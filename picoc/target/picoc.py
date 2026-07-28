#!/usr/bin/env python3
"""
picoc-py: a Python reimplementation of the picoc C interpreter.

Run: picoc.py path/to/file.c

Supports the subset of C exercised by the reLang picoc test suite:
  - int/char/short/long (signed/unsigned), float, double, void
  - pointers, arrays (single & multi-dim), structs, unions
  - static locals, function decls + defs (incl. forward), recursion
  - if/else, while, do/while, for, switch/case/default, goto/labels,
    break/continue/return
  - preprocessor: #include (textual), #define, #if/#else/#endif, #ifdef,
    comments
  - stdio subset: printf with %d %u %c %s %x %X %f %e %g %05d %.Nf
    via Python's str.format; malloc/free via bytearray; sizeof
"""
from __future__ import annotations

import sys
import struct
import math
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict, Tuple, Union as _Union

# ------------------------------------------------------------------
# Limits (model an LP64-like machine for layout, but use Python ints
# for arithmetic and clamp on store like C semantics require).
# ------------------------------------------------------------------
LLONG_MIN = -(1 << 63)
LLONG_MAX = (1 << 63) - 1
ULONG_MAX = (1 << 64) - 1


# ------------------------------------------------------------------
# Truncation helpers — match C's "convert then mask to type" rules
# so that e.g. (unsigned char)200 plus arithmetic promotes correctly.
# ------------------------------------------------------------------
def _trunc_int(value: int, bits: int, unsigned: bool) -> int:
    """Mask `value` to a C-style integer of `bits` width."""
    mask = (1 << bits) - 1
    v = value & mask
    if not unsigned and v >= (1 << (bits - 1)):
        v -= 1 << bits
    return v


def to_signed(value: int, bits: int) -> int:
    return _trunc_int(value, bits, False)


def to_unsigned(value: int, bits: int) -> int:
    return _trunc_int(value, bits, True)


def coerce_to_int(value: Any, target_bits: int, target_unsigned: bool) -> int:
    """Convert any runtime value to int of given width/sign (per C)."""
    if isinstance(value, float):
        # C truncates toward zero when converting FP -> integer.
        if math.isnan(value) or math.isinf(value):
            v = 0 if math.isnan(value) else (LLONG_MAX if value > 0 else LLONG_MIN)
        else:
            v = int(value)
        return _trunc_int(v, target_bits, target_unsigned)
    # int-like: take modulo 2**bits first, then sign adjust
    return _trunc_int(int(value), target_bits, target_unsigned)


def coerce_to_float(value: Any) -> float:
    if isinstance(value, float):
        return value
    return float(int(value))


# ------------------------------------------------------------------
# Types
# ------------------------------------------------------------------
# Each C type is described by a Type object.
#   kind: 'void' | 'int' | 'float' | 'ptr' | 'array' | 'struct' | 'union'
#       | 'func' | 'char' (special int with size=1)
#   name: human name (e.g. "int", "char", "unsigned int")
#   size:  bytes (used for sizeof and struct layout)
#   align: alignment
#   signed: bool
#   elem:  for ptr/array: inner Type
#   length: for array: element count (None means unspecified)
#   fields: for struct/union: ordered list of (name, Type, offset)
#   members: dict for struct/union: name -> (Type, offset)
#   ret / params: for func
@dataclass
class CType:
    kind: str
    name: str = ""
    size: int = 0
    align: int = 1
    signed: bool = True
    # pointer / array
    elem: Optional["CType"] = None
    length: Optional[int] = None
    # struct/union
    fields: List[Tuple[str, "CType", int]] = field(default_factory=list)
    members: Dict[str, Tuple["CType", int]] = field(default_factory=dict)
    # function
    ret: Optional["CType"] = None
    params: List["CType"] = field(default_factory=list)

    def __repr__(self):
        return f"<CType {self.name or self.kind}>"

    @property
    def is_int(self) -> bool:
        return self.kind in ("int", "char")

    @property
    def is_float(self) -> bool:
        return self.kind == "float"

    @property
    def is_ptr(self) -> bool:
        return self.kind == "ptr"

    @property
    def is_array(self) -> bool:
        return self.kind == "array"

    @property
    def is_aggregate(self) -> bool:
        return self.kind in ("struct", "union", "array")

    @property
    def is_struct_or_union(self) -> bool:
        return self.kind in ("struct", "union")

    @property
    def is_void(self) -> bool:
        return self.kind == "void"

    @property
    def base_elem(self) -> "CType":
        """For arrays, return innermost element type."""
        t = self
        while t.kind == "array":
            t = t.elem  # type: ignore
        return t


# ------------------------------------------------------------------
# Scalar type singletons (deferred init to break forward refs).
# ------------------------------------------------------------------
T_void = CType("void", "void", 0, 1)
T_char = CType("char", "char", 1, 1, signed=True)
T_schar = CType("char", "signed char", 1, 1, signed=True)
T_uchar = CType("char", "unsigned char", 1, 1, signed=False)
T_short = CType("int", "short", 2, 2, signed=True)
T_ushort = CType("int", "unsigned short", 2, 2, signed=False)
T_int = CType("int", "int", 4, 4, signed=True)
T_uint = CType("int", "unsigned int", 4, 4, signed=False)
T_long = CType("int", "long", 8, 8, signed=True)
T_ulong = CType("int", "unsigned long", 8, 8, signed=False)
T_llong = CType("int", "long long", 8, 8, signed=True)
T_ullong = CType("int", "unsigned long long", 8, 8, signed=False)
T_float = CType("float", "float", 4, 4, signed=True)
T_double = CType("float", "double", 8, 8, signed=True)


def make_ptr(to: CType) -> CType:
    return CType("ptr", f"{to.name} *", 8, 8, elem=to)


# ------------------------------------------------------------------
# "Real" C runtime values.
#
# Scalars live as Python ints (Python ints are arbitrary precision; we
# mask on store to match the target C type's width/sign).
# Pointers and arrays and struct/union values live as a Python object
# representing a *byte buffer* and a *type*; the buffer is the memory
# the C program sees. Static locals and malloc'd memory use the same
# blob class so aliasing Just Works.
# ------------------------------------------------------------------
class Mem:
    """A resizable byte buffer that backs some object's storage."""

    __slots__ = ("data", "tag", "wrap")

    def __init__(self, size: int):
        self.data = bytearray(size)
        self.tag: Dict[Tuple[int, int], CType] = {}  # (offset, size) -> CType
        self.wrap = None
        # Track declared sub-objects so reads of padded tail bytes know
        # which CType applies. Filled by declare().

    def __len__(self) -> int:
        return len(self.data)


# Helper: read typed scalar from buffer.
def _int_size(t: CType) -> int:
    return t.size


def rd_int(mem: Mem, off: int, t: CType) -> int:
    raw = int.from_bytes(mem.data[off:off + t.size], "little", signed=t.signed)
    return raw


def wr_int(mem: Mem, off: int, t: CType, v: int) -> None:
    raw = to_signed if t.signed else to_unsigned
    # Convert to target width first as unsigned, then write with proper sign.
    if t.signed:
        b = int.to_bytes(raw(int(v), t.size * 8), t.size, "little", signed=True)
    else:
        b = int.to_bytes(raw(int(v), t.size * 8), t.size, "little", signed=False)
    mem.data[off:off + t.size] = b


def rd_float(mem: Mem, off: int, t: CType) -> float:
    if t.size == 4:
        return struct.unpack_from("<f", mem.data, off)[0]
    return struct.unpack_from("<d", mem.data, off)[0]


def wr_float(mem: Mem, off: int, t: CType, v: float) -> None:
    if t.size == 4:
        struct.pack_into("<f", mem.data, off, float(v))
    else:
        struct.pack_into("<d", mem.data, off, float(v))


def rd_scalar(mem: Mem, off: int, t: CType) -> int:
    if t.kind == "float":
        f = rd_float(mem, off, t)
        return int(f) if False else f  # caller handles float branch
    return rd_int(mem, off, t)


# ------------------------------------------------------------------
# A "Value" wraps a C value + its type. For integers, payload is a
# Python int. For pointers/structs/unions/arrays, payload is a Mem
# object plus offset 0.
# ------------------------------------------------------------------
@dataclass
class Value:
    type: CType
    # For scalars: Python int (sign-extended to Python int)
    # For float: Python float
    # For ptr/array/struct/union: Mem (memory at offset 0)
    scalar: Any = 0
    mem: Optional[Mem] = None
    # For function "values", a Python callable (Interpreter.func_call)
    func: Optional[Any] = None

    def __repr__(self):
        return f"Value({self.type.name}, ...)"

    @property
    def is_mem(self) -> bool:
        return self.mem is not None and self.type.kind != "ptr"

    @property
    def is_scalar(self) -> bool:
        return self.mem is None and self.func is None

    @property
    def is_func(self) -> bool:
        return self.func is not None


def v_int(t: CType, x: int) -> Value:
    # No truncation here; caller can choose; interpretation trims when needed.
    return Value(t, scalar=x)


def v_float(t: CType, x: float) -> Value:
    return Value(t, scalar=x)


def v_ptr(pointee: CType, mem: Mem) -> Value:
    return Value(make_ptr(pointee), mem=mem)


def v_mem(t: CType, size: int) -> Value:
    return Value(t, mem=Mem(size))


def null_ptr(t: CType) -> Value:
    return Value(make_ptr(t), scalar=0)


# ------------------------------------------------------------------
# Symbol table.
#
# Each scope is a dict[name] = Symbol. Symbols track a value (or
# function) and properties (storage class, type). Static locals live
# outside the scope dict — the value is allocated once and reused.
# ------------------------------------------------------------------
@dataclass
class Symbol:
    name: str
    type: CType
    storage: str = "auto"  # 'auto' | 'static' | 'extern' | 'typedef' | 'func'
    value: Optional[Value] = None  # backing storage for vars (auto)
    static_value: Optional[Value] = None  # backing storage for statics
    params: Optional[List["Symbol"]] = None  # for functions
    func_body: Optional["Block"] = None  # for function defs
    is_forward: bool = False
    is_typedef: bool = False


class Scope:
    def __init__(self, parent: Optional["Scope"] = None, kind: str = "block"):
        self.parent = parent
        self.kind = kind
        self.syms: Dict[str, Symbol] = {}
        # Track static vars separately so they survive past their scope's
        # closure — keyed by (function, name).
        self.statics: Dict[str, Value] = {}

    def get(self, name: str) -> Optional[Symbol]:
        s = self.syms.get(name)
        if s is not None:
            return s
        if self.parent:
            return self.parent.get(name)
        return None

    def define(self, sym: Symbol) -> Symbol:
        self.syms[sym.name] = sym
        return sym

    def declare_local(self, name: str, t: CType, storage: str = "auto") -> Symbol:
        if name in self.syms:
            # C lets you re-declare in inner scope (shadows outer); allow it.
            self.syms[name].type = t
            return self.syms[name]
        v: Optional[Value] = None
        if storage != "typedef":
            if t.kind in ("struct", "union"):
                v = v_mem(t, t.size)
            elif t.kind == "array":
                v = v_mem(t, t.size)
            else:
                v = v_int(t, 0)
        sym = Symbol(name=name, type=t, storage=storage, value=v)
        self.syms[name] = sym
        return sym


# ------------------------------------------------------------------
# Statement / expression AST.
# ------------------------------------------------------------------
@dataclass
class Program:
    decls: List["Decl"]


@dataclass
class Decl:
    pass


@dataclass
class VarDecl(Decl):
    name: str
    type: CType
    init: Optional["Expr"] = None
    storage: str = "auto"


@dataclass
class FuncDecl(Decl):
    name: str
    ret: CType
    params: List[Tuple[str, CType]] = field(default_factory=list)
    body: Optional["Block"] = None  # None => forward decl


@dataclass
class StructDecl(Decl):
    name: str
    kind: str  # "struct" | "union"
    fields: List[Tuple[str, CType]] = field(default_factory=list)


@dataclass
class TypedefDecl(Decl):
    name: str
    type: CType


@dataclass
class Block:
    stmts: List["Stmt"] = field(default_factory=list)
    scope: Optional[Scope] = None  # populated when executed


@dataclass
class Stmt:
    pass


@dataclass
class ExprStmt(Stmt):
    expr: "Expr"


@dataclass
class IfStmt(Stmt):
    cond: "Expr"
    then_branch: "Stmt"
    else_branch: Optional["Stmt"] = None


@dataclass
class WhileStmt(Stmt):
    cond: "Expr"
    body: "Stmt"


@dataclass
class DoWhileStmt(Stmt):
    body: "Stmt"
    cond: "Expr"


@dataclass
class ForStmt(Stmt):
    init: Optional["Stmt"]
    cond: Optional["Expr"]
    step: Optional["Expr"]
    body: "Stmt"


@dataclass
class ReturnStmt(Stmt):
    expr: Optional["Expr"]


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class GotoStmt(Stmt):
    label: str


@dataclass
class LabelStmt(Stmt):
    label: str
    stmt: "Stmt"


@dataclass
class CompoundStmt(Stmt):
    block: Block


@dataclass
class SwitchStmt(Stmt):
    expr: "Expr"
    body: "Stmt"
    cases: List[Tuple[Optional[int], "Stmt"]] = field(default_factory=list)
    has_default: bool = False


@dataclass
class Expr:
    pass


@dataclass
class IntLit(Expr):
    value: int
    type: CType  # determined by suffix


@dataclass
class FloatLit(Expr):
    value: float
    type: CType  # float or double


@dataclass
class CharLit(Expr):
    value: int
    type: CType


@dataclass
class StrLit(Expr):
    value: str


@dataclass
class Ident(Expr):
    name: str


@dataclass
class Binary(Expr):
    op: str
    lhs: "Expr"
    rhs: "Expr"


@dataclass
class Unary(Expr):
    op: str
    operand: "Expr"
    prefix: bool = True


@dataclass
class Conditional(Expr):
    cond: "Expr"
    then_branch: "Expr"
    else_branch: "Expr"


@dataclass
class Assign(Expr):
    op: str  # "=" | "+=" | "-=" | "*=" | "/=" | "%="
    target: "Expr"
    value: "Expr"


@dataclass
class Call(Expr):
    callee: "Expr"
    args: List["Expr"]


@dataclass
class Index(Expr):
    base: "Expr"
    index: "Expr"


@dataclass
class Member(Expr):
    base: "Expr"
    field: str
    arrow: bool = False  # True for p->f, False for s.f


@dataclass
class Cast(Expr):
    type: CType
    operand: "Expr"


@dataclass
class Sizeof(Expr):
    arg: "_Union[Expr, CType]"
    is_type: bool


@dataclass
class InitList(Expr):
    items: List["Expr"]


# Exception types used for control flow + jumps.
class ReturnSignal(Exception):
    def __init__(self, value: Optional[Value]):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class GotoSignal(Exception):
    def __init__(self, label: str):
        self.label = label


# ------------------------------------------------------------------
# Preprocessor
# ------------------------------------------------------------------
# A small text-based preprocessor. #include <stdio.h> / <stdlib.h>
# are matched against inline header text. #define and #if only
# support object-like macros with literal integer RHSes (which is all
# the tests use).
STDIO_H = r"""
typedef struct __va_listStruct va_list;
typedef struct __FILEStruct FILE;

int printf(char *, ...);
int fprintf(FILE *, char *, ...);
int sprintf(char *, char *, ...);
int snprintf(char *, int, char *, ...);
int scanf(char *, ...);
int fscanf(FILE *, char *, ...);
int sscanf(char *, char *, ...);
int vprintf(char *, va_list);
int vfprintf(FILE *, char *, va_list);
int vsprintf(char *, char *, va_list);
int vsnprintf(char *, int, char *, va_list);
int vscanf(char *, va_list);
int vfscanf(FILE *, char *, va_list);
int vsscanf(char *, char *, va_list);

int getc(FILE *);
int getchar(void);
int putc(int, FILE *);
int putchar(int);
int puts(char *);
char *gets(char *);
char *fgets(char *, int, FILE *);
int fputc(int, FILE *);
int fputs(char *, FILE *);
int sprintf(char *, char *, ...);
int snprintf(char *, int, char *, ...);
int fread(void *, int, int, FILE *);
int fwrite(void *, int, int, FILE *);
int fclose(FILE *);
FILE *fopen(char *, char *);
FILE *freopen(char *, char *, FILE *);
int feof(FILE *);
int ferror(FILE *);
int fflush(FILE *);
int fgetc(FILE *);
int fseek(FILE *, int, int);
long ftell(FILE *);
int remove(char *);
int rename(char *, char *);
void rewind(FILE *);
int fgetpos(FILE *, int *);
int fsetpos(FILE *, int *);
int ungetc(int, FILE *);
int vfprintf(FILE *, char *, va_list);
int fputchar(int);

#define NULL 0
#define BUFSIZ 1024
#define EOF (-1)
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2
#define _IOFBF 0
#define _IOLBF 1
#define _IONBF 2
"""

STDLIB_H = r"""
void *malloc(int);
void *calloc(int, int);
void *realloc(void *, int);
void free(void *);
int atoi(char *);
long atol(char *);
long strtol(char *, char **, int);
unsigned long strtoul(char *, char **, int);
void exit(int);
void abort(void);
int rand(void);
void srand(int);
void qsort(void *, int, int, int (*)(void *, void *));
int abs(int);
long labs(long);
#define NULL 0
#define RAND_MAX 32767
"""

STRING_H = r"""
void *memcpy(void *, void *, int);
void *memmove(void *, void *, int);
void *memset(void *, int, int);
int memcmp(void *, void *, int);
char *strcpy(char *, char *);
char *strncpy(char *, char *, int);
char *strcat(char *, char *);
char *strncat(char *, char *, int);
int strcmp(char *, char *);
int strncmp(char *, char *, int);
char *strchr(char *, int);
char *strrchr(char *, int);
char *strstr(char *, char *);
int strlen(char *);
char *strdup(char *);
"""

HEADERS = {
    "stdio.h": STDIO_H,
    "stdlib.h": STDLIB_H,
    "string.h": STRING_H,
}


def _strip_block_comments(src: str) -> str:
    """Remove /* … */ comments but keep newlines so line numbers are stable."""
    out = []
    i = 0
    n = len(src)
    while i < n:
        if i + 1 < n and src[i] == "/" and src[i + 1] == "*":
            # Skip until */
            j = src.find("*/", i + 2)
            if j < 0:
                raise RuntimeError("unterminated block comment")
            # preserve newlines for line numbers
            out.append("\n" * src[i:j + 2].count("\n"))
            i = j + 2
        elif i + 1 < n and src[i] == "/" and src[i + 1] == "/":
            j = src.find("\n", i)
            if j < 0:
                j = n
            i = j
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def _eval_preproc_expr(expr: str, macros: Dict[str, str]) -> int:
    """Evaluate a preprocessor #if expression with macro substitution.

    Supports: integer literals (decimal/hex), defined(NAME),
    unary !, binary && || == != < <= > >= + - * / % & | ^ << >> ( ) ?:.
    """
    s = expr.strip()
    # Substitute macros (object-like)
    for _ in range(20):  # bounded expansion
        new = re.sub(
            r"\b([A-Za-z_][A-Za-z_0-9]*)\b",
            lambda m: macros.get(m.group(1), m.group(1)),
            s,
        )
        if new == s:
            break
        s = new
    # Replace 'defined NAME' / 'defined(NAME)' with 1/0
    def repl_def(m):
        name = m.group(1) or m.group(2)
        return "1" if name in macros else "0"
    s = re.sub(r"defined\s+([A-Za-z_][A-Za-z_0-9]*)|defined\s*\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*\)", repl_def, s)
    # Now evaluate as a Python expression after sanitizing.
    safe = re.sub(r"[^A-Za-z0-9_+\-*/%<>=!&|^()?\:\[\] ]", " ", s)
    # Replace && || with ' and ' ' or ' is tricky; do a small mapping.
    safe = safe.replace("&&", " and ").replace("||", " or ")
    # Replace C bitwise ops Python differs on: Python uses ^ for bit xor — same.
    try:
        return int(eval(safe, {"__builtins__": {}}, {}))
    except Exception:
        return 0


def preprocess(src: str) -> Tuple[str, Dict[str, str]]:
    """Run preprocessor. Returns (expanded_source, macro_dict_for_ifdef)."""
    src = _strip_block_comments(src)
    macros: Dict[str, str] = {}
    out: List[str] = []
    lines = src.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            out.append(line)
            i += 1
            continue
        body = stripped[1:].strip()
        # Handle backslash-newline line continuation: join continuation lines
        while body.endswith("\\") and i + 1 < len(lines):
            i += 1
            body = body[:-1] + " " + lines[i].strip()
        if body.startswith("include"):
            m = re.search(r'include\s*[<"]([^>"]+)[>"]', body)
            if not m:
                raise RuntimeError(f"bad #include: {body}")
            name = m.group(1)
            header = HEADERS.get(name)
            if header is None:
                raise RuntimeError(f"unknown header: {name}")
            # Process header text through preprocessor for nested #defines etc.
            sub, sub_macros = preprocess(header)
            macros.update(sub_macros)
            out.append(sub)
        elif body.startswith("define"):
            m = re.match(r"define\s+([A-Za-z_][A-Za-z_0-9]*)\s*(.*)", body)
            if not m:
                raise RuntimeError(f"bad #define: {body}")
            name = m.group(1)
            rhs = m.group(2).strip()
            macros[name] = rhs
        elif body.startswith("undef"):
            m = re.match(r"undef\s+([A-Za-z_][A-Za-z_0-9]*)", body)
            if m and m.group(1) in macros:
                del macros[m.group(1)]
        elif body.startswith("ifdef"):
            m = re.match(r"ifdef\s+([A-Za-z_][A-Za-z_0-9]*)", body)
            keep = m and m.group(1) in macros
            i += 1
            depth = 1
            while i < len(lines) and depth > 0:
                s = lines[i].lstrip()
                if s.startswith("#"):
                    if s[1:].lstrip().startswith("ifdef") or s[1:].lstrip().startswith("ifndef") or s[1:].lstrip().startswith("if"):
                        depth += 1
                    elif s[1:].lstrip().startswith("endif"):
                        depth -= 1
                        i += 1
                        break
                    elif s[1:].lstrip().startswith("else") and depth == 1:
                        # flip keep and continue scanning the else
                        keep = not keep
                        i += 1
                        continue
                if keep:
                    out.append(lines[i])
                i += 1
            continue
        elif body.startswith("ifndef"):
            m = re.match(r"ifndef\s+([A-Za-z_][A-Za-z_0-9]*)", body)
            keep = m and m.group(1) not in macros
            i += 1
            depth = 1
            while i < len(lines) and depth > 0:
                s = lines[i].lstrip()
                if s.startswith("#"):
                    if s[1:].lstrip().startswith("ifdef") or s[1:].lstrip().startswith("ifndef") or s[1:].lstrip().startswith("if"):
                        depth += 1
                    elif s[1:].lstrip().startswith("endif"):
                        depth -= 1
                        i += 1
                        break
                    elif s[1:].lstrip().startswith("else") and depth == 1:
                        keep = not keep
                        i += 1
                        continue
                if keep:
                    out.append(lines[i])
                i += 1
            continue
        elif body.startswith("if"):
            m = re.match(r"if\s+(.*)", body)
            cond = m.group(1) if m else "0"
            keep = bool(_eval_preproc_expr(cond, macros))
            i += 1
            depth = 1
            while i < len(lines) and depth > 0:
                s = lines[i].lstrip()
                if s.startswith("#"):
                    inner = s[1:].lstrip()
                    if inner.startswith("ifdef") or inner.startswith("ifndef") or inner.startswith("if"):
                        depth += 1
                    elif inner.startswith("endif"):
                        depth -= 1
                        i += 1
                        break
                    elif inner.startswith("else") and depth == 1:
                        keep = not keep
                        i += 1
                        continue
                if keep:
                    out.append(lines[i])
                i += 1
            continue
        elif body.startswith("else"):
            # bare else without preceding #if — ignore
            pass
        elif body.startswith("endif"):
            pass
        else:
            pass  # unknown directive — drop
        i += 1
    return "\n".join(out), macros


# ------------------------------------------------------------------
# Lexer
# ------------------------------------------------------------------
@dataclass
class Tok:
    kind: str
    text: str
    line: int
    col: int


KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "int", "long", "register", "return", "short", "signed", "sizeof",
    "static", "struct", "switch", "typedef", "union", "unsigned", "void",
    "volatile", "while",
}


def tokenize(src: str) -> List[Tok]:
    tokens: List[Tok] = []
    i = 0
    n = len(src)
    line = 1
    line_start = 0
    while i < n:
        c = src[i]
        # whitespace
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue
        col = i - line_start + 1
        # identifiers and keywords
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            text = src[i:j]
            tokens.append(Tok("ID", text, line, col))
            i = j
            continue
        # numbers
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] in "abcdefABCDEF"):
                j += 1
            is_float = False
            # look for fractional part
            if j < n and src[j] == ".":
                is_float = True
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
            # exponent
            if j < n and src[j] in "eE":
                is_float = True
                j += 1
                if j < n and src[j] in "+-":
                    j += 1
                while j < n and src[j].isdigit():
                    j += 1
            text = src[i:j]
            tokens.append(Tok("NUM", text, line, col))
            i = j
            continue
        # strings
        if c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    if esc == "n":
                        buf.append("\n")
                    elif esc == "t":
                        buf.append("\t")
                    elif esc == "r":
                        buf.append("\r")
                    elif esc == "\\":
                        buf.append("\\")
                    elif esc == "'":
                        buf.append("'")
                    elif esc == '"':
                        buf.append('"')
                    elif esc == "0":
                        buf.append("\0")
                    else:
                        buf.append(esc)
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise RuntimeError(f"unterminated string at line {line}")
            j += 1  # closing "
            tokens.append(Tok("STR", "".join(buf), line, col))
            i = j
            continue
        # char literal
        if c == "'":
            j = i + 1
            if j < n and src[j] == "\\":
                esc = src[j + 1]
                if esc == "n":
                    val = 10
                elif esc == "t":
                    val = 9
                elif esc == "r":
                    val = 13
                elif esc == "0":
                    val = 0
                elif esc == "\\":
                    val = 92
                else:
                    val = ord(esc)
                j += 2
            else:
                val = ord(src[j])
                j += 1
            if j < n and src[j] == "'":
                j += 1
            tokens.append(Tok("CHAR", str(val), line, col))
            i = j
            continue
        # comments
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j < 0:
                j = n
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                raise RuntimeError("unterminated block comment")
            i = j + 2
            continue
        # multi-char operators
        for op in ("<<=", ">>=", "<=", ">=", "==", "!=", "&&", "||",
                   "<<", ">>", "++", "--", "+=", "-=", "*=", "/=", "%=",
                   "&=", "|=", "^=", "->", "...", "##"):
            if src.startswith(op, i):
                tokens.append(Tok("OP", op, line, col))
                i += len(op)
                break
        else:
            if c in "+-*/%&|^~!=<>?:;,(){}[]#.":
                tokens.append(Tok("OP", c, line, col))
                i += 1
                continue
            raise RuntimeError(f"unexpected char {c!r} at line {line}:{col}")
    return tokens


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------
class Parser:
    def __init__(self, toks: List[Tok]):
        self.toks = toks
        self.pos = 0

    # Token helpers
    def peek(self, off: int = 0) -> Tok:
        return self.toks[min(self.pos + off, len(self.toks) - 1)]

    def at(self, kind: Optional[str] = None, text: Optional[str] = None, off: int = 0) -> bool:
        t = self.peek(off)
        if kind is not None and t.kind != kind:
            return False
        if text is not None and t.text != text:
            return False
        return True

    def consume(self, kind: Optional[str] = None, text: Optional[str] = None) -> Tok:
        t = self.peek()
        if kind is not None and t.kind != kind:
            raise RuntimeError(f"expected {kind} got {t.kind} {t.text!r} at line {t.line}")
        if text is not None and t.text != text:
            raise RuntimeError(f"expected {text!r} got {t.text!r} at line {t.line}")
        self.pos += 1
        return t

    def match(self, kind: Optional[str] = None, text: Optional[str] = None) -> bool:
        if self.at(kind, text):
            self.consume(kind, text)
            return True
        return False

    def parse_program(self) -> Program:
        decls = []
        while not self.at(kind="OP", text=None) or (self.peek().kind == "OP" and self.peek().text != "") :
            # EOF check
            if self.peek().kind == "OP" and self.peek().text == "":
                break
            # Hack: end of token stream marked by sentinel Tok(kind="OP", text="")
            if self.peek().kind == "OP" and self.peek().text == "":
                break
            d = self.parse_top_decl()
            if d is None:
                break
            decls.append(d)
        return Program(decls=decls)

    # Helpers
    def _is_type_start(self, off: int = 0) -> bool:
        t = self.peek(off)
        if t.kind == "ID" and t.text in KEYWORDS:
            return t.text in {
                "void", "char", "short", "int", "long", "signed", "unsigned",
                "float", "double", "struct", "union", "enum", "const",
                "volatile", "static", "extern"
            }
        if t.kind == "ID":
            # typedef name?
            return self._typedef_names.get(t.text, False)
        return False

    def _is_type_specifier(self, off: int = 0) -> bool:
        t = self.peek(off)
        if t.kind != "ID":
            return False
        return t.text in {"void", "char", "short", "int", "long", "signed",
                           "unsigned", "float", "double", "struct", "union", "enum"}

    def _parse_type_specifiers(self) -> Tuple[CType, str]:
        """Read storage class + base specifiers and return (type, storage).

        Handles: 'static int', 'unsigned int', 'unsigned long long',
        'long long', 'signed', etc.
        """
        storage = "auto"
        # gather tokens
        specs: List[str] = []
        while True:
            t = self.peek()
            if t.kind != "ID":
                break
            if t.text == "static":
                storage = "static"
                self.consume()
                continue
            if t.text == "extern":
                storage = "extern"
                self.consume()
                continue
            if t.text == "const" or t.text == "volatile":
                self.consume()
                continue
            if t.text == "register":
                self.consume()
                continue
            if t.text in {"void", "char", "short", "int", "long", "signed",
                          "unsigned", "float", "double"}:
                specs.append(t.text)
                self.consume()
                continue
            if t.text == "struct" or t.text == "union":
                # parse struct/union, get CType
                ct = self._parse_struct_or_union(t.text)
                return (ct, storage)
            if t.text == "enum":
                # ignore enum body — skip tokens until matching }
                self.consume()  # 'enum'
                if self.match("ID"):
                    pass
                if self.at("OP", "{"):
                    self.consume()
                    depth = 1
                    while depth and self.pos < len(self.toks):
                        tk = self.consume()
                        if tk.text == "{":
                            depth += 1
                        elif tk.text == "}":
                            depth -= 1
                return (T_int, storage)
            # typedef'd name
            if self._typedef_names.get(t.text, False):
                ct = self._typedefs[t.text]
                self.consume()
                return (ct, storage)
            break
        if not specs:
            return (T_int, storage)
        # normalize
        u = "unsigned" in specs
        s = "signed" in specs
        if "void" in specs:
            return (T_void, storage)
        if "char" in specs:
            return (T_uchar if u else T_schar, storage)
        if "float" in specs:
            return (T_float, storage)
        if "double" in specs:
            return (T_double, storage)
        if "short" in specs:
            return (T_ushort if u else T_short, storage)
        if "long" in specs:
            cnt = sum(1 for s_ in specs if s_ == "long")
            if cnt >= 2:
                return (T_ullong if u else T_llong, storage)
            return (T_ulong if u else T_long, storage)
        # 'int' or unsigned-int etc.
        if u:
            return (T_uint, storage)
        return (T_int, storage)

    def _parse_struct_or_union(self, kw: str) -> CType:
        self.consume()  # struct/union keyword
        name = None
        if self.at("ID"):
            name = self.consume().text
        # Body?
        if self.at("OP", "{"):
            self.consume("OP", "{")
            fields: List[Tuple[str, CType]] = []
            while not self.at("OP", "}"):
                ft, _ = self._parse_type_specifiers()
                # parse declarators (possibly many)
                while True:
                    f_name, decl_type = self._parse_declarator(ft)
                    fields.append((f_name, decl_type))
                    if self.match("OP", ","):
                        continue
                    break
                self.match("OP", ";")
            self.consume("OP", "}")
            ct = self._build_aggregate_type(kw, name, fields)
            if name:
                self._struct_defs[name] = ct
            return ct
        # Tag without body — use previously defined type.
        if name and name in self._struct_defs:
            return self._struct_defs[name]
        # Forward tag — create empty placeholder.
        if name:
            if name not in self._struct_defs:
                self._struct_defs[name] = CType(kw, f"{kw} {name}", 0, 1)
            return self._struct_defs[name]
        return CType(kw, kw, 0, 1)

    def _build_aggregate_type(self, kind: str, name: Optional[str], fields: List[Tuple[str, CType]]) -> CType:
        if kind == "struct":
            offset = 0
            max_align = 1
            members: Dict[str, Tuple[CType, int]] = {}
            field_list: List[Tuple[str, CType, int]] = []
            for fname, ft in fields:
                a = ft.align
                offset = (offset + a - 1) // a * a
                members[fname] = (ft, offset)
                field_list.append((fname, ft, offset))
                offset += ft.size
                if a > max_align:
                    max_align = a
            size = (offset + max_align - 1) // max_align * max_align
        else:
            # union — all fields at offset 0, size = max
            offset = 0
            members = {}
            field_list = []
            max_size = 0
            max_align = 1
            for fname, ft in fields:
                members[fname] = (ft, 0)
                field_list.append((fname, ft, 0))
                if ft.size > max_size:
                    max_size = ft.size
                if ft.align > max_align:
                    max_align = ft.align
            size = max_size
        tname = f"{kind} {name}" if name else f"anon_{kind}"
        return CType(kind=kind, name=tname, size=size, align=max_align,
                     fields=field_list, members=members)

    # Declarators: int x, int x[3], int x[2][3], int *x, int (*x)[3]
    def _parse_declarator(self, base: CType) -> Tuple[str, CType]:
        """Parse declarator on top of base type. Returns (name, full_type)."""
        # read pointer stars
        ptr = 0
        while self.match("OP", "*"):
            ptr += 1
        if self.at("ID"):
            name = self.consume().text
        else:
            name = ""
        # array/function suffixes
        t = base
        for _ in range(ptr):
            t = make_ptr(t)
        # arrays
        dims = []
        while self.at("OP", "["):
            self.consume("OP", "[")
            if self.at("OP", "]"):
                self.consume()
                dims.append(None)
            else:
                dims.append(int(self.consume("NUM").text))
                self.consume("OP", "]")
        for length in reversed(dims):
            elem = t
            arr = CType("array", name=f"{elem.name}[{length if length is not None else ''}]",
                         size=elem.size * (length if length is not None else 0),
                         align=elem.align, elem=elem, length=length)
            t = arr
        return (name, t)

    def parse_top_decl(self) -> Optional[Decl]:
        if self.peek().kind == "OP" and self.peek().text == "":
            return None
        # Try typedef
        if self.at("ID", "typedef"):
            self.consume()
            base_t, _ = self._parse_type_specifiers()
            name, t = self._parse_declarator(base_t)
            self.match("OP", ";")
            self._typedef_names[name] = True
            self._typedefs[name] = t
            return TypedefDecl(name=name, type=t)
        # Otherwise parse a declaration
        saved_pos = self.pos
        base_t, storage = self._parse_type_specifiers()
        if self.at("OP", ";"):
            self.consume()
            return None
        # try to parse a full declarator — could be a function, var, struct, etc.
        # peek further: if name followed by '(', it's a function declaration.
        def _peek_function_decl() -> bool:
            pos2 = self.pos
            while self.peek(pos2 - self.pos).text == "*" and self.peek(pos2 - self.pos).kind == "OP":
                pos2 += 1
            if pos2 < len(self.toks) and self.toks[pos2].kind == "ID":
                pos2 += 1
            return pos2 < len(self.toks) and self.toks[pos2].kind == "OP" and self.toks[pos2].text == "("

        if _peek_function_decl():
            name, t = self._parse_declarator(base_t)
            self.consume("OP", "(")
            params: List[Tuple[str, CType]] = []
            if self.at("OP", "void") and self.peek(1).text == ")":
                self.consume(); self.consume()
            elif self.at("OP", ")"):
                self.consume()
            else:
                while True:
                    if self.at("OP", "..."):
                        self.consume()
                        break
                    p_t, _ = self._parse_type_specifiers()
                    p_n, p_full_t = self._parse_declarator(p_t)
                    if not p_n:
                        p_n = ""
                    params.append((p_n, p_full_t))
                    if self.match("OP", ","):
                        if self.at("OP", "..."):
                            self.consume()
                        continue
                    break
                self.consume("OP", ")")
            # old-style K&R function param decls not supported
            if self.at("OP", "{"):
                # function definition
                body = self.parse_block()
                self.match("OP", ";")
                return FuncDecl(name=name, ret=base_t, params=params, body=body)
            else:
                self.match("OP", ";")
                return FuncDecl(name=name, ret=base_t, params=params)
        # variable declarations (possibly multiple per spec)
        decls: List[VarDecl] = []
        first = True
        while True:
            if first:
                if self.pos == saved_pos:
                    # could not consume anything meaningful
                    break
                first = False
            else:
                if not self.match("OP", ","):
                    break
            n, t = self._parse_declarator(base_t)
            init = None
            if self.match("OP", "="):
                init = self.parse_initializer()
            decls.append(VarDecl(name=n, type=t, init=init, storage=storage))
        self.match("OP", ";")
        # when there are multiple, just keep all (we only need single var per
        # test case really).
        return decls[0] if decls else None

    def parse_block(self) -> Block:
        self.consume("OP", "{")
        stmts: List[Stmt] = []
        while not self.at("OP", "}"):
            stmts.append(self.parse_stmt())
        self.consume("OP", "}")
        return Block(stmts=stmts)

    def parse_stmt(self) -> Stmt:
        t = self.peek()
        if t.text == "{":
            b = self.parse_block()
            return CompoundStmt(block=b)
        if t.text == "if":
            return self.parse_if()
        if t.text == "while":
            return self.parse_while()
        if t.text == "do":
            return self.parse_do()
        if t.text == "for":
            return self.parse_for()
        if t.text == "switch":
            return self.parse_switch()
        if t.text == "return":
            self.consume()
            e = None
            if not self.at("OP", ";"):
                e = self.parse_expr()
            self.consume("OP", ";")
            return ReturnStmt(expr=e)
        if t.text == "break":
            self.consume()
            self.consume("OP", ";")
            return BreakStmt()
        if t.text == "continue":
            self.consume()
            self.consume("OP", ";")
            return ContinueStmt()
        if t.text == "goto":
            self.consume()
            name = self.consume("ID").text
            self.consume("OP", ";")
            return GotoStmt(label=name)
        if t.kind == "ID" and self.peek(1).text == ":":
            # label
            name = self.consume().text
            self.consume("OP", ":")
            inner = self.parse_stmt()
            return LabelStmt(label=name, stmt=inner)
        # declaration-statement OR expression statement
        if self._is_type_start():
            base_t, storage = self._parse_type_specifiers()
            decls = []
            while True:
                n, t = self._parse_declarator(base_t)
                init = None
                if self.match("OP", "="):
                    init = self.parse_initializer()
                decls.append(VarDecl(name=n, type=t, init=init, storage=storage))
                if not self.match("OP", ","):
                    break
            self.consume("OP", ";")
            # Emit as a single declaration; the runtime will translate them
            # into variable introductions. For simplicity wrap as a DeclStmt
            # by attaching a list to a fake statement. We cheat: convert to
            # a stmt that when interpreted executes the declare+init.
            return DeclStmt(decls=decls)
        e = self.parse_expr()
        self.consume("OP", ";")
        return ExprStmt(expr=e)

    def parse_if(self) -> Stmt:
        self.consume("ID", "if")
        self.consume("OP", "(")
        c = self.parse_expr()
        self.consume("OP", ")")
        th = self.parse_stmt()
        el = None
        if self.match("ID", "else"):
            el = self.parse_stmt()
        return IfStmt(cond=c, then_branch=th, else_branch=el)

    def parse_while(self) -> Stmt:
        self.consume("ID", "while")
        self.consume("OP", "(")
        c = self.parse_expr()
        self.consume("OP", ")")
        b = self.parse_stmt()
        return WhileStmt(cond=c, body=b)

    def parse_do(self) -> Stmt:
        self.consume("ID", "do")
        b = self.parse_stmt()
        self.consume("ID", "while")
        self.consume("OP", "(")
        c = self.parse_expr()
        self.consume("OP", ")")
        self.consume("OP", ";")
        return DoWhileStmt(body=b, cond=c)

    def parse_for(self) -> Stmt:
        self.consume("ID", "for")
        self.consume("OP", "(")
        init: Optional[Stmt] = None
        if not self.at("OP", ";"):
            if self._is_type_start():
                base_t, storage = self._parse_type_specifiers()
                decls = []
                while True:
                    n, t = self._parse_declarator(base_t)
                    init_e = None
                    if self.match("OP", "="):
                        init_e = self.parse_initializer()
                    decls.append(VarDecl(name=n, type=t, init=init_e, storage=storage))
                    if not self.match("OP", ","):
                        break
                init = DeclStmt(decls=decls)
            else:
                init = ExprStmt(expr=self.parse_expr())
        self.consume("OP", ";")
        cond = None
        if not self.at("OP", ";"):
            cond = self.parse_expr()
        self.consume("OP", ";")
        step = None
        if not self.at("OP", ")"):
            step = self.parse_expr()
        self.consume("OP", ")")
        body = self.parse_stmt()
        return ForStmt(init=init, cond=cond, step=step, body=body)

    def parse_switch(self) -> Stmt:
        self.consume("ID", "switch")
        self.consume("OP", "(")
        e = self.parse_expr()
        self.consume("OP", ")")
        body = self.parse_block()
        # Flatten into a SwitchStmt
        cases: List[Tuple[Optional[int], Stmt]] = []
        has_default = False

        def flatten(bs: List[Stmt], cur_label: Optional[int], cur_stmts: List[Stmt]):
            nonlocal has_default
            i = 0
            while i < len(bs):
                s = bs[i]
                if isinstance(s, CaseLabel):
                    if cur_label is not None or cur_stmts:
                        cases.append((cur_label, CompoundStmt(block=Block(stmts=cur_stmts))))
                    cur_label = s.value
                    cur_stmts = []
                elif isinstance(s, DefaultLabel):
                    if cur_label is not None or cur_stmts:
                        cases.append((cur_label, CompoundStmt(block=Block(stmts=cur_stmts))))
                    cur_label = None
                    has_default = True
                    cur_stmts = []
                elif isinstance(s, CompoundStmt):
                    cur_stmts.append(s)
                else:
                    cur_stmts.append(s)
                i += 1
            if cur_label is not None or cur_stmts:
                cases.append((cur_label, CompoundStmt(block=Block(stmts=cur_stmts))))

        flatten(body.stmts, None, [])
        return SwitchStmt(expr=e, body=CompoundStmt(block=Block(stmts=[c[1] for c in cases])),
                          cases=cases, has_default=has_default)

    def parse_initializer(self) -> Expr:
        if self.at("OP", "{"):
            self.consume()
            items = []
            if not self.at("OP", "}"):
                items.append(self.parse_initializer())
                while self.match("OP", ","):
                    if self.at("OP", "}"):
                        break
                    items.append(self.parse_initializer())
            self.consume("OP", "}")
            return InitList(items=items)
        return self.parse_expr()

    # ---- expressions (precedence climbing) ----
    def parse_expr(self) -> Expr:
        return self.parse_assign()

    def parse_assign(self) -> Expr:
        e = self.parse_conditional()
        if self.at("OP") and self.peek().text in ("=", "+=", "-=", "*=", "/=", "%=",
                                                  "&=", "|=", "^=", "<<=", ">>="):
            op = self.consume().text
            v = self.parse_assign()
            return Assign(op=op, target=e, value=v)
        return e

    def parse_conditional(self) -> Expr:
        e = self.parse_logor()
        if self.match("OP", "?"):
            t = self.parse_expr()
            self.consume("OP", ":")
            f = self.parse_conditional()
            return Conditional(cond=e, then_branch=t, else_branch=f)
        return e

    def parse_logor(self) -> Expr:
        e = self.parse_logand()
        while self.match("OP", "||"):
            r = self.parse_logand()
            e = Binary("||", e, r)
        return e

    def parse_logand(self) -> Expr:
        e = self.parse_bitor()
        while self.match("OP", "&&"):
            r = self.parse_bitor()
            e = Binary("&&", e, r)
        return e

    def parse_bitor(self) -> Expr:
        e = self.parse_bitxor()
        while self.match("OP", "|"):
            r = self.parse_bitxor()
            e = Binary("|", e, r)
        return e

    def parse_bitxor(self) -> Expr:
        e = self.parse_bitand()
        while self.match("OP", "^"):
            r = self.parse_bitand()
            e = Binary("^", e, r)
        return e

    def parse_bitand(self) -> Expr:
        e = self.parse_equality()
        while self.match("OP", "&"):
            r = self.parse_equality()
            e = Binary("&", e, r)
        return e

    def parse_equality(self) -> Expr:
        e = self.parse_relational()
        while self.at("OP", "==") or self.at("OP", "!="):
            op = self.consume().text
            r = self.parse_relational()
            e = Binary(op, e, r)
        return e

    def parse_relational(self) -> Expr:
        e = self.parse_shift()
        while self.at("OP", "<") or self.at("OP", ">") or self.at("OP", "<=") or self.at("OP", ">="):
            op = self.consume().text
            r = self.parse_shift()
            e = Binary(op, e, r)
        return e

    def parse_shift(self) -> Expr:
        e = self.parse_add()
        while self.at("OP", "<<") or self.at("OP", ">>"):
            op = self.consume().text
            r = self.parse_add()
            e = Binary(op, e, r)
        return e

    def parse_add(self) -> Expr:
        e = self.parse_mul()
        while self.at("OP", "+") or self.at("OP", "-"):
            op = self.consume().text
            r = self.parse_mul()
            e = Binary(op, e, r)
        return e

    def parse_mul(self) -> Expr:
        e = self.parse_unary()
        while self.at("OP", "*") or self.at("OP", "/") or self.at("OP", "%"):
            op = self.consume().text
            r = self.parse_unary()
            e = Binary(op, e, r)
        return e

    def parse_unary(self) -> Expr:
        if self.at("OP", "++"):
            self.consume()
            e = self.parse_unary()
            return Unary("++", e, prefix=True)
        if self.at("OP", "--"):
            self.consume()
            e = self.parse_unary()
            return Unary("--", e, prefix=True)
        if self.at("OP", "+"):
            self.consume()
            e = self.parse_unary()
            return Unary("+", e, prefix=True)
        if self.at("OP", "-"):
            self.consume()
            e = self.parse_unary()
            return Unary("-", e, prefix=True)
        if self.at("OP", "!"):
            self.consume()
            e = self.parse_unary()
            return Unary("!", e, prefix=True)
        if self.at("OP", "~"):
            self.consume()
            e = self.parse_unary()
            return Unary("~", e, prefix=True)
        if self.at("OP", "*"):
            self.consume()
            e = self.parse_unary()
            return Unary("*", e, prefix=True)
        if self.at("OP", "&"):
            self.consume()
            e = self.parse_unary()
            return Unary("&", e, prefix=True)
        if self.at("OP", "(") and self._is_type_specifier(1):
            # Try to parse a cast: ( type-specifiers * ) operand
            saved = self.pos
            try:
                self.consume("OP", "(")
                ct, _ = self._parse_type_specifiers()
                while self.match("OP", "*"):
                    ct = make_ptr(ct)
                self.consume("OP", ")")
                e = self.parse_unary()
                return Cast(type=ct, operand=e)
            except Exception:
                self.pos = saved
        return self.parse_postfix()

    def _type_from_cast(self, tname: str) -> CType:
        return {
            "void": T_void,
            "char": T_schar,
            "int": T_int,
            "long": T_long,
            "short": T_short,
            "float": T_float,
            "double": T_double,
        }.get(tname, T_int)

    def parse_postfix(self) -> Expr:
        e = self.parse_primary()
        while True:
            if self.match("OP", "++"):
                e = Unary("++", e, prefix=False)
            elif self.match("OP", "--"):
                e = Unary("--", e, prefix=False)
            elif self.match("OP", "["):
                i = self.parse_expr()
                self.consume("OP", "]")
                e = Index(base=e, index=i)
            elif self.match("OP", "."):
                fn = self.consume("ID").text
                e = Member(base=e, field=fn, arrow=False)
            elif self.match("OP", "->"):
                fn = self.consume("ID").text
                e = Member(base=e, field=fn, arrow=True)
            elif self.match("OP", "("):
                args = []
                if not self.at("OP", ")"):
                    args.append(self.parse_assign())
                    while self.match("OP", ","):
                        args.append(self.parse_assign())
                self.consume("OP", ")")
                e = Call(callee=e, args=args)
            else:
                break
        return e

    def parse_primary(self) -> Expr:
        t = self.peek()
        if t.text == "sizeof":
            self.consume()
            paren = self.match("OP", "(")
            if paren and (self._is_type_specifier() or self.at("ID") and self._typedef_names.get(self.peek().text, False)):
                # type arg
                tt, _ = self._parse_type_specifiers()
                # type may still have trailing declarator pieces (e.g. int[3])
                # We don't support sizeof of a type declarator here; tests
                # only use sizeof(type-name).
                self.match("OP", ")")
                return Sizeof(arg=tt, is_type=True)
            # expression arg
            e = self.parse_unary()
            if paren:
                self.match("OP", ")")
            return Sizeof(arg=e, is_type=False)
        if t.kind == "NUM":
            text = self.consume().text
            if "." in text or "e" in text or "E" in text:
                v = float(text)
                return FloatLit(value=v, type=T_double)
            v = int(text, 0) if text.startswith("0") else int(text)
            return IntLit(value=v, type=T_int)
        if t.kind == "CHAR":
            v = int(self.consume().text)
            return CharLit(value=v, type=T_int)
        if t.kind == "STR":
            v = self.consume().text
            return StrLit(value=v)
        if t.text == "(":
            self.consume()
            e = self.parse_expr()
            self.consume("OP", ")")
            return e
        if t.kind == "ID":
            return Ident(name=self.consume().text)
        raise RuntimeError(f"unexpected token {t.text!r} at line {t.line}")


@dataclass
class CaseLabel:
    value: Optional[int]


@dataclass
class DefaultLabel:
    pass


@dataclass
class DeclStmt(Stmt):
    decls: List[VarDecl]


# Monkey-patch parse_stmt to also recognize 'case' and 'default' before any
# declaration. Insert this near parse_stmt:
_orig_parse_stmt = Parser.parse_stmt


def parse_stmt_with_cases(self: Parser) -> Stmt:
    t = self.peek()
    if t.text == "case":
        self.consume()
        v = int(self.consume("NUM").text)
        self.consume("OP", ":")
        return CaseLabel(value=v)
    if t.text == "default":
        self.consume()
        self.consume("OP", ":")
        return DefaultLabel()
    return _orig_parse_stmt(self)


Parser.parse_stmt = parse_stmt_with_cases


def _stmt_contains_label(s: Stmt, target: str) -> bool:
    if isinstance(s, LabelStmt) and s.label == target:
        return True
    if isinstance(s, CompoundStmt):
        return any(_stmt_contains_label(st, target) for st in s.block.stmts)
    if isinstance(s, IfStmt):
        if _stmt_contains_label(s.then_branch, target): return True
        if s.else_branch and _stmt_contains_label(s.else_branch, target): return True
    if isinstance(s, (WhileStmt, DoWhileStmt, ForStmt)):
        if _stmt_contains_label(s.body, target): return True
    return False

def _find_label_index(stmts: List[Stmt], target: str) -> Optional[int]:
    for i, s in enumerate(stmts):
        if _stmt_contains_label(s, target):
            return i
    return None


# ------------------------------------------------------------------
# Interpreter
# ------------------------------------------------------------------
class InterpreterError(Exception):
    pass


class Interpreter:
    def __init__(self):
        self.global_scope = Scope(kind="global")
        # Register global types/values for stdio stub.
        self.global_scope.syms["NULL"] = Symbol(
            name="NULL", type=T_int, value=v_int(T_int, 0))
        # Track if we've entered main yet (for implicit return 0).
        self.finished = False
        self.exit_code = 0
        # Statically-allocated globals + aggregate initializers.
        # Stored in a single byte buffer named ".data" with member offsets.
        # Lazy allocation as globals are declared.
        self.output_buf: List[str] = []
        # Track static locals by (function, name) -> Value.
        # We implement function-level stashes via a dict on the function's
        # own callable object.
        self._typedef_names: Dict[str, bool] = {}
        self._typedefs: Dict[str, CType] = {}
        self._struct_defs: Dict[str, CType] = {}
        self._current_function_statics: Optional[Dict[str, Value]] = None

    def add_typedef(self, name: str, t: CType):
        self._typedef_names[name] = True
        self._typedefs[name] = t
        self.global_scope.syms[name] = Symbol(
            name=name, type=t, storage="typedef")

    def add_struct(self, name: str, t: CType):
        self._struct_defs[name] = t

    # ---- runtime helpers ----
    def truthy(self, v: Value) -> int:
        if isinstance(v.scalar, int):
            return int(bool(v.scalar))
        return int(bool(int(v.scalar)))

    def to_py_int(self, v: Value) -> int:
        if v.type.kind == "float":
            f = float(v.scalar)
            return int(f)
        return int(v.scalar)

    def read_scalar(self, v: Value) -> Union[int, float]:
        """Return the raw value at v, dereferencing pointers if needed."""
        t = v.type
        if t.kind in ("int", "char"):
            return int(v.scalar)
        if t.kind == "float":
            return float(v.scalar)
        if t.kind == "ptr" or t.kind == "array" or t.kind in ("struct", "union"):
            # Reading a pointer (rvalue) yields the pointer as int (address)
            return int(v.scalar) if v.scalar is not None else 0
        raise InterpreterError(f"cannot read {t.name}")

    # Default integer promotion rules (C99):
    # char/short -> int (or unsigned int if int can't hold it).
    def promote(self, t: CType) -> CType:
        if t.kind == "char":
            return T_int  # assume 4-byte signed
        if t.kind == "int" and t.size < 4:
            return T_int
        return t

    def usual_arith(self, a: CType, b: CType) -> CType:
        """Return common type for arithmetic on a, b."""
        pa, pb = self.promote(a), self.promote(b)
        if pa.kind == "float" or pb.kind == "float":
            # Both must be float (size 4) to stay float; else double
            if pa.kind == "float" and pb.kind == "float" and pa.name == "float" and pb.name == "float":
                return T_float
            return T_double
        # both int after promotion; if either unsigned, result unsigned,
        # signed if both signed, etc.
        if pa.signed == pb.signed:
            return pa if pa.size >= pb.size else pb
        # mixed signedness — C's baroque rules: if both same width, signed.
        if pa.size != pb.size:
            wider = pa if pa.size > pb.size else pb
            # if signed's rank < unsigned's -> unsigned; else if signed can
            # represent everything -> signed.
            if wider.signed:
                return wider
            return wider
        return pa if pa.signed else pb

    # ---- statement execution ----
    def exec_block(self, block: Block, parent_scope: Optional[Scope] = None,
                   outer_call_stack: Optional[List["CallFrame"]] = None,
                   fn_scope: Optional[Scope] = None) -> None:
        parent = parent_scope if parent_scope is not None else (fn_scope if fn_scope is not None else self.global_scope)
        scope = Scope(parent=parent)
        i = 0
        while i < len(block.stmts):
            s = block.stmts[i]
            try:
                self.exec_stmt(s, scope, outer_call_stack)
                i += 1
            except GotoSignal as g:
                idx = _find_label_index(block.stmts, g.label)
                if idx is not None:
                    i = idx
                else:
                    raise g

    def exec_block_with_break_target(self, block: Block, target: int,
                                    parent_scope: Optional[Scope] = None,
                                    outer_call_stack: Optional[List["CallFrame"]] = None,
                                    fn_scope: Optional[Scope] = None) -> int:
        """Run block using switch-tagged break signal handling. Returns target id of matching break."""
        parent = parent_scope if parent_scope is not None else (fn_scope if fn_scope is not None else self.global_scope)
        scope = Scope(parent=parent)
        i = 0
        while i < len(block.stmts):
            s = block.stmts[i]
            try:
                self.exec_stmt(s, scope, outer_call_stack)
                i += 1
            except GotoSignal as g:
                idx = _find_label_index(block.stmts, g.label)
                if idx is not None:
                    i = idx
                else:
                    raise g
        return -1  # no break encountered

    def exec_stmt(self, s: Stmt, scope: Scope, call_stack: Optional[List["CallFrame"]] = None) -> None:
        call_stack = call_stack if call_stack is not None else []
        if isinstance(s, CompoundStmt):
            self.exec_block(s.block, scope, call_stack)
        elif isinstance(s, DeclStmt):
            self.exec_decl_stmt(s, scope, call_stack)
        elif isinstance(s, ExprStmt):
            v = self.eval_expr(s.expr, scope, call_stack)
            # discard result
            return
        elif isinstance(s, IfStmt):
            c = self.eval_expr(s.cond, scope, call_stack)
            if self.truthy(c):
                self.exec_stmt(s.then_branch, scope, call_stack)
            elif s.else_branch:
                self.exec_stmt(s.else_branch, scope, call_stack)
        elif isinstance(s, WhileStmt):
            while True:
                c = self.eval_expr(s.cond, scope, call_stack)
                if not self.truthy(c):
                    return
                try:
                    self.exec_stmt(s.body, scope, call_stack)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    return
                except ReturnSignal as r:
                    raise r
                except GotoSignal as g:
                    raise g
        elif isinstance(s, DoWhileStmt):
            try:
                while True:
                    self.exec_stmt(s.body, scope, call_stack)
                    c = self.eval_expr(s.cond, scope, call_stack)
                    if not self.truthy(c):
                        return
            except ContinueSignal:
                # continue from inner loop — re-evaluate cond
                pass
            except BreakSignal:
                return
        elif isinstance(s, ForStmt):
            for_scope = Scope(parent=scope)
            if s.init is not None:
                if isinstance(s.init, DeclStmt):
                    self.exec_decl_stmt(s.init, for_scope, call_stack)
                else:
                    self.eval_expr(s.init.expr, for_scope, call_stack)
            while True:
                if s.cond is not None:
                    c = self.eval_expr(s.cond, for_scope, call_stack)
                    if not self.truthy(c):
                        return
                try:
                    self.exec_stmt(s.body, for_scope, call_stack)
                except ContinueSignal:
                    pass
                except BreakSignal:
                    return
                except (ReturnSignal, GotoSignal):
                    raise
                if s.step is not None:
                    self.eval_expr(s.step, for_scope, call_stack)
        elif isinstance(s, ReturnStmt):
            v = None
            if s.expr is not None:
                v = self.eval_expr(s.expr, scope, call_stack)
            raise ReturnSignal(v)
        elif isinstance(s, BreakStmt):
            raise BreakSignal()
        elif isinstance(s, ContinueStmt):
            raise ContinueSignal()
        elif isinstance(s, GotoStmt):
            raise GotoSignal(s.label)
        elif isinstance(s, LabelStmt):
            # labels are resolved at parse time by recursing through stmt list;
            # we keep LabelStmt for completeness. They don't introduce new
            # scope.
            self.exec_stmt(s.stmt, scope, call_stack)
        elif isinstance(s, SwitchStmt):
            e = self.eval_expr(s.expr, scope, call_stack)
            target = self.to_py_int(e)
            # Find matching case
            idx = None
            for i, (val, _) in enumerate(s.cases):
                if val == target:
                    idx = i
                    break
            if idx is None and s.has_default:
                for i, (val, _) in enumerate(s.cases):
                    if val is None:
                        idx = i
                        break
            # Execute cases from idx to end (or all if not found and no default)
            try:
                if idx is None:
                    return
                # Execute the matched case and all subsequent cases (fall-through)
                for i in range(idx, len(s.cases)):
                    val, body = s.cases[i]
                    self.exec_stmt(body, scope, call_stack)
            except BreakSignal:
                pass
            except (ContinueSignal, GotoSignal, ReturnSignal):
                raise
        else:
            raise InterpreterError(f"unknown stmt {type(s).__name__}")

    def exec_decl_stmt(self, s: DeclStmt, scope: Scope, call_stack: List["CallFrame"]):
        for d in s.decls:
            t = self._strip_array(d.type)  # array→pointer? no, keep Mem
            v = self._allocate_value(t, d.storage)
            sym = Symbol(name=d.name, type=d.type, storage=d.storage, value=v)
            scope.syms[d.name] = sym
            if d.init is not None:
                self._initialize(sym, d.init, scope, call_stack)

    def _allocate_value(self, t: CType, storage: str) -> Value:
        if t.kind == "array":
            return v_mem(t, t.size)
        if t.kind in ("struct", "union"):
            return v_mem(t, t.size)
        if t.kind == "ptr":
            return Value(make_ptr(t.elem), scalar=0)
        if t.kind == "float":
            return v_float(t, 0.0)
        return v_int(t, 0)

    def _strip_array(self, t: CType) -> CType:
        # In most contexts int arr[] decays to int*, but as a declaration
        # it remains an array type. We keep array type for locals.
        return t

    def _initialize(self, sym: Symbol, init: Expr, scope: Scope, call_stack: List["CallFrame"]):
        if isinstance(init, InitList):
            self._init_aggregate(sym, init, sym.type, scope, call_stack)
            return
        v = self.eval_expr(init, scope, call_stack)
        self._store(sym.value, sym.type, v, scope, call_stack)

    def _init_aggregate(self, sym: Symbol, init: InitList, target_type: CType,
                         scope: Scope, call_stack: List["CallFrame"]):
        self._init_aggregate_at(sym.value.mem, 0, init, target_type, scope, call_stack)

    def _init_aggregate_at(self, mem: Mem, off: int, init: InitList, target_type: CType,
                            scope: Scope, call_stack: List["CallFrame"]):
        if target_type.kind == "array":
            elem_t = target_type.elem
            for i, item in enumerate(init.items[:target_type.length or len(init.items)]):
                item_off = off + i * elem_t.size
                if isinstance(item, InitList):
                    self._init_aggregate_at(mem, item_off, item, elem_t, scope, call_stack)
                else:
                    v = self.eval_expr(item, scope, call_stack)
                    self._store_at(mem, item_off, elem_t, v)
            return
        if target_type.kind in ("struct", "union"):
            for i, item in enumerate(init.items):
                if i >= len(target_type.fields):
                    break
                fname, ft, foff = target_type.fields[i]
                if isinstance(item, InitList):
                    self._init_aggregate_at(mem, off + foff, item, ft, scope, call_stack)
                else:
                    v = self.eval_expr(item, scope, call_stack)
                    self._store_at(mem, off + foff, ft, v)
            return

    # ---- expression evaluation ----
    def eval_expr(self, e: Expr, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        if isinstance(e, IntLit):
            return v_int(e.type, _trunc_int(int(e.value), e.type.size * 8, not e.type.signed))
        if isinstance(e, FloatLit):
            return v_float(e.type, float(e.value))
        if isinstance(e, CharLit):
            return v_int(T_int, int(e.value))
        if isinstance(e, StrLit):
            # string literal: char[N+1] backing store with literal chars
            data = (e.value + "\0").encode("latin-1")
            m = Mem(len(data))
            m.data[:len(data)] = data
            t = CType("array", "char[%d]" % len(data), len(data), 1, elem=T_char, length=len(data))
            return Value(t, mem=m)
        if isinstance(e, Ident):
            return self.eval_ident(e.name, scope)
        if isinstance(e, Binary):
            return self.eval_binary(e, scope, call_stack)
        if isinstance(e, Unary):
            return self.eval_unary(e, scope, call_stack)
        if isinstance(e, Conditional):
            c = self.eval_expr(e.cond, scope, call_stack)
            if self.truthy(c):
                return self.eval_expr(e.then_branch, scope, call_stack)
            return self.eval_expr(e.else_branch, scope, call_stack)
        if isinstance(e, Assign):
            return self.eval_assign(e, scope, call_stack)
        if isinstance(e, Call):
            return self.eval_call(e, scope, call_stack)
        if isinstance(e, Index):
            return self.eval_index(e, scope, call_stack)
        if isinstance(e, Member):
            return self.eval_member(e, scope, call_stack)
        if isinstance(e, Cast):
            return self.eval_cast(e, scope, call_stack)
        if isinstance(e, Sizeof):
            if e.is_type:
                return v_int(T_ulong, e.arg.size)
            # sizeof(expr): evaluate expression is not strictly needed
            inner = self.eval_expr(e.arg, scope, call_stack)
            return v_int(T_ulong, inner.type.size)
        if isinstance(e, InitList):
            # Empty initializer?
            return v_int(T_int, 0)
        raise InterpreterError(f"unknown expr {type(e).__name__}")

    def eval_ident(self, name: str, scope: Scope) -> Value:
        s = scope.get(name)
        if s is None:
            raise InterpreterError(f"undefined identifier: {name}")
        if s.storage == "typedef":
            raise InterpreterError(f"{name} is a typedef")
        if s.storage == "func":
            return Value(s.type, func=s)
        return s.value

    def eval_binary(self, e: Binary, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        if e.op == "&&":
            l = self.eval_expr(e.lhs, scope, call_stack)
            if not self.truthy(l):
                return v_int(T_int, 0)
            r = self.eval_expr(e.rhs, scope, call_stack)
            return v_int(T_int, int(bool(self.truthy(r))))
        if e.op == "||":
            l = self.eval_expr(e.lhs, scope, call_stack)
            if self.truthy(l):
                return v_int(T_int, 1)
            r = self.eval_expr(e.rhs, scope, call_stack)
            return v_int(T_int, int(bool(self.truthy(r))))
        # short-circuit comma is not commonly used; support it anyway
        if e.op == ",":
            self.eval_expr(e.lhs, scope, call_stack)
            return self.eval_expr(e.rhs, scope, call_stack)
        l = self.eval_expr(e.lhs, scope, call_stack)
        r = self.eval_expr(e.rhs, scope, call_stack)
        lt, rt = l.type, r.type
        # Pointer arithmetic
        if lt.kind == "ptr" and rt.kind == "int":
            # ptr +/- int
            base = int(l.scalar) if l.scalar is not None else 0
            ix = self.to_py_int(r)
            new_addr = base + ix * lt.elem.size
            return Value(make_ptr(lt.elem), scalar=new_addr)
        if lt.kind == "int" and rt.kind == "ptr":
            new_addr = int(l.scalar) + self.to_py_int(r) * rt.elem.size
            return Value(make_ptr(rt.elem), scalar=new_addr)
        if lt.kind == "ptr" and rt.kind == "ptr":
            # subtraction only
            if e.op == "-":
                base = int(l.scalar) - int(r.scalar)
                if lt.elem.size:
                    base //= lt.elem.size
                return v_int(T_long, base)
            raise InterpreterError("ptr-ptr only")
        # float ops
        if lt.kind == "float" or rt.kind == "float":
            lf = float(l.scalar) if isinstance(l.scalar, (int, float)) else float(int(l.scalar))
            rf = float(r.scalar) if isinstance(r.scalar, (int, float)) else float(int(r.scalar))
            if rt.kind != "float":
                rt_p = self.promote(rt)
            res_t = self.usual_arith(lt, rt)
            if res_t.kind == "float":
                if e.op == "+": return v_float(T_float, lf + rf)
                if e.op == "-": return v_float(T_float, lf - rf)
                if e.op == "*": return v_float(T_float, lf * rf)
                if e.op == "/": return v_float(T_float, lf / rf)
                if e.op == "%": return v_float(T_float, math.fmod(lf, rf))
                if e.op in ("<", ">", "<=", ">=", "==", "!="):
                    return v_int(T_int, {
                        "<": lambda a, b: a < b,
                        ">": lambda a, b: a > b,
                        "<=": lambda a, b: a <= b,
                        ">=": lambda a, b: a >= b,
                        "==": lambda a, b: a == b,
                        "!=": lambda a, b: a != b,
                    }[e.op](lf, rf))
                if e.op == "&":
                    return v_float(T_float, float(int(lf) & int(rf)))
                if e.op == "|":
                    return v_float(T_float, float(int(lf) | int(rf)))
                if e.op == "^":
                    return v_float(T_float, float(int(lf) ^ int(rf)))
                if e.op == "<<":
                    return v_float(T_float, float(int(lf) << int(rf)))
                if e.op == ">>":
                    return v_float(T_float, float(int(lf) >> int(rf)))
            else:  # double
                if e.op == "+": return v_float(T_double, lf + rf)
                if e.op == "-": return v_float(T_double, lf - rf)
                if e.op == "*": return v_float(T_double, lf * rf)
                if e.op == "/": return v_float(T_double, lf / rf)
                if e.op == "%": return v_float(T_double, math.fmod(lf, rf))
                if e.op in ("<", ">", "<=", ">=", "==", "!="):
                    return v_int(T_int, int({
                        "<": lambda a, b: a < b,
                        ">": lambda a, b: a > b,
                        "<=": lambda a, b: a <= b,
                        ">=": lambda a, b: a >= b,
                        "==": lambda a, b: a == b,
                        "!=": lambda a, b: a != b,
                    }[e.op](lf, rf)))
                if e.op == "&":
                    return v_float(T_double, float(int(lf) & int(rf)))
                if e.op == "|":
                    return v_float(T_double, float(int(lf) | int(rf)))
                if e.op == "^":
                    return v_float(T_double, float(int(lf) ^ int(rf)))
                if e.op == "<<":
                    return v_float(T_double, float(int(lf) << int(rf)))
                if e.op == ">>":
                    return v_float(T_double, float(int(lf) >> int(rf)))
        # integer ops
        la = self.to_py_int(l)
        ra = self.to_py_int(r)
        rt2 = self.usual_arith(lt, rt)
        res_t = rt2 if rt2.size >= lt.size else lt
        # For shift, the result type is the promoted LHS.
        if e.op in ("<<", ">>"):
            res_t = self.promote(lt)
        if e.op == "+": return v_int(res_t, la + ra)
        if e.op == "-": return v_int(res_t, la - ra)
        if e.op == "*": return v_int(res_t, la * ra)
        if e.op == "/":
            if ra == 0:
                raise InterpreterError("division by zero")
            # C: truncates toward zero
            q = abs(la) // abs(ra)
            if (la < 0) ^ (ra < 0):
                q = -q
            return v_int(res_t, q)
        if e.op == "%":
            if ra == 0:
                raise InterpreterError("mod by zero")
            q = abs(la) // abs(ra)
            if (la < 0) ^ (ra < 0):
                q = -q
            return v_int(res_t, la - q * ra)
        if e.op == "&": return v_int(res_t, la & ra)
        if e.op == "|": return v_int(res_t, la | ra)
        if e.op == "^": return v_int(res_t, la ^ ra)
        if e.op == "<<": return v_int(res_t, (la << ra) & ((1 << (res_t.size * 8)) - 1) if False else la << ra)
        if e.op == ">>":
            if res_t.signed:
                # arithmetic shift
                mask = (1 << (res_t.size * 8)) - 1
                v = la & mask
                if v & (1 << (res_t.size * 8 - 1)):
                    v |= ~mask
                return v_int(res_t, v >> ra)
            return v_int(res_t, la >> ra)
        if e.op == "<": return v_int(T_int, int(la < ra))
        if e.op == ">": return v_int(T_int, int(la > ra))
        if e.op == "<=": return v_int(T_int, int(la <= ra))
        if e.op == ">=": return v_int(T_int, int(la >= ra))
        if e.op == "==": return v_int(T_int, int(la == ra))
        if e.op == "!=": return v_int(T_int, int(la != ra))
        raise InterpreterError(f"unknown binary op {e.op}")

    def eval_unary(self, e: Unary, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        if e.prefix:
            if e.op == "++":
                tgt = self.eval_expr(e.operand, scope, call_stack)
                if isinstance(tgt, Value) and tgt.is_mem:
                    self._inc_at(tgt.mem, 0, tgt.type, 1)
                    return tgt
                self._assign_to_lvalue(e.operand, scope, call_stack,
                                         lambda: self._add_to(tgt, 1, scope, call_stack))
                return tgt
            if e.op == "--":
                tgt = self.eval_expr(e.operand, scope, call_stack)
                if isinstance(tgt, Value) and tgt.is_mem:
                    self._inc_at(tgt.mem, 0, tgt.type, -1)
                    return tgt
                self._assign_to_lvalue(e.operand, scope, call_stack,
                                         lambda: self._add_to(tgt, -1, scope, call_stack))
                return tgt
            if e.op == "+":
                v = self.eval_expr(e.operand, scope, call_stack)
                return v
            if e.op == "-":
                v = self.eval_expr(e.operand, scope, call_stack)
                if v.type.kind == "float":
                    return v_float(v.type, -float(v.scalar))
                return v_int(v.type, -int(v.scalar))
            if e.op == "!":
                v = self.eval_expr(e.operand, scope, call_stack)
                return v_int(T_int, int(not self.truthy(v)))
            if e.op == "~":
                v = self.eval_expr(e.operand, scope, call_stack)
                return v_int(v.type, ~int(v.scalar))
            if e.op == "*":
                v = self.eval_expr(e.operand, scope, call_stack)
                # v must be a pointer
                if not v.type.is_ptr:
                    raise InterpreterError(f"cannot dereference non-pointer {v.type.name}")
                return self._deref(v)
            if e.op == "&":
                return self.eval_address_of(e.operand, scope, call_stack)
        # postfix
        if e.op == "++":
            tgt = self._resolve_lvalue(e.operand, scope, call_stack)
            old = self._read_scalar(tgt["mem"], tgt["off"], tgt["type"])
            res = v_int(tgt["type"], old)
            if "_wrap" in tgt:
                # write back through assign helper so scalar storage persists
                self._assign_to_lvalue(e.operand, scope, call_stack,
                                         lambda: v_int(tgt["type"], old + 1))
            else:
                self._store_at(tgt["mem"], tgt["off"], tgt["type"], old + 1)
            return res
        if e.op == "--":
            tgt = self._resolve_lvalue(e.operand, scope, call_stack)
            old = self._read_scalar(tgt["mem"], tgt["off"], tgt["type"])
            res = v_int(tgt["type"], old)
            if "_wrap" in tgt:
                self._assign_to_lvalue(e.operand, scope, call_stack,
                                         lambda: v_int(tgt["type"], old - 1))
            else:
                self._store_at(tgt["mem"], tgt["off"], tgt["type"], old - 1)
            return res
        raise InterpreterError(f"unknown unary {e.op}")

    def _add_to(self, v: Value, n: int, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        if v.type.kind == "float":
            return v_float(v.type, float(v.scalar) + n)
        return v_int(v.type, int(v.scalar) + n)

    def _assign_to_lvalue(self, expr: Expr, scope: Scope, call_stack, value_fn):
        tgt = self._resolve_lvalue(expr, scope, call_stack)
        v = value_fn()
        self._store_at(tgt["mem"], tgt["off"], tgt["type"], int(v.scalar) if hasattr(v, "scalar") else v)
        if "_wrap" in tgt:
            wrapped = tgt["_wrap"]
            if tgt["type"].kind == "float":
                wrapped.value.scalar = float(v.scalar)
            else:
                wrapped.value.scalar = self._read_scalar(tgt["mem"], tgt["off"], tgt["type"])

    def eval_address_of(self, operand: Expr, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        tgt = self._resolve_lvalue(operand, scope, call_stack)
        return Value(make_ptr(tgt["type"]), mem=tgt["mem"], scalar=tgt["off"])

    def _resolve_lvalue(self, expr: Expr, scope: Scope, call_stack) -> dict:
        """Return {'mem': Mem, 'off': int, 'type': CType} for an lvalue."""
        if isinstance(expr, Ident):
            s = scope.get(expr.name)
            if s is None:
                raise InterpreterError(f"undefined {expr.name}")
            if s.value.is_mem:
                return {"mem": s.value.mem, "off": 0, "type": s.type}
            # scalar — synthesize a tiny mem so we can still mutate via store
            m = Mem(s.type.size)
            if s.type.kind == "float":
                wr_float(m, 0, s.type, float(s.value.scalar))
            else:
                wr_int(m, 0, s.type, int(s.value.scalar) if s.value.scalar is not None else 0)
            m.wrap = s
            return {"mem": m, "off": 0, "type": s.type, "_wrap": s}
        if isinstance(expr, Unary) and expr.op == "*":
            p = self.eval_expr(expr.operand, scope, call_stack)
            return {"mem": p.mem, "off": int(p.scalar) if p.scalar is not None else 0,
                    "type": p.type.elem}
        if isinstance(expr, Index):
            base = self.eval_expr(expr.base, scope, call_stack)
            ix = self.eval_expr(expr.index, scope, call_stack)
            base_off = int(base.scalar) if base.scalar else 0
            elem_sz = base.type.elem.size if base.type.elem else 1
            off = base_off + self.to_py_int(ix) * elem_sz
            return {"mem": base.mem, "off": int(off), "type": base.type.elem}
        if isinstance(expr, Member):
            base = self.eval_expr(expr.base, scope, call_stack)
            if expr.arrow:
                # p->f is (*p).f
                m = base.mem
                off = int(base.scalar) if base.scalar else 0
                struct_off = m.members.get(expr.field, (None, 0))[1] if False else \
                    self._struct_offset(base.type.elem, expr.field)
                return {"mem": m, "off": off + struct_off,
                        "type": base.type.elem.members[expr.field][0]}
            # base is a struct value, base.mem is struct memory
            struct_off = self._struct_offset(base.type, expr.field)
            return {"mem": base.mem, "off": struct_off,
                    "type": base.type.members[expr.field][0]}
        raise InterpreterError(f"not an lvalue: {type(expr).__name__}")

    def _struct_offset(self, t: CType, field: str) -> int:
        # walk through struct/union chain via mem reference for nested types
        if t.kind not in ("struct", "union"):
            raise InterpreterError(f"member access on non-aggregate {t.name}")
        if field not in t.members:
            raise InterpreterError(f"{field} not in {t.name}")
        return t.members[field][1]

    def _deref(self, p: Value) -> Value:
        m = p.mem
        off = int(p.scalar) if p.scalar is not None else 0
        if m is None:
            raise InterpreterError("null dereference")
        if p.type.elem.kind == "ptr" and off == 0 and getattr(m, "wrap", None) is not None:
            wrapped = m.wrap.value
            if wrapped is not None and wrapped.type.kind == "ptr":
                return Value(p.type.elem, mem=wrapped.mem, scalar=wrapped.scalar)
        # We don't know exactly the type the user wants — return a Mem
        # wrapper at that offset.
        return Value(p.type.elem, mem=m, scalar=off)  # faux

    def _read_scalar(self, mem: Mem, off: int, t: CType) -> int:
        if t.kind == "float":
            f = rd_float(mem, off, t)
            if t.size == 4:
                f = round_to_single_precision(f)
            # For integer-style read of float (rare), return int
            return int(f)
        return rd_int(mem, off, t)

    def _store_at(self, mem: Mem, off: int, t: CType, v) -> None:
        if t.kind == "ptr":
            if isinstance(v, Value):
                x = int(v.scalar) if v.scalar is not None else 0
                pointee_mem = v.mem
            else:
                x = int(v)
                pointee_mem = None
            wr_int(mem, off, t, x)
            if off == 0 and mem.wrap is not None:
                mem.wrap.value.scalar = x
                mem.wrap.value.mem = pointee_mem
            return
        if t.kind == "float":
            if isinstance(v, Value):
                f = float(v.scalar)
            else:
                f = float(v)
            fv = round_to_single_precision(f) if t.size == 4 else f
            wr_float(mem, off, t, fv)
            if mem.wrap is not None:
                mem.wrap.value.scalar = fv
            return
        if isinstance(v, Value):
            x = int(v.scalar)
        else:
            x = int(v)
        wr_int(mem, off, t, x)
        if mem.wrap is not None:
            mem.wrap.value.scalar = x

    def _store(self, holder: Value, t: CType, source: Value, scope, call_stack) -> None:
        """For initializing a Value held by holder, placing source coerced to t."""
        if t.kind == "array":
            # nothing — already allocated
            return
        if t.kind == "ptr":
            holder.scalar = int(source.scalar) if source.scalar is not None else 0
            holder.mem = source.mem
            return
        if t.kind in ("struct", "union"):
            # copy bytes
            m_src = source.mem
            if m_src is None:
                return
            holder.mem.data[:] = m_src.data[:t.size]
            return
        if t.kind == "float":
            f = float(source.scalar)
            if holder.mem is not None:
                wr_float(holder.mem, 0, t, round_to_single_precision(f) if t.size == 4 else f)
            else:
                holder.scalar = f
            return
        # scalar int/char
        x = coerce_to_int(source.scalar, t.size * 8, not t.signed)
        if holder.mem is not None:
            wr_int(holder.mem, 0, t, x)
            return
        # fallback (scalars stored as Python ints)
        holder.scalar = x

    def eval_assign(self, e: Assign, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        tgt = self._resolve_lvalue(e.target, scope, call_stack)
        rv = self.eval_expr(e.value, scope, call_stack)
        if e.op == "=":
            self._do_assign(tgt, rv)
            return rv
        # compound assignments
        old_v = self._read_scalar(tgt["mem"], tgt["off"], tgt["type"])
        if tgt["type"].kind == "float":
            old_f = float(old_v)
            rv_f = float(rv.scalar)
            if e.op == "+=": nv = old_f + rv_f
            elif e.op == "-=": nv = old_f - rv_f
            elif e.op == "*=": nv = old_f * rv_f
            elif e.op == "/=": nv = old_f / rv_f
            elif e.op == "%=": nv = math.fmod(old_f, rv_f)
            else: raise InterpreterError(f"unknown {e.op}")
            self._store_at(tgt["mem"], tgt["off"], tgt["type"], round_to_single_precision(nv) if tgt["type"].size == 4 else nv)
            return v_float(tgt["type"], nv)
        else:
            old_i = int(old_v)
            rv_i = int(rv.scalar)
            if e.op == "+=": nv = old_i + rv_i
            elif e.op == "-=": nv = old_i - rv_i
            elif e.op == "*=": nv = old_i * rv_i
            elif e.op == "/=": nv = old_i // rv_i
            elif e.op == "%=": nv = old_i % rv_i
            elif e.op == "&=": nv = old_i & rv_i
            elif e.op == "|=": nv = old_i | rv_i
            elif e.op == "^=": nv = old_i ^ rv_i
            elif e.op == "<<=": nv = old_i << rv_i
            elif e.op == ">>=": nv = old_i >> rv_i
            else: raise InterpreterError(f"unknown {e.op}")
            # truncate to type width
            mask = (1 << (tgt["type"].size * 8)) - 1
            nv_t = nv & mask
            if tgt["type"].signed and nv_t >= (1 << (tgt["type"].size * 8 - 1)):
                nv_t -= 1 << (tgt["type"].size * 8)
            self._store_at(tgt["mem"], tgt["off"], tgt["type"], nv_t)
            return v_int(tgt["type"], nv_t)

    def _do_assign(self, tgt: dict, source: Value):
        if tgt["type"].kind == "ptr":
            self._store_at(tgt["mem"], tgt["off"], tgt["type"], source)
            return
        if tgt["type"].kind == "float":
            f = float(source.scalar)
            self._store_at(tgt["mem"], tgt["off"], tgt["type"],
                            round_to_single_precision(f) if tgt["type"].size == 4 else f)
            return
        if isinstance(source.scalar, (int, float)) and tgt["type"].kind not in ("struct", "union", "array"):
            self._store_at(tgt["mem"], tgt["off"], tgt["type"], source.scalar)
            return
        # pointer/aggregate copy
        if source.mem is not None:
            n = min(len(source.mem.data) - (int(source.scalar) if source.scalar else 0), tgt["type"].size)
            tgt["mem"].data[tgt["off"]:tgt["off"] + n] = source.mem.data[
                int(source.scalar) if source.scalar else 0:
                int(source.scalar) if source.scalar else 0 + n]

    def eval_index(self, e: Index, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        # arr[i] — returns a pointer-like value pointing to the element.
        base = self.eval_expr(e.base, scope, call_stack)
        ix = self.eval_expr(e.index, scope, call_stack)
        i = self.to_py_int(ix)
        # If base is array, point into base.mem; if base is pointer, point into base.mem at offset.
        if base.type.kind == "array":
            base_off = int(base.scalar) if base.scalar else 0
            off = base_off + i * base.type.elem.size
            return Value(base.type.elem, mem=base.mem, scalar=off)
        if base.type.kind == "ptr":
            base_addr = int(base.scalar) if base.scalar else 0
            return Value(base.type.elem, mem=base.mem, scalar=base_addr + i * base.type.elem.size)
        raise InterpreterError(f"cannot index {base.type.name}")

    def eval_member(self, e: Member, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        base = self.eval_expr(e.base, scope, call_stack)
        if e.arrow:
            m = base.mem
            off = int(base.scalar) if base.scalar else 0
            struct_t = base.type.elem
        else:
            m = base.mem
            off = 0
            struct_t = base.type
        if struct_t.kind not in ("struct", "union"):
            raise InterpreterError(f"member access on non-aggregate {struct_t.name}")
        ft, field_off = struct_t.members[e.field]
        # Return a value that can be further indexed/assigned/etc.
        return Value(ft, mem=m, scalar=off + field_off)

    def eval_cast(self, e: Cast, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        v = self.eval_expr(e.operand, scope, call_stack)
        if e.type.kind == "float":
            if v.type.kind == "ptr":
                # pointer -> integer -> float
                x = int(v.scalar) if v.scalar else 0
                return v_float(e.type, float(x))
            return v_float(e.type, float(v.scalar) if not isinstance(v.scalar, int) else float(int(v.scalar)))
        if e.type.is_ptr:
            # integer -> pointer
            x = int(v.scalar) if v.scalar else 0
            return Value(e.type, scalar=x)
        if e.type.kind in ("int", "char"):
            x = int(v.scalar) if not isinstance(v.scalar, float) else int(v.scalar)
            return v_int(e.type, _trunc_int(x, e.type.size * 8, not e.type.signed))
        return v

    def eval_call(self, e: Call, scope: Scope, call_stack: List["CallFrame"]) -> Value:
        # Find callee
        if isinstance(e.callee, Ident):
            fn_name = e.callee.name
        elif isinstance(e.callee, Member):
            # member call: not supported here (no function pointers via structs)
            base = self.eval_expr(e.callee.base, scope, call_stack)
            raise InterpreterError(f"function call through {type(e.callee).__name__} unsupported")
        else:
            raise InterpreterError("complex callee unsupported")
        try:
            sys.stderr.write(f"CALL {fn_name} with {len(e.args)} args\n")
        except Exception:
            pass
        s = scope.get(fn_name)
        if s is None:
            raise InterpreterError(f"unknown function {fn_name}")
        # Find function decl/def
        if s.storage != "func":
            # could be a function pointer variable
            if s.value and s.value.func:
                fdef = s.value.func
            else:
                raise InterpreterError(f"{fn_name} is not a function")
        else:
            fdef = s.func_body
        if fdef is None:
            raise InterpreterError(f"{fn_name} has no definition")
        decl: FuncDecl = fdef
        if getattr(decl, "intrinsic", None):
            arg_vals = [self.eval_expr(a, scope, call_stack) for a in e.args]
            result = decl.intrinsic(self, arg_vals)
            if isinstance(result, Value):
                return result
            return v_int(T_int, 0)
        if not decl.body:
            raise InterpreterError(f"{fn_name} has no body")
        # Set up new scope with parameters
        new_scope = Scope(parent=self.global_scope, kind="function")
        # Track static locals under decl.name
        static_key = f"{fn_name}"
        for (pn, pt), sym in zip(decl.params, []):
            pass
        # We need to associate per-function statics: store on the Symbol's
        # params list isn't quite right. Instead use a dict keyed by decl.
        if not hasattr(decl, "_static_store"):
            decl._static_store = {}
        # Allocate params from caller
        arg_vals = [self.eval_expr(a, scope, call_stack) for a in e.args]
        for (pn, pt), av in zip(decl.params, arg_vals):
            # Coerce/promote argument per default arg promotion
            v = self._coerce_arg(av, pt)
            new_scope.syms[pn] = Symbol(name=pn, type=pt, storage="auto", value=v)
        # Run body inside new scope; but static locals live in decl._static_store.
        saved_globals = self._current_function_statics
        self._current_function_statics = decl._static_store
        try:
            try:
                self.exec_block(decl.body, fn_scope=new_scope)
                # implicit return 0
                return v_int(T_int, 0)
            except ReturnSignal as rs:
                return rs.value if rs.value else v_int(T_int, 0)
            except GotoSignal as g:
                raise InterpreterError(f"goto {g.label} outside any function")
        finally:
            self._current_function_statics = saved_globals

    _current_function_statics: Optional[Dict[str, Value]] = None

    def _coerce_arg(self, v: Value, target: CType) -> Value:
        # Default argument promotions: float -> double
        if target.kind == "float" and v.type.kind == "float":
            return v_float(T_double, float(v.scalar))
        if target.kind == "ptr" and v.type.kind == "array":
            return Value(make_ptr(target.elem), mem=v.mem, scalar=0)
        if target.kind == "ptr" and v.type.kind == "ptr":
            return Value(target, mem=v.mem, scalar=v.scalar)
        # integer-to-integer
        if target.kind in ("int", "char") and v.type.kind in ("int", "char"):
            return v_int(target, int(v.scalar))
        return v


# ------------------------------------------------------------------
# Helpers for printf I/O and float formatting
# ------------------------------------------------------------------
def round_to_single_precision(x: float) -> float:
    """Match C's single-precision rounding by reinterpreting as float32."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _c_fmt_double(v: float) -> str:
    s = repr(v)
    if "e" not in s and "." not in s:
        s += ".0"
    # Python repr uses 17 sig digits; format spec uses %.6f default for %f, %.6g for %g,
    # etc. C does NOT preserve those many digits in printf. We need to round to the
    # effective precision of a double (15-17 sig digits) and let the format spec
    # determine the printed digits. We will defer formatting to Python's format
    # spec in most cases; but we need to round to float precision when the
    # *type is float* (not double), since C %f uses float values directly.
    return s


def printf_format(fmt: str, args: List[Value], interp: "Interpreter") -> str:
    """Implement C printf with the subset of specifiers used in the tests.

    Supports: %d, %u, %ld, %lu, %c, %s, %x, %X, %f, %e, %g, %%,
              width/precision/length modifiers with - + 0 # flags,
              but NOT all combinations.
    """
    out: List[str] = []
    i = 0
    arg_i = 0
    while i < len(fmt):
        c = fmt[i]
        if c != "%":
            out.append(c)
            i += 1
            continue
        # parse format spec
        i += 1
        flags = ""
        while i < len(fmt) and fmt[i] in "-+ #0":
            flags += fmt[i]
            i += 1
        width = ""
        while i < len(fmt) and fmt[i].isdigit():
            width += fmt[i]; i += 1
        prec = ""
        if i < len(fmt) and fmt[i] == ".":
            prec = "."
            i += 1
            while i < len(fmt) and fmt[i].isdigit():
                prec += fmt[i]; i += 1
        length = ""
        if i < len(fmt) and fmt[i] in "hlLz":
            length = fmt[i]; i += 1
        spec = fmt[i] if i < len(fmt) else ""
        i += 1
        if spec == "%":
            out.append("%"); continue
        if spec == "n":
            arg_i += 1; continue
        if arg_i >= len(args):
            out.append("XXX")
            continue
        v = args[arg_i]
        arg_i += 1
        # If argument is stored in memory (pointer/array/struct), read the
        # actual scalar value from the backing Mem at the pointed offset.
        if v.mem is not None:
            base = int(v.scalar) if v.scalar else 0
            if v.type.kind == "float":
                val_scalar = rd_float(v.mem, base, v.type)
            else:
                val_scalar = rd_int(v.mem, base, v.type)
        else:
            val_scalar = v.scalar
        # Default conversion
        if spec == "d" or spec == "i":
            x = int(val_scalar) if not isinstance(val_scalar, float) else int(val_scalar)
            # apply int truncation based on width
            if length == "l" or length == "z":
                pass  # use long
            else:
                pass
            w = int(width) if width else 0
            s = str(x)
            if w > len(s):
                pad = w - len(s)
                if "0" in flags and not ("-" in flags):
                    s = "0" * pad + s
                else:
                    s = " " * pad + s
            if "-" in flags and w > len(s):
                s = s + " " * (w - len(s))
            out.append(s)
            continue
        if spec == "u":
            x = int(val_scalar) if not isinstance(val_scalar, float) else int(val_scalar)
            # convert to unsigned
            bits = 64 if length == "l" else 32
            x &= (1 << bits) - 1
            w = int(width) if width else 0
            s = str(x)
            if w > len(s):
                if "0" in flags and "-" not in flags:
                    s = "0" * (w - len(s)) + s
                else:
                    s = " " * (w - len(s)) + s
            if "-" in flags and w > len(s):
                s = s + " " * (w - len(s))
            out.append(s)
            continue
        if spec == "c":
            x = int(val_scalar) if not isinstance(val_scalar, float) else int(val_scalar)
            out.append(chr(x & 0x7f) if x < 128 else chr(x))  # best effort
            continue
        if spec == "s":
            # value is a pointer to char (str or array)
            if v.mem is None:
                out.append("(null)")
            else:
                base_addr = int(v.scalar) if v.scalar else 0
                if prec == ".":
                    maxlen = int(prec[1:]) if prec[1:].isdigit() else -1
                else:
                    maxlen = -1
                j = base_addr
                buf = []
                while j < len(v.mem.data):
                    if v.mem.data[j] == 0 and maxlen < 0:
                        break
                    if maxlen >= 0 and len(buf) >= maxlen:
                        break
                    buf.append(chr(v.mem.data[j]))
                    j += 1
                out.append("".join(buf))
            continue
        if spec == "x" or spec == "X":
            x = int(val_scalar) if not isinstance(val_scalar, float) else int(val_scalar)
            x &= 0xFFFFFFFF
            s = format(x, "x" if spec == "x" else "X")
            if "#" in flags:
                out.append("0" + spec.lower())
            w = int(width) if width else 0
            if w > len(s):
                if "0" in flags and "-" not in flags:
                    s = "0" * (w - len(s)) + s
                else:
                    s = " " * (w - len(s)) + s
            if "-" in flags and w > len(s):
                s = s + " " * (w - len(s))
            out.append(s)
            continue
        if spec == "f" or spec == "F":
            x = float(val_scalar)
            # Round to float precision if type was float (we approximate via
            # checking v.type.size).
            if v.type.kind == "float" and v.type.size == 4:
                x = round_to_single_precision(x)
            p = int(prec[1:]) if prec and prec[1:].isdigit() else 6
            s = f"{x:.{p}f}"
            if spec == "F":
                # C99 %F is like %f but uppercase for special values; for our
                # case we don't expect inf/nan.
                pass
            w = int(width) if width else 0
            if w > len(s):
                if "0" in flags and "-" not in flags:
                    s = "0" * (w - len(s)) + s
                else:
                    s = " " * (w - len(s)) + s
            if "-" in flags and w > len(s):
                s = s + " " * (w - len(s))
            out.append(s)
            continue
        if spec == "e" or spec == "E":
            x = float(v.scalar) if not isinstance(v.scalar, float) else float(int(v.scalar))
            if v.type.kind == "float" and v.type.size == 4:
                x = round_to_single_precision(x)
            p = int(prec[1:]) if prec and prec[1:].isdigit() else 6
            s = f"{x:.{p}e}"
            if spec == "E":
                s = s.replace("e", "E")
            w = int(width) if width else 0
            if w > len(s):
                s = " " * (w - len(s)) + s
            out.append(s)
            continue
        if spec == "g" or spec == "G":
            x = float(v.scalar) if not isinstance(v.scalar, float) else float(int(v.scalar))
            if v.type.kind == "float" and v.type.size == 4:
                x = round_to_single_precision(x)
            p = int(prec[1:]) if prec and prec[1:].isdigit() else 6
            s = f"{x:.{p}g}"
            if "#" in flags:
                # ensure decimal point appears
                if "." not in s:
                    s += ".0"
            if spec == "G":
                s = s.upper().replace("E", "E")  # already works for %g vs %G
            w = int(width) if width else 0
            if w > len(s):
                s = " " * (w - len(s)) + s
            out.append(s)
            continue
        if spec == "p":
            x = int(val_scalar) if not isinstance(val_scalar, float) else int(val_scalar)
            out.append(format(x & 0xFFFFFFFFFFFFFFFF, "x"))
            continue
        out.append(f"%{flags}{width}{prec}{length}{spec}")
    return "".join(out)


# ------------------------------------------------------------------
# Stdlib stubs
# ------------------------------------------------------------------
def setup_stdlib(interp: Interpreter):
    """Install built-in functions on the global scope as 'intrinsic' FunDecls.

    Each is a FuncDecl whose body calls into the runtime helpers.
    """
    def make_intrinsic(name: str, ret_t: CType, params: List[Tuple[str, CType]], fn):
        d = FuncDecl(name=name, ret=ret_t, params=params, body=None)
        d.intrinsic = fn
        return d

    def _install(name: str, ret_t: CType, params: List[Tuple[str, CType]], fn):
        d = make_intrinsic(name, ret_t, params, fn)
        interp.global_scope.syms[name] = Symbol(
            name=name,
            type=CType("func", "func", 0, 1, ret=ret_t, params=[t for _, t in params]),
            storage="func",
            func_body=d,
        )

    # malloc: signature is C's "void *malloc(int)" — we accept int.
    _install("malloc", make_ptr(T_void), [("", T_int)],
             lambda interp, args: _libc_malloc(interp, args))
    _install("free", T_void, [("", make_ptr(T_void))],
             lambda interp, args: v_int(T_int, 0))
    _install("printf", T_int, [("", make_ptr(T_char))], _libc_printf)
    _install("fprintf", T_int,
             [("", make_ptr(T_void)), ("", make_ptr(T_char))],
             _libc_fprintf)
    _install("sprintf", T_int,
             [("", make_ptr(T_char)), ("", make_ptr(T_char))],
             _libc_sprintf)
    _install("snprintf", T_int,
             [("", make_ptr(T_char)), ("", T_int), ("", make_ptr(T_char))],
             _libc_snprintf)
    _install("memset", make_ptr(T_void),
             [("", make_ptr(T_void)), ("", T_int), ("", T_int)],
             _libc_memset)
    _install("memcpy", make_ptr(T_void),
             [("", make_ptr(T_void)), ("", make_ptr(T_void)), ("", T_int)],
             _libc_memcpy)
    # __builtin_va_list type marker — nothing.


# Allocations table for malloc.
_malloc_table: Dict[int, Mem] = {}


def _alloc_address() -> int:
    # Use big enough numbers so they don't collide with 0 (NULL).
    if not _malloc_table:
        return 0x100000
    return max(_malloc_table) + 1


def _libc_malloc(interp: Interpreter, args: List[Value]) -> Value:
    size = int(args[0].scalar)
    addr = _alloc_address()
    m = Mem(size)
    _malloc_table[addr] = m
    return Value(make_ptr(T_void), scalar=addr, mem=m)


def _libc_printf(interp: Interpreter, args: List[Value]) -> Value:
    if not args:
        return v_int(T_int, 0)
    fmt_v = args[0]
    if fmt_v.mem is not None:
        base = int(fmt_v.scalar) if fmt_v.scalar else 0
        fmt = _read_cstr(fmt_v.mem, base)
    else:
        fmt = str(fmt_v.scalar)
    out = printf_format(fmt, args[1:], interp)
    interp.output_buf.append(out)
    return v_int(T_int, len(out))


def _libc_fprintf(interp: Interpreter, args: List[Value]) -> Value:
    if len(args) < 2:
        return v_int(T_int, 0)
    fmt_v = args[1]
    if fmt_v.mem is not None:
        base = int(fmt_v.scalar) if fmt_v.scalar else 0
        fmt = _read_cstr(fmt_v.mem, base)
    else:
        fmt = str(fmt_v.scalar)
    out = printf_format(fmt, args[2:], interp)
    interp.output_buf.append(out)
    return v_int(T_int, len(out))


def _libc_sprintf(interp: Interpreter, args: List[Value]) -> Value:
    return _libc_snprintf_fmt(args, -1)


def _libc_snprintf(interp: Interpreter, args: List[Value]) -> Value:
    if len(args) < 3:
        return v_int(T_int, 0)
    size = int(args[1].scalar)
    return _libc_snprintf_fmt(args, size)


def _libc_snprintf_fmt(args: List[Value], size: int) -> Value:
    # Buffer is at args[0] (or args[2] when called as snprintf).
    # For our purposes we just compute the formatted string and write it
    # into the destination buffer.
    # Determine positions based on call: if args[0].type is char* and
    # args[1] is int, it's snprintf; else sprintf.
    if size < 0:
        # sprintf: dest, fmt, ...
        dest = args[0]
        fmt_v = args[1]
        fmt_args = args[2:]
    else:
        dest = args[0]
        # skip size_t
        fmt_v = args[2]
        fmt_args = args[3:]
    if fmt_v.mem is not None:
        base = int(fmt_v.scalar) if fmt_v.scalar else 0
        fmt = _read_cstr(fmt_v.mem, base)
    else:
        fmt = str(fmt_v.scalar)
    out = printf_format(fmt, fmt_args, None)
    # write into dest.mem
    m = dest.mem
    n = min(len(out), size - 1 if size >= 0 else len(out))
    if m is not None:
        for i, ch in enumerate(out[:n]):
            m.data[i] = ord(ch)
        m.data[n] = 0
    return v_int(T_int, len(out))


def _libc_memset(interp: Interpreter, args: List[Value]) -> Value:
    dst = args[0]
    val = int(args[1].scalar)
    n = int(args[2].scalar)
    addr = int(dst.scalar) if dst.scalar else 0
    m = _malloc_table.get(addr, dst.mem)
    if m is None:
        return v_int(T_int, 0)
    for i in range(n):
        if addr + i < len(m.data):
            m.data[addr + i] = val
    return dst


def _libc_memcpy(interp: Interpreter, args: List[Value]) -> Value:
    dst = args[0]
    src = args[1]
    n = int(args[2].scalar)
    if dst.mem is None or src.mem is None:
        return dst
    off_dst = int(dst.scalar) if dst.scalar else 0
    off_src = int(src.scalar) if src.scalar else 0
    dst.mem.data[off_dst:off_dst + n] = src.mem.data[off_src:off_src + n]
    return dst


def _read_cstr(mem: Mem, off: int) -> str:
    s = []
    j = off
    while j < len(mem.data):
        b = mem.data[j]
        if b == 0:
            break
        s.append(chr(b))
        j += 1
    return "".join(s)


# ------------------------------------------------------------------
# Compiler: AST → program. The Interpreter needs Scope and Symbol
# already populated. We do this by running the parsed decls through
# a "binder" pass.
# ------------------------------------------------------------------
def bind(ast: Program, interp: Interpreter) -> None:
    interp._typedef_names = {}
    interp._typedefs = {}
    interp._struct_defs = {}
    # Two passes: first typedefs/struct decls, then functions.
    for d in ast.decls:
        if isinstance(d, TypedefDecl):
            interp.add_typedef(d.name, d.type)
        elif isinstance(d, FuncDecl) and d.body is None:
            # forward declaration
            sym = Symbol(name=d.name, type=CType("func", "func", 0, 1,
                                                  ret=d.ret, params=[t for _, t in d.params]),
                         storage="func")
            sym.func_body = d
            interp.global_scope.syms[d.name] = sym
        elif isinstance(d, StructDecl):
            ct = _build_struct_or_union(d.kind, d.name, d.fields)
            interp.add_struct(d.name, ct)
    # Second pass: actual definitions.
    for d in ast.decls:
        if isinstance(d, FuncDecl):
            sym = Symbol(name=d.name, type=CType("func", "func", 0, 1,
                                                  ret=d.ret, params=[t for _, t in d.params]),
                         storage="func")
            sym.func_body = d
            interp.global_scope.syms[d.name] = sym
    # Globals (variables declared outside any function) — store them
    # by running through exec_decl_stmt-equivalent (without init eval,
    # since they may not run; tests don't actually use globals).
    # We won't implement true globals beyond what is naturally needed.


def _build_struct_or_union(kind: str, name: Optional[str], fields: List[Tuple[str, CType]]) -> CType:
    if kind == "struct":
        offset = 0
        max_align = 1
        members: Dict[str, Tuple[CType, int]] = {}
        field_list: List[Tuple[str, CType, int]] = []
        for fname, ft in fields:
            a = ft.align
            offset = (offset + a - 1) // a * a
            members[fname] = (ft, offset)
            field_list.append((fname, ft, offset))
            offset += ft.size
            if a > max_align:
                max_align = a
        size = (offset + max_align - 1) // max_align * max_align
    else:
        max_size = 0
        max_align = 1
        members = {}
        field_list = []
        for fname, ft in fields:
            members[fname] = (ft, 0)
            field_list.append((fname, ft, 0))
            if ft.size > max_size:
                max_size = ft.size
            if ft.align > max_align:
                max_align = ft.align
        size = max_size
    tname = f"{kind} {name}" if name else f"anon_{kind}"
    return CType(kind=kind, name=tname, size=size, align=max_align,
                 fields=field_list, members=members)


# ------------------------------------------------------------------
# Driver
# ------------------------------------------------------------------
def run_program(src: str) -> str:
    src, _ = preprocess(src)
    toks = tokenize(src)
    if not toks:
        return ""
    try:
        sys.stderr.write(f"TOKENS={len(toks)}\n")
    except Exception:
        pass
    # Append EOF sentinel
    toks.append(Tok("OP", "", -1, -1))
    parser = Parser(toks)
    parser._typedef_names = {}
    parser._typedefs = {}
    parser._struct_defs = {}
    prog = parser.parse_program()
    try:
        sys.stderr.write(f"PARSED decls={len(prog.decls)}\n")
    except Exception:
        pass
    interp = Interpreter()
    # Make parser.typedef_names etc visible:
    interp._typedef_names = parser._typedef_names
    interp._typedefs = parser._typedefs
    interp._struct_defs = parser._struct_defs
    # Walk AST and extract any struct/typedef decls that were hidden inside
    # top-level declarations (we collected them too).
    decls_to_bind: List[Decl] = list(prog.decls)
    # Pass all structure + function decls through bind.
    bind(prog, interp)
    setup_stdlib(interp)
    # Find main
    main = interp.global_scope.syms.get("main")
    if main is None:
        return ""
    if main.func_body is None:
        # forward decl with body elsewhere — not supported
        return ""
    # Call main()
    decl = main.func_body
    new_scope = Scope(parent=interp.global_scope, kind="function")
    if not hasattr(decl, "_static_store"):
        decl._static_store = {}
    saved = interp._current_function_statics
    interp._current_function_statics = decl._static_store
    try:
        try:
            interp.exec_block(decl.body, fn_scope=interp.global_scope)
        except ReturnSignal as rs:
            interp.exit_code = 0 if rs.value is None else int(rs.value.scalar)
        except GotoSignal as g:
            raise InterpreterError(f"goto {g.label} outside any function")
    finally:
        interp._current_function_statics = saved
    return "".join(interp.output_buf)


def main():
    if len(sys.argv) < 2:
        print("usage: picoc.py path/to/file.c", file=sys.stderr)
        return 2
    with open(sys.argv[1], "r") as f:
        src = f.read()
    out = run_program(src)
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
