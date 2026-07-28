#!/usr/bin/env python3
"""
Wren programming language interpreter — Python implementation.
Reference: wren-lang/wren-cli (C)
Target language: Python 3
"""

import sys
import os
import math
import time
import shutil
import threading

sys.setrecursionlimit(50000)

# ---------------------------------------------------------------------------
# Exit codes  (mirror wren-cli)
# ---------------------------------------------------------------------------
EXIT_OK            = 0
EXIT_COMPILE_ERROR = 65   # EX_DATAERR
EXIT_RUNTIME_ERROR = 70   # EX_SOFTWARE

# ---------------------------------------------------------------------------
# Control-flow exceptions
# ---------------------------------------------------------------------------
class WrenCompileError(Exception):
    def __init__(self, msg, module="?", line=0):
        super().__init__(msg)
        self.module = module
        self.wren_line = line

class WrenRuntimeError(Exception):
    pass

class _Return(Exception):
    def __init__(self, value): self.value = value

class _Break(Exception): pass
class _Continue(Exception): pass
class _FiberYield(Exception):
    def __init__(self, value): self.value = value
class _FiberAbort(Exception):
    def __init__(self, value): self.value = value

# ---------------------------------------------------------------------------
# Number formatting  (integers without ".0")
# ---------------------------------------------------------------------------
def _num_str(n):
    if math.isnan(n): return "nan"
    if math.isinf(n): return "infinity" if n > 0 else "-infinity"
    if n == 0.0:
        return "-0" if math.copysign(1.0, n) == -1.0 else "0"
    if not math.isinf(n) and n == int(n) and abs(n) < 1e14:
        return str(int(n))
    s = f"{n:.14g}"
    if s.endswith('.0'): s = s[:-2]
    return s

# ---------------------------------------------------------------------------
# TOKEN TYPES
# ---------------------------------------------------------------------------
TT_NUM  = 'NUM'
TT_STR  = 'STR'
TT_NAME = 'NAME'
TT_NL   = 'NL'
TT_EOF  = 'EOF'

KEYWORDS = {
    'as','break','class','construct','continue','else',
    'false','for','foreign','if','import','in','is',
    'null','return','static','super','this','true','var','while',
}

class Token:
    __slots__ = ('type','val','line')
    def __init__(self, t, v, ln):
        self.type=t; self.val=v; self.line=ln
    def __repr__(self):
        return f'Token({self.type!r},{self.val!r},L{self.line})'

# ---------------------------------------------------------------------------
# LEXER
# ---------------------------------------------------------------------------
class Lexer:
    def __init__(self, src, module='(script)'):
        self.src=src; self.module=module; self.pos=0; self.line=1

    def _err(self, msg, line=None):
        ln = line if line is not None else self.line
        raise WrenCompileError(f'[{self.module} line {ln}] Error: {msg}', self.module, ln)

    def _peek(self, off=0):
        i = self.pos+off
        return self.src[i] if i < len(self.src) else '\0'

    def _adv(self):
        ch = self.src[self.pos]; self.pos += 1
        if ch == '\n': self.line += 1
        return ch

    def _match(self, c):
        if self.pos < len(self.src) and self.src[self.pos] == c:
            self.pos += 1; return True
        return False

    def _skip_line_comment(self):
        while self.pos < len(self.src) and self.src[self.pos] != '\n':
            self.pos += 1

    def _skip_block_comment(self):
        depth=1; sl=self.line
        while self.pos < len(self.src):
            c = self._adv()
            if c=='/' and self._peek()=='*': self._adv(); depth+=1
            elif c=='*' and self._peek()=='/': self._adv(); depth-=1
            if depth==0: return
        self._err('Unterminated block comment.', sl)

    def _read_escape(self):
        if self.pos >= len(self.src):
            self._err('Incomplete escape sequence.')
        e = self.src[self.pos]; self.pos += 1
        if e=='"':  return '"'
        if e=='\\': return '\\'
        if e=='0':  return '\0'
        if e=='a':  return '\a'
        if e=='b':  return '\b'
        if e=='f':  return '\f'
        if e=='n':  return '\n'
        if e=='r':  return '\r'
        if e=='t':  return '\t'
        if e=='v':  return '\v'
        if e=='%':  return '%'
        if e=='x':
            h=''
            for _ in range(2):
                if self.pos>=len(self.src) or self.src[self.pos] not in '0123456789abcdefABCDEF':
                    self._err('Invalid byte escape sequence.')
                h+=self.src[self.pos]; self.pos+=1
            return chr(int(h,16))
        if e=='u':
            h=''
            for _ in range(4):
                if self.pos>=len(self.src) or self.src[self.pos] not in '0123456789abcdefABCDEF':
                    self._err('Invalid Unicode escape sequence.')
                h+=self.src[self.pos]; self.pos+=1
            return chr(int(h,16))
        if e=='U':
            h=''
            for _ in range(8):
                if self.pos>=len(self.src) or self.src[self.pos] not in '0123456789abcdefABCDEF':
                    self._err('Invalid Unicode escape sequence.')
                h+=self.src[self.pos]; self.pos+=1
            cp=int(h,16)
            if cp>0x10FFFF: self._err('Invalid Unicode code point.')
            return chr(cp)
        self._err(f"Invalid escape character '{e}'.")

    def _read_str_segment(self):
        buf=''
        while True:
            if self.pos>=len(self.src): self._err('Unterminated string.')
            c=self.src[self.pos]
            if c=='"':   self.pos+=1; return buf, False
            if c=='\n':  self._err('Unterminated string.')
            if c=='%' and self._peek(1)=='(':
                self.pos+=2; return buf, True
            if c=='\\':
                self.pos+=1; buf+=self._read_escape()
            else:
                buf+=c; self.pos+=1

    def _lex_str_tokens(self, sl):
        out=[]
        seg, interp = self._read_str_segment()
        if not interp:
            out.append(Token(TT_STR, seg, sl)); return out
        out.append(Token('ISTART', seg, sl))
        while True:
            depth=1
            while depth>0:
                self._skip_ws_in_interp()
                if self.pos>=len(self.src): self._err('Unterminated string interpolation.')
                c=self.src[self.pos]
                if c=='(':
                    self.pos+=1; depth+=1; out.append(Token('(','(',self.line))
                elif c==')':
                    self.pos+=1; depth-=1
                    if depth>0: out.append(Token(')',')',self.line))
                elif c=='"':
                    self.pos+=1; out.extend(self._lex_str_tokens(self.line))
                else:
                    out.extend(self._one_token())
            seg2, interp2 = self._read_str_segment()
            if not interp2:
                out.append(Token('IEND', seg2, self.line)); break
            else:
                out.append(Token('IMID', seg2, self.line))
        return out

    def _skip_ws_in_interp(self):
        while self.pos<len(self.src) and self.src[self.pos] in ' \t\r':
            self.pos+=1
        if self.pos<len(self.src) and self.src[self.pos]=='\n':
            self.pos+=1; self.line+=1
            return self._skip_ws_in_interp()
        if self.pos<len(self.src) and self.src[self.pos]=='/' and self._peek(1)=='/':
            self.pos+=2; self._skip_line_comment(); return self._skip_ws_in_interp()
        if self.pos<len(self.src) and self.src[self.pos]=='/' and self._peek(1)=='*':
            self.pos+=2; self._skip_block_comment(); return self._skip_ws_in_interp()

    def _one_token(self):
        sl=self.line; src=self.src
        if self.pos>=len(src): return [Token(TT_EOF,None,sl)]
        c=src[self.pos]; self.pos+=1
        out=[]
        if c == '0' and self.pos < len(src) and src[self.pos] in 'xX':
            self.pos += 1
            hs = ''
            while self.pos < len(src) and (src[self.pos] in '0123456789abcdefABCDEF' or src[self.pos] == '_'):
                if src[self.pos] != '_': hs += src[self.pos]
                self.pos += 1
            out.append(Token(TT_NUM, float(int(hs or '0', 16)), sl))
        elif c == '0' and self.pos < len(src) and src[self.pos] in 'bB':
            self.pos += 1
            bs = ''
            while self.pos < len(src) and (src[self.pos] in '01' or src[self.pos] == '_'):
                if src[self.pos] != '_': bs += src[self.pos]
                self.pos += 1
            out.append(Token(TT_NUM, float(int(bs or '0', 2)), sl))
        elif c.isdigit():
            ns=c
            while self.pos<len(src) and (src[self.pos].isdigit() or src[self.pos]=='_'):
                if src[self.pos]!='_': ns+=src[self.pos]
                self.pos+=1
            if self.pos<len(src) and src[self.pos]=='.' and self.pos+1<len(src) and src[self.pos+1].isdigit():
                ns+='.'; self.pos+=1
                while self.pos<len(src) and src[self.pos].isdigit():
                    ns+=src[self.pos]; self.pos+=1
            if self.pos<len(src) and src[self.pos] in 'eE':
                ns+=src[self.pos]; self.pos+=1
                if self.pos<len(src) and src[self.pos] in '+-': ns+=src[self.pos]; self.pos+=1
                while self.pos<len(src) and src[self.pos].isdigit(): ns+=src[self.pos]; self.pos+=1
            out.append(Token(TT_NUM,float(ns),sl))
        elif c.isalpha() or c=='_':
            name=c
            while self.pos<len(src) and (src[self.pos].isalnum() or src[self.pos]=='_'):
                name+=src[self.pos]; self.pos+=1
            tt = name if name in KEYWORDS else TT_NAME
            out.append(Token(tt,name,sl))
        elif c in '+-*/%':
            if self._match('='): out.append(Token(c+'=',c+'=',sl))
            else: out.append(Token(c,c,sl))
        elif c=='&':
            if self._match('&'): out.append(Token('&&','&&',sl))
            elif self._match('='): out.append(Token('&=','&=',sl))
            else: out.append(Token('&','&',sl))
        elif c=='|':
            if self._match('|'): out.append(Token('||','||',sl))
            elif self._match('='): out.append(Token('|=','|=',sl))
            else: out.append(Token('|','|',sl))
        elif c=='^':
            if self._match('='): out.append(Token('^=','^=',sl))
            else: out.append(Token('^','^',sl))
        elif c=='!':
            if self._match('='): out.append(Token('!=','!=',sl))
            else: out.append(Token('!','!',sl))
        elif c=='=':
            if self._match('='): out.append(Token('==','==',sl))
            else: out.append(Token('=','=',sl))
        elif c=='<':
            if self._match('<'):
                if self._match('='): out.append(Token('<<=','<<=',sl))
                else: out.append(Token('<<','<<',sl))
            elif self._match('='): out.append(Token('<=','<=',sl))
            else: out.append(Token('<','<',sl))
        elif c=='>':
            if self._match('>'):
                if self._match('='): out.append(Token('>>=','>>=',sl))
                else: out.append(Token('>>','>>',sl))
            elif self._match('='): out.append(Token('>=','>=',sl))
            else: out.append(Token('>','>',sl))
        elif c=='.':
            if self._match('.'):
                if self._match('.'): out.append(Token('...','...',sl))
                else: out.append(Token('..','..', sl))
            else: out.append(Token('.','.',sl))
        elif c in '()[]{},:;~@?':
            out.append(Token(c,c,sl))
        else:
            self._err(f"Unexpected character '{c}'.", sl)
        return out

    def tokenize(self):
        toks=[]; src=self.src; shebang_ok=True
        while self.pos<len(src):
            sl=self.line; c=src[self.pos]
            if c in ' \t\r': self.pos+=1; continue
            if c=='\n': self.pos+=1; self.line+=1; toks.append(Token(TT_NL,'\n',self.line-1)); continue
            if c=='#':
                self._skip_line_comment(); shebang_ok=False; continue
            shebang_ok=False
            if c=='/' and self._peek(1)=='/': self.pos+=2; self._skip_line_comment(); continue
            if c=='/' and self._peek(1)=='*': self.pos+=2; self._skip_block_comment(); continue
            if c=='"': self.pos+=1; toks.extend(self._lex_str_tokens(sl)); continue
            toks.extend(self._one_token())
        toks.append(Token(TT_EOF,None,self.line))
        return toks

# ---------------------------------------------------------------------------
# AST NODES
# ---------------------------------------------------------------------------
class Node: pass

class Program(Node):
    def __init__(self,stmts): self.stmts=stmts
class VarDecl(Node):
    def __init__(self,name,init,line): self.name=name;self.init=init;self.line=line
class ClassDecl(Node):
    def __init__(self,name,super_expr,methods,foreign,line):
        self.name=name;self.super_expr=super_expr;self.methods=methods;self.foreign=foreign;self.line=line
class MethodDef(Node):
    def __init__(self,name,is_static,params,body,is_construct,is_foreign,line):
        self.name=name;self.is_static=is_static;self.params=params
        self.body=body;self.is_construct=is_construct;self.is_foreign=is_foreign;self.line=line
class ImportStmt(Node):
    def __init__(self,path,names,line): self.path=path;self.names=names;self.line=line
class IfStmt(Node):
    def __init__(self,cond,then_br,else_br,line): self.cond=cond;self.then_br=then_br;self.else_br=else_br;self.line=line
class WhileStmt(Node):
    def __init__(self,cond,body,line): self.cond=cond;self.body=body;self.line=line
class ForStmt(Node):
    def __init__(self,var,iter_expr,body,line): self.var=var;self.iter_expr=iter_expr;self.body=body;self.line=line
class BreakStmt(Node):
    def __init__(self,line): self.line=line
class ContinueStmt(Node):
    def __init__(self,line): self.line=line
class ReturnStmt(Node):
    def __init__(self,value,line): self.value=value;self.line=line
class Block(Node):
    def __init__(self,stmts): self.stmts=stmts
class ExprStmt(Node):
    def __init__(self,expr): self.expr=expr

class Literal(Node):
    def __init__(self,value): self.value=value
class StringInterp(Node):
    def __init__(self,parts): self.parts=parts
class NameExpr(Node):
    def __init__(self,name,line): self.name=name;self.line=line
class FieldGet(Node):
    def __init__(self,name,line): self.name=name;self.line=line
class FieldSet(Node):
    def __init__(self,name,op,value,line): self.name=name;self.op=op;self.value=value;self.line=line
class ThisExpr(Node):
    def __init__(self,line): self.line=line
class SuperExpr(Node):
    def __init__(self,method,args,bp,bb,line):
        self.method=method;self.args=args;self.bp=bp;self.bb=bb;self.line=line
class TernaryExpr(Node):
    def __init__(self,cond,then_br,else_br,line):
        self.cond=cond;self.then_br=then_br;self.else_br=else_br;self.line=line
class BinOp(Node):
    def __init__(self,op,left,right,line): self.op=op;self.left=left;self.right=right;self.line=line
class UnOp(Node):
    def __init__(self,op,operand,line): self.op=op;self.operand=operand;self.line=line
class Assign(Node):
    def __init__(self,target,op,value,line): self.target=target;self.op=op;self.value=value;self.line=line
class GetAttr(Node):
    def __init__(self,obj,name,line): self.obj=obj;self.name=name;self.line=line
class SetAttr(Node):
    def __init__(self,obj,name,op,value,line): self.obj=obj;self.name=name;self.op=op;self.value=value;self.line=line
class CallMethod(Node):
    def __init__(self,obj,name,args,bp,bb,line): self.obj=obj;self.name=name;self.args=args;self.bp=bp;self.bb=bb;self.line=line
class Call(Node):
    def __init__(self,callee,args,bp,bb,line): self.callee=callee;self.args=args;self.bp=bp;self.bb=bb;self.line=line
class Subscript(Node):
    def __init__(self,obj,idx,line): self.obj=obj;self.idx=idx;self.line=line
class SubscriptSet(Node):
    def __init__(self,obj,idx,value,line): self.obj=obj;self.idx=idx;self.value=value;self.line=line
class ListExpr(Node):
    def __init__(self,items): self.items=items
class MapExpr(Node):
    def __init__(self,pairs): self.pairs=pairs
class FnExpr(Node):
    def __init__(self,params,body,line): self.params=params;self.body=body;self.line=line
class RangeExpr(Node):
    def __init__(self,start,end,inclusive,line): self.start=start;self.end=end;self.inclusive=inclusive;self.line=line
class IsExpr(Node):
    def __init__(self,obj,cls,line): self.obj=obj;self.cls=cls;self.line=line

# ---------------------------------------------------------------------------
# PARSER
# ---------------------------------------------------------------------------
class Parser:
    def __init__(self,tokens,module='(script)'):
        self.tokens=tokens; self.pos=0; self.module=module
        self.current_method_name = None

    def _err(self,msg,tok=None):
        tok=tok or self._cur()
        ln=tok.line
        if tok.type==TT_EOF: at='end of file'
        elif tok.type==TT_NL: at='newline'
        else: at=f'"{tok.val}"'
        raise WrenCompileError(f'[{self.module} line {ln}] Error at {at}: {msg}', self.module, ln)

    def _cur(self): return self.tokens[self.pos]
    def _peek(self,off=1):
        i=self.pos+off
        return self.tokens[i] if i<len(self.tokens) else self.tokens[-1]
    def _adv(self):
        t=self.tokens[self.pos]
        if self.pos+1<len(self.tokens): self.pos+=1
        return t
    def _check(self,*types): return self._cur().type in types
    def _match(self,*types):
        if self._cur().type in types: return self._adv()
        return None
    def _expect(self,tt,msg=None):
        if self._cur().type==tt: return self._adv()
        self._err(msg or f'Expected "{tt}".')
    def _skip_nl(self):
        while self._check(TT_NL): self._adv()
    def _expect_nl(self):
        self._match(TT_NL,';')

    def parse(self):
        stmts=[]; self._skip_nl()
        while not self._check(TT_EOF):
            stmts.append(self._stmt()); self._skip_nl()
        return Program(stmts)

    def _stmt(self):
        self._skip_nl(); t=self._cur()
        if t.type=='class': return self._class_decl(False)
        if t.type=='foreign' and self._peek().type=='class': return self._class_decl(True)
        if t.type=='import': return self._import()
        if t.type=='var':    return self._var()
        if t.type=='if':     return self._if()
        if t.type=='while':  return self._while()
        if t.type=='for':    return self._for()
        if t.type=='break':  self._adv(); self._expect_nl(); return BreakStmt(t.line)
        if t.type=='continue': self._adv(); self._expect_nl(); return ContinueStmt(t.line)
        if t.type=='return': return self._return()
        if t.type=='{':      b=self._block(); self._expect_nl(); return b
        expr=self._expr(); self._expect_nl(); return ExprStmt(expr)

    def _class_decl(self, foreign):
        if foreign: self._adv()
        ln=self._cur().line; self._adv()
        name=self._expect(TT_NAME,'Expected class name.').val
        sup=None
        if self._match('is'): sup=self._primary()
        self._skip_nl(); self._expect('{','Expected "{".')
        methods=[]
        self._skip_nl()
        while not self._check('}',TT_EOF):
            methods.append(self._method()); self._skip_nl()
        self._expect('}','Expected "}".')
        return ClassDecl(name,sup,methods,foreign,ln)

    def _method(self):
        ln=self._cur().line
        is_static=False; is_foreign=False; is_construct=False
        while True:
            if self._match('static'): is_static=True
            elif self._match('foreign'): is_foreign=True
            elif self._match('construct'): is_construct=True; is_static=True
            else: break
        t=self._cur()
        if t.type in ('+','-','*','/','%','<','>','<=','>=','==','!=','&','|','^','<<','>>','~','..','...'):
            name=t.val; self._adv()
            if self._match('='): name+='='
            old_m = self.current_method_name; self.current_method_name = name
            params,body=self._method_sig_body(is_foreign)
            self.current_method_name = old_m
            return MethodDef(name,is_static,params,body,is_construct,is_foreign,ln)
        if t.type=='[':
            self._adv(); params=[]
            self._skip_nl()
            while not self._check(']',TT_EOF):
                params.append(self._expect(TT_NAME).val)
                self._skip_nl()
                if not self._match(','): break
                self._skip_nl()
            self._expect(']')
            if self._match('='):
                params.append(self._expect(TT_NAME,'Expected setter param.').val); name='[]='
            else: name='[]'
            old_m = self.current_method_name; self.current_method_name = name
            body=self._method_body(is_foreign)
            self.current_method_name = old_m
            return MethodDef(name,is_static,params,body,is_construct,is_foreign,ln)
        name=self._expect(TT_NAME,'Expected method name.').val
        if self._match('='):
            if self._check('('):
                self._adv(); self._skip_nl()
                param=self._expect(TT_NAME,'Expected setter parameter.').val
                self._skip_nl(); self._expect(')')
            else:
                param=self._expect(TT_NAME,'Expected setter parameter.').val
            old_m = self.current_method_name; self.current_method_name = name+'='
            body=self._method_body(is_foreign)
            self.current_method_name = old_m
            return MethodDef(name+'=',is_static,[param],body,is_construct,is_foreign,ln)
        old_m = self.current_method_name; self.current_method_name = name
        params,body=self._method_sig_body(is_foreign)
        self.current_method_name = old_m
        return MethodDef(name,is_static,params,body,is_construct,is_foreign,ln)

    def _method_sig_body(self,is_foreign):
        if self._check('('):
            self._adv(); params=[]
            self._skip_nl()
            if not self._check(')'):
                while True:
                    params.append(self._expect(TT_NAME,'Expected parameter.').val)
                    self._skip_nl()
                    if not self._match(','): break
                    self._skip_nl()
            self._expect(')')
            return params, self._method_body(is_foreign)
        return None, self._method_body(is_foreign)

    def _method_body(self,is_foreign):
        if is_foreign: self._expect_nl(); return None
        self._skip_nl(); return self._block()

    def _block(self):
        self._expect('{','Expected "{".'); stmts=[]; self._skip_nl()
        while not self._check('}',TT_EOF):
            stmts.append(self._stmt()); self._skip_nl()
        self._expect('}','Expected "}".')
        return Block(stmts)

    def _import(self):
        ln=self._cur().line; self._adv()
        path=self._expect(TT_STR,'Expected module path.').val
        names=None
        if self._match('for'):
            names=[]
            while True:
                orig=self._expect(TT_NAME,'Expected import name.').val
                alias=orig
                if self._match('as'): alias=self._expect(TT_NAME).val
                names.append((orig,alias))
                if not self._match(','): break
        self._expect_nl(); return ImportStmt(path,names,ln)

    def _var(self):
        ln=self._cur().line; self._adv()
        name=self._expect(TT_NAME,'Expected variable name.').val
        init=None
        if self._match('='):
            self._skip_nl()
            init=self._expr()
        self._expect_nl(); return VarDecl(name,init,ln)

    def _if(self):
        ln=self._cur().line; self._adv()
        self._expect('('); cond=self._expr(); self._expect(')')
        self._skip_nl(); then_br=self._stmt()
        else_br=None; saved=self.pos; self._skip_nl()
        if self._match('else'): self._skip_nl(); else_br=self._stmt()
        else: self.pos=saved
        return IfStmt(cond,then_br,else_br,ln)

    def _while(self):
        ln=self._cur().line; self._adv()
        self._expect('('); cond=self._expr(); self._expect(')')
        self._skip_nl(); body=self._stmt()
        return WhileStmt(cond,body,ln)

    def _for(self):
        ln=self._cur().line; self._adv()
        self._expect('('); var=self._expect(TT_NAME).val
        self._expect('in'); it=self._expr(); self._expect(')')
        self._skip_nl(); body=self._stmt()
        return ForStmt(var,it,body,ln)

    def _return(self):
        ln=self._cur().line; self._adv(); val=None
        if not self._check(TT_NL,';','}',TT_EOF): val=self._expr()
        self._expect_nl(); return ReturnStmt(val,ln)

    def _expr(self): return self._assign()

    def _assign(self):
        left=self._cond()
        op=self._cur().type
        if op in ('=','+=','-=','*=','/=','%=','&=','|=','^=','<<=','>>='):
            ln=self._cur().line; self._adv()
            self._skip_nl()
            right=self._assign()
            if isinstance(left,NameExpr):    return Assign(left,op,right,ln)
            if isinstance(left,FieldGet):    return FieldSet(left.name,op,right,ln)
            if isinstance(left,GetAttr):     return SetAttr(left.obj,left.name,op,right,ln)
            if isinstance(left,Subscript):   return SubscriptSet(left.obj,left.idx,right,ln)
            self._err('Invalid assignment target.')
        return left

    def _cond(self):
        l=self._or()
        if self._match('?'):
            ln=self._cur().line
            self._skip_nl()
            then_br=self._expr()
            self._skip_nl()
            self._expect(':')
            self._skip_nl()
            else_br=self._expr()
            return TernaryExpr(l, then_br, else_br, ln)
        return l

    def _or(self):
        l=self._and()
        while self._check('||'): ln=self._cur().line; self._adv(); r=self._and(); l=BinOp('||',l,r,ln)
        return l

    def _and(self):
        l=self._eq()
        while self._check('&&'): ln=self._cur().line; self._adv(); r=self._eq(); l=BinOp('&&',l,r,ln)
        return l

    def _eq(self):
        l=self._is()
        while self._check('==','!='): op=self._cur().type; ln=self._cur().line; self._adv(); r=self._is(); l=BinOp(op,l,r,ln)
        return l

    def _is(self):
        l=self._cmp()
        if self._check('is'): ln=self._cur().line; self._adv(); r=self._cmp(); return IsExpr(l,r,ln)
        return l

    def _cmp(self):
        l=self._bitor()
        while self._check('<','>','<=','>='): op=self._cur().type; ln=self._cur().line; self._adv(); r=self._bitor(); l=BinOp(op,l,r,ln)
        return l

    def _bitor(self):
        l=self._bitxor()
        while self._check('|'): ln=self._cur().line; self._adv(); r=self._bitxor(); l=BinOp('|',l,r,ln)
        return l

    def _bitxor(self):
        l=self._bitand()
        while self._check('^'): ln=self._cur().line; self._adv(); r=self._bitand(); l=BinOp('^',l,r,ln)
        return l

    def _bitand(self):
        l=self._shift()
        while self._check('&'): ln=self._cur().line; self._adv(); r=self._shift(); l=BinOp('&',l,r,ln)
        return l

    def _shift(self):
        l=self._range()
        while self._check('<<','>>'): op=self._cur().type; ln=self._cur().line; self._adv(); r=self._range(); l=BinOp(op,l,r,ln)
        return l

    def _range(self):
        l=self._add()
        if self._check('..','...'):
            op=self._cur().type; ln=self._cur().line; self._adv(); r=self._add()
            return RangeExpr(l,r,op=='..',ln)
        return l

    def _add(self):
        l=self._mul()
        while self._check('+','-'): op=self._cur().type; ln=self._cur().line; self._adv(); r=self._mul(); l=BinOp(op,l,r,ln)
        return l

    def _mul(self):
        l=self._unary()
        while self._check('*','/','%'): op=self._cur().type; ln=self._cur().line; self._adv(); r=self._unary(); l=BinOp(op,l,r,ln)
        return l

    def _unary(self):
        if self._check('!','-','~'):
            op=self._cur().type; ln=self._cur().line; self._adv(); return UnOp(op,self._unary(),ln)
        return self._postfix()

    def _postfix(self):
        e=self._primary()
        while True:
            t=self._cur()
            if t.type=='.':
                ln=t.line; self._adv()
                name=self._expect(TT_NAME,'Expected property name.').val
                if self._match('='):
                    val=self._assign(); e=SetAttr(e,name,'=',val,ln)
                elif self._check('(') or self._check('{'):
                    args,bp,bb=self._call_args(); e=CallMethod(e,name,args,bp,bb,ln)
                else:
                    e=GetAttr(e,name,ln)
            elif t.type=='[':
                ln=t.line; self._adv(); self._skip_nl()
                idx=self._expr(); self._skip_nl()
                # multi-arg subscript
                idxs=[idx]
                while self._match(','):
                    self._skip_nl(); idxs.append(self._expr()); self._skip_nl()
                self._skip_nl(); self._expect(']')
                idx = idxs[0] if len(idxs)==1 else tuple(idxs)
                if self._match('='): val=self._assign(); e=SubscriptSet(e,idx,val,ln)
                else: e=Subscript(e,idx,ln)
            elif t.type=='(':
                ln=t.line; args,bp,bb=self._call_args(); e=Call(e,args,bp,bb,ln)
            elif t.type=='{':
                ln=t.line; bp,bb=self._block_arg(); e=Call(e,[],bp,bb,ln)
            else: break
        return e

    def _call_args(self):
        args=[]; bp=None; bb=None
        if self._check('('):
            self._adv(); self._skip_nl()
            while not self._check(')',TT_EOF):
                args.append(self._expr()); self._skip_nl()
                if not self._match(','): break
                self._skip_nl()
            self._skip_nl(); self._expect(')')
        if self._check('{'): bp,bb=self._block_arg()
        return args,bp,bb

    def _block_arg(self):
        self._adv(); params=[]
        if self._match('|'):
            while not self._check('|',TT_EOF):
                params.append(self._expect(TT_NAME,'Expected param.').val)
                if not self._match(','): break
            self._expect('|')
        stmts=[]; self._skip_nl()
        while not self._check('}',TT_EOF):
            stmts.append(self._stmt()); self._skip_nl()
        self._expect('}'); return params, Block(stmts)

    def _primary(self):
        t=self._cur()
        if t.type==TT_NUM:  self._adv(); return Literal(t.val)
        if t.type==TT_STR:  self._adv(); return Literal(t.val)
        if t.type=='ISTART': return self._interp_str()
        if t.type=='true':  self._adv(); return Literal(True)
        if t.type=='false': self._adv(); return Literal(False)
        if t.type=='null':  self._adv(); return Literal(None)
        if t.type=='this':  self._adv(); return ThisExpr(t.line)
        if t.type=='super':
            ln=t.line; self._adv(); method=None
            if self._match('.'): method=self._expect(TT_NAME,'Expected method name.').val
            else: method = self.current_method_name
            args,bp,bb=self._call_args()
            return SuperExpr(method,args,bp,bb,ln)
        if t.type==TT_NAME:
            self._adv()
            if t.val.startswith('_'): return FieldGet(t.val,t.line)
            return NameExpr(t.val,t.line)
        if t.type=='(':
            self._adv(); self._skip_nl(); e=self._expr(); self._skip_nl()
            self._expect(')'); return e
        if t.type=='[':
            ln=t.line; self._adv(); items=[]; self._skip_nl()
            while not self._check(']',TT_EOF):
                items.append(self._expr()); self._skip_nl()
                if not self._match(','): break
                self._skip_nl()
            self._expect(']'); return ListExpr(items)
        if t.type=='{':
            return self._map_or_block()
        self._err(f'Expected expression.', t)

    def _interp_str(self):
        parts=[]; t=self._cur(); self._adv()
        parts.append(t.val)
        parts.append(self._expr())
        while True:
            t=self._cur()
            if t.type=='IMID':  self._adv(); parts.append(t.val); parts.append(self._expr())
            elif t.type=='IEND': self._adv(); parts.append(t.val); break
            else: self._err('Unterminated string interpolation.')
        return StringInterp(parts)

    def _map_or_block(self):
        ln=self._cur().line
        off=1
        while self._peek(off).type=='NL': off+=1
        p1=self._peek(off); p2=self._peek(off+1)
        if p1.type=='}':
            for _ in range(off+1): self._adv()
            return MapExpr([])
        if p1.type in (TT_STR,TT_NAME,TT_NUM,'true','false','null','(') and p2.type==':':
            return self._map_literal(ln)
        bp,bb=self._block_arg(); return FnExpr(bp,bb,ln)

    def _map_literal(self,ln):
        self._adv(); pairs=[]; self._skip_nl()
        while not self._check('}',TT_EOF):
            k=self._expr(); self._expect(':'); self._skip_nl(); v=self._expr()
            pairs.append((k,v)); self._skip_nl()
            if not self._match(','): break
            self._skip_nl()
            if self._check('}'): break
        self._expect('}'); return MapExpr(pairs)

# ---------------------------------------------------------------------------
# RUNTIME VALUES
# ---------------------------------------------------------------------------
class WrenClass:
    def __init__(self,name,superclass=None):
        self.name=name; self.superclass=superclass
        self.methods={}; self.static_methods={}
        self.static_fields={}
    def find_method(self,name):
        curr=self; visited=set()
        while curr and curr not in visited:
            visited.add(curr)
            m=curr.methods.get(name)
            if m is not None: return m
            curr=curr.superclass
        return None
    def find_static(self,name):
        return self.static_methods.get(name)
    def __repr__(self): return self.name

class WrenInstance:
    def __init__(self,klass): self.klass=klass; self.fields={}
    def __repr__(self): return f'instance of {self.klass.name}'

class WrenMapEntry:
    def __init__(self, key, value, klass):
        self.key = key; self.value = value; self.klass = klass
    def __repr__(self): return f'instance of {self.klass.name}'

class WrenFileStat:
    def __init__(self, path, klass):
        self.path = path; self.klass = klass
        self.is_dir = os.path.isdir(path) if os.path.exists(path) else False
        self.is_file = os.path.isfile(path) if os.path.exists(path) else False
        self.size = float(os.path.getsize(path)) if os.path.exists(path) else 0.0
    def __repr__(self): return f'instance of {self.klass.name}'

class WrenFn:
    def __init__(self,params,body,closure,name='(fn)'):
        self.params=params; self.body=body; self.closure=closure; self.name=name

class WrenFiber:
    def __init__(self,fn,interp):
        self.fn=fn; self.interp=interp; self.done=False; self.error=None
        self._thread=None
        self._caller_event=None  # set when caller resumes fiber
        self._fiber_event=None   # set when fiber yields/completes
        self._send_val=None      # value sent from caller to fiber
        self._yield_val=None     # value yielded from fiber to caller
    def __repr__(self): return '(fiber)'

class WrenRange:
    def __init__(self,s,e,inclusive): self.start=s; self.end=e; self.inclusive=inclusive
    def __repr__(self):
        op='..' if self.inclusive else '...'; return f'{_num_str(self.start)}{op}{_num_str(self.end)}'
    def seq(self):
        s,e=int(self.start),int(self.end)
        if self.inclusive:
            return list(range(s,e+1)) if s<=e else list(range(s,e-1,-1))
        else:
            if s<e: return list(range(s,e))
            if s>e: return list(range(s,e+1,-1))
            return []

class WrenSeq:
    def __init__(self, items, klass):
        self.items = items; self.klass = klass
    def __repr__(self): return f'instance of {self.klass.name}'

class WrenFileStat:
    def __init__(self, path, klass):
        self.path = path; self.klass = klass
        st = os.stat(path) if os.path.exists(path) else None
        self.is_file = float(os.path.isfile(path)) if st else 0.0
        self.is_dir = float(os.path.isdir(path)) if st else 0.0
        self.size = float(st.st_size) if st else 0.0
        self.device = float(st.st_dev) if st else 0.0
        self.inode = float(st.st_ino) if st else 0.0
        self.mode = float(st.st_mode) if st else 0.0
        self.link_count = float(getattr(st, 'st_nlink', 1)) if st else 1.0
        self.user = float(getattr(st, 'st_uid', 0)) if st else 0.0
        self.group = float(getattr(st, 'st_gid', 0)) if st else 0.0
        self.special_device = float(getattr(st, 'st_rdev', 0)) if st else 0.0
        self.block_size = float(getattr(st, 'st_blksize', 4096)) if st else 4096.0
        self.blocks = float(getattr(st, 'st_blocks', 0)) if st else 0.0
        self.is_device = False
        self.is_fifo = False
        self.is_socket = False
        self.is_special = False
    def __repr__(self): return 'instance of Stat'

class WrenFile:
    def __init__(self, path, fp, klass):
        self.path = path; self.fp = fp; self.klass = klass; self.closed = False
    def __repr__(self): return 'instance of File'

_UNDEF=object()

# ---------------------------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------------------------
class Env:
    def __init__(self,parent=None): self.vars={}; self.parent=parent
    def get(self,n):
        curr=self; visited=set()
        while curr and id(curr) not in visited:
            visited.add(id(curr))
            if n in curr.vars: return curr.vars[n]
            curr=curr.parent
        return _UNDEF
    def set(self,n,v):
        curr=self; visited=set()
        while curr and id(curr) not in visited:
            visited.add(id(curr))
            if n in curr.vars:
                curr.vars[n]=v; return True
            curr=curr.parent
        return False
    def define(self,n,v): self.vars[n]=v

class WrenMethod:
    def __init__(self,name,params,body,closure,is_construct=False,klass=None):
        self.name=name; self.params=params; self.body=body
        self.closure=closure; self.is_construct=is_construct; self.klass=klass

# ---------------------------------------------------------------------------
# INTERPRETER
# ---------------------------------------------------------------------------
class Interpreter:
    _tls = threading.local()

    def __init__(self,module='(script)',cwd=None):
        self.module=module; self.cwd=cwd or os.getcwd()
        self.globals=Env(); self._modules={}
        self._exit_code=0
        self._sched_queue=[]
        self._setup_builtins()

    @property
    def _current_fiber(self):
        return getattr(Interpreter._tls,'current_fiber',None)
    @_current_fiber.setter
    def _current_fiber(self,v):
        Interpreter._tls.current_fiber=v

    def _setup_builtins(self):
        g=self.globals
        def mc(n,s=None): c=WrenClass(n,s); g.define(n,c); return c
        self.cObject   =mc('Object')
        self.cClass    =mc('Class',   self.cObject)
        self.cSeq      =mc('Sequence',self.cObject)
        self.cBool     =mc('Bool',    self.cObject)
        self.cNum      =mc('Num',     self.cObject)
        self.cString   =mc('String',  self.cObject)
        self.cNull     =mc('Null',    self.cObject)
        self.cList     =mc('List',    self.cSeq)
        self.cMap      =mc('Map',     self.cSeq)
        self.cMapEntry =mc('MapEntry',self.cObject)
        self.cRange    =mc('Range',   self.cSeq)
        self.cFn       =mc('Fn',      self.cObject)
        self.cFiber    =mc('Fiber',   self.cObject)
        self.cSystem   =mc('System',  self.cObject)
        self.cStringBytes = mc('StringByteSequence', self.cSeq)
        self.cStringCodes = mc('StringCodePointSequence', self.cSeq)
        self.cMKS      =mc('MapKeySequence',  self.cSeq)
        self.cMVS      =mc('MapValueSequence',self.cSeq)

        self._build_object()
        self._build_seq()
        self._build_num()
        self._build_string()
        self._build_bool()
        self._build_null()
        self._build_list()
        self._build_map()
        self._build_range()
        self._build_fn()
        self._build_fiber()
        self._build_system()
        self._build_builtin_modules()

    def _sm(self,cls,name,fn,static=False):
        if static: cls.static_methods[name]=fn
        else:      cls.methods[name]=fn

    def _build_object(self):
        c=self.cObject; I=self
        self._sm(self.cClass, 'name', lambda r,a=None: r.name if isinstance(r,WrenClass) else 'Class')
        self._sm(c,'toString',    lambda r,a=None: f'{r.name} metaclass' if isinstance(r,WrenClass) else (f'instance of {r.klass.name}' if isinstance(r,WrenInstance) else I._str(r)))
        self._sm(c,'type',        lambda r,a=None: I._typeof(r))
        self._sm(c,'type',        lambda r,a=None: WrenClass(f'{r.name} metaclass', I.cClass) if isinstance(r,WrenClass) else I._typeof(r), static=True)
        self._sm(c,'is(_)',       lambda r,a: I._is_instance(r,a[0]))
        self._sm(c,'==(_)',       lambda r,a: r is a[0] or r==a[0])
        self._sm(c,'!=(_)',       lambda r,a: r is not a[0] and r!=a[0])
        self._sm(c,'==(_)',       lambda r,a: r is a[0], static=True)
        self._sm(c,'!=(_)',       lambda r,a: r is not a[0], static=True)
        self._sm(c,'!',           lambda r,a=None: r is None or r is False)
        self._sm(c,'hash',        lambda r,a=None: float(id(r)&0xFFFFFFFF))
        self._sm(c,'same(_,_)',   lambda r,a: (a[0] is a[1]) or (type(a[0])==type(a[1]) and a[0]==a[1]), static=True)

        self._sm(self.cMapEntry, 'key', lambda r,a=None: r.key)
        self._sm(self.cMapEntry, 'value', lambda r,a=None: r.value)
        self._sm(self.cMapEntry, 'toString', lambda r,a=None: f'{I._str(r.key)}:{I._str(r.value)}')
        self._sm(self.cMapEntry, 'new(_,_)', lambda r,a: WrenMapEntry(a[0],a[1],r), static=True)

    def _build_seq(self):
        c=self.cSeq; I=self
        self._sm(c,'isEmpty', lambda r,a=None: len(I._to_iter(r))==0)
        self._sm(c,'take(_)', lambda r,a: I._to_iter(r)[:int(a[0])])
        def seq_bytes(recv, args=None):
            return WrenSeq([float(b) for b in recv.encode('utf-8')], I.cStringBytes)
        def seq_codes(recv, args=None):
            return WrenSeq([float(ord(ch)) for ch in recv], I.cStringCodes)
        def seq_sub(recv, args):
            i = int(args[0])
            if 0 <= i < len(recv.items): return recv.items[i]
            I._rt('Sequence index out of bounds.')
        self._sm(self.cStringBytes, '[](_)', seq_sub)
        self._sm(self.cStringBytes, '[_]',   seq_sub)
        self._sm(self.cStringCodes, '[](_)', seq_sub)
        self._sm(self.cStringCodes, '[_]',   seq_sub)
        I._seq_bytes_fn = seq_bytes
        I._seq_codes_fn = seq_codes

    def _build_num(self):
        c=self.cNum; I=self
        def n(v):
            if not isinstance(v,float): I._rt('Expected a number.')
            return v
        self._sm(c,'+(_)',  lambda r,a: n(r)+n(a[0]))
        self._sm(c,'-(_)',  lambda r,a: n(r)-n(a[0]))
        self._sm(c,'*(_)',  lambda r,a: n(r)*n(a[0]))
        self._sm(c,'/(_)',  lambda r,a: n(r)/n(a[0]) if a[0]!=0.0 else
                            (math.inf if r>0 else (-math.inf if r<0 else math.nan)))
        self._sm(c,'%(_)',  lambda r,a: math.fmod(n(r),n(a[0])))
        self._sm(c,'<(_)',  lambda r,a: n(r)<n(a[0]))
        self._sm(c,'>(_)',  lambda r,a: n(r)>n(a[0]))
        self._sm(c,'<=(_)', lambda r,a: n(r)<=n(a[0]))
        self._sm(c,'>=(_)', lambda r,a: n(r)>=n(a[0]))
        self._sm(c,'==(_)', lambda r,a: isinstance(a[0],float) and n(r)==a[0])
        self._sm(c,'!=(_)', lambda r,a: not isinstance(a[0],float) or n(r)!=a[0])
        self._sm(c,'-',     lambda r,a=None: -n(r))
        self._sm(c,'~',     lambda r,a=None: float(~int(n(r))))
        self._sm(c,'&(_)',  lambda r,a: float(int(n(r))&int(n(a[0]))))
        self._sm(c,'|(_)',  lambda r,a: float(int(n(r))|int(n(a[0]))))
        self._sm(c,'^(_)',  lambda r,a: float(int(n(r))^int(n(a[0]))))
        self._sm(c,'<<(_)', lambda r,a: float(int(n(r))<<int(n(a[0]))))
        self._sm(c,'>>(_)', lambda r,a: float(int(n(r))>>int(n(a[0]))))
        self._sm(c,'..(_)',  lambda r,a: WrenRange(n(r),n(a[0]),True))
        self._sm(c,'...(_)', lambda r,a: WrenRange(n(r),n(a[0]),False))
        self._sm(c,'toString',   lambda r,a=None: _num_str(n(r)))
        self._sm(c,'abs',        lambda r,a=None: abs(n(r)))
        self._sm(c,'ceil',       lambda r,a=None: float(math.ceil(n(r))))
        self._sm(c,'floor',      lambda r,a=None: float(math.floor(n(r))))
        self._sm(c,'round',      lambda r,a=None: float(round(n(r))))
        self._sm(c,'sqrt',       lambda r,a=None: math.sqrt(n(r)))
        self._sm(c,'log',        lambda r,a=None: math.log(n(r)) if n(r)>0 else math.nan)
        self._sm(c,'log2',       lambda r,a=None: math.log2(n(r)) if n(r)>0 else math.nan)
        self._sm(c,'exp',        lambda r,a=None: math.exp(n(r)))
        self._sm(c,'sin',        lambda r,a=None: math.sin(n(r)))
        self._sm(c,'cos',        lambda r,a=None: math.cos(n(r)))
        self._sm(c,'tan',        lambda r,a=None: math.tan(n(r)))
        self._sm(c,'asin',       lambda r,a=None: math.asin(n(r)))
        self._sm(c,'acos',       lambda r,a=None: math.acos(n(r)))
        self._sm(c,'atan',       lambda r,a=None: math.atan(n(r)))
        self._sm(c,'atan(_)',    lambda r,a: math.atan2(n(r),n(a[0])))
        self._sm(c,'pow(_)',     lambda r,a: n(r)**n(a[0]))
        self._sm(c,'min(_)',     lambda r,a: min(n(r),n(a[0])))
        self._sm(c,'max(_)',     lambda r,a: max(n(r),n(a[0])))
        self._sm(c,'clamp(_,_)', lambda r,a: max(n(a[0]),min(n(r),n(a[1]))))
        self._sm(c,'fraction',   lambda r,a=None: math.modf(n(r))[0])
        self._sm(c,'truncate',   lambda r,a=None: float(math.trunc(n(r))))
        self._sm(c,'isNan',      lambda r,a=None: math.isnan(n(r)))
        self._sm(c,'isInfinity', lambda r,a=None: math.isinf(n(r)))
        self._sm(c,'isInteger',  lambda r,a=None: not math.isinf(n(r)) and n(r)==int(n(r)))
        self._sm(c,'sign',       lambda r,a=None: 0.0 if n(r)==0 else (1.0 if n(r)>0 else -1.0))

        self._sm(c,'pi',       lambda r,a=None: math.pi, static=True)
        self._sm(c,'tau',      lambda r,a=None: math.tau, static=True)
        self._sm(c,'infinity', lambda r,a=None: math.inf, static=True)
        self._sm(c,'nan',      lambda r,a=None: math.nan, static=True)
        self._sm(c,'largest',  lambda r,a=None: 1.7976931348623157e+308, static=True)
        self._sm(c,'smallest', lambda r,a=None: 2.2250738585072014e-308, static=True)
        self._sm(c,'maxSafeInteger', lambda r,a=None: float(2**53-1), static=True)
        self._sm(c,'minSafeInteger', lambda r,a=None: float(-(2**53-1)), static=True)
        self._sm(c,'fromString(_)', lambda r,a: (float(a[0]) if isinstance(a[0],str) and a[0] else None), static=True)

    def _build_string(self):
        c=self.cString; I=self
        def s(v):
            if not isinstance(v,str): I._rt('Expected a string.')
            return v
        self._sm(c,'+(_)',    lambda r,a: s(r)+I._str(a[0]))
        self._sm(c,'*(_)',    lambda r,a: s(r)*int(a[0]))
        self._sm(c,'==(_)',   lambda r,a: isinstance(a[0],str) and s(r)==a[0])
        self._sm(c,'!=(_)',   lambda r,a: not isinstance(a[0],str) or s(r)!=a[0])
        self._sm(c,'<(_)',    lambda r,a: s(r)<s(a[0]))
        self._sm(c,'>(_)',    lambda r,a: s(r)>s(a[0]))
        self._sm(c,'<=(_)',   lambda r,a: s(r)<=s(a[0]))
        self._sm(c,'>=(_)',   lambda r,a: s(r)>=s(a[0]))
        self._sm(c,'toString',lambda r,a=None: s(r))
        self._sm(c,'count',   lambda r,a=None: float(len(s(r))))
        self._sm(c,'bytes',   lambda r,a=None: I._seq_bytes_fn(s(r)))
        self._sm(c,'codePoints', lambda r,a=None: I._seq_codes_fn(s(r)))
        self._sm(c,'isEmpty',     lambda r,a=None: len(s(r))==0)
        self._sm(c,'contains(_)',   lambda r,a: a[0] in s(r))
        self._sm(c,'startsWith(_)', lambda r,a: s(r).startswith(s(a[0])))
        self._sm(c,'endsWith(_)',   lambda r,a: s(r).endswith(s(a[0])))
        self._sm(c,'indexOf(_)',    lambda r,a: float(s(r).find(s(a[0]))))
        self._sm(c,'indexOf(_,_)',  lambda r,a: float(s(r).find(s(a[0]),int(a[1]))))
        self._sm(c,'replace(_,_)',  lambda r,a: s(r).replace(s(a[0]),s(a[1])))
        self._sm(c,'split(_)',      lambda r,a: (list(s(r)) if s(a[0])=='' else s(r).split(s(a[0]))))
        self._sm(c,'trim',          lambda r,a=None: s(r).strip())
        self._sm(c,'trimEnd',       lambda r,a=None: s(r).rstrip())
        self._sm(c,'trimStart',     lambda r,a=None: s(r).lstrip())
        self._sm(c,'toLowerCase',   lambda r,a=None: s(r).lower())
        self._sm(c,'toUpperCase',   lambda r,a=None: s(r).upper())
        self._sm(c,'toList',        lambda r,a=None: list(s(r)))
        self._sm(c,'hash',          lambda r,a=None: float(hash(s(r))&0xFFFFFFFF))
        def _idx(r,a):
            i=int(a[0]); r2=s(r)
            if i<0: i=len(r2)+i
            if 0<=i<len(r2): return r2[i]
            I._rt('String index out of bounds.')
        self._sm(c,'[](_)', _idx)
        self._sm(c,'[_]',   _idx)
        self._sm(c,'byteCount_', lambda r,a=None: float(len(s(r).encode('utf-8'))))
        self._sm(c,'codePointAt_(_)', lambda r,a: float(ord(s(r)[int(a[0])])))
        self._sm(c,'byteAt_(_)', lambda r,a: float(list(s(r).encode('utf-8'))[int(a[0])]))
        self._sm(c,'fromCodePoint(_)', lambda r,a: chr(int(a[0])), static=True)
        self._sm(c,'fromByte(_)',       lambda r,a: bytes([int(a[0])]).decode('latin-1'), static=True)

    def _build_bool(self):
        c=self.cBool
        self._sm(c,'toString', lambda r,a=None: 'true' if r else 'false')
        self._sm(c,'!',        lambda r,a=None: not r)
        self._sm(c,'==(_)',    lambda r,a: isinstance(a[0],bool) and r==a[0])
        self._sm(c,'!=(_)',    lambda r,a: not isinstance(a[0],bool) or r!=a[0])

    def _build_null(self):
        c=self.cNull
        self._sm(c,'toString', lambda r,a=None: 'null')
        self._sm(c,'!',        lambda r,a=None: True)
        self._sm(c,'==(_)',    lambda r,a: a[0] is None)
        self._sm(c,'!=(_)',    lambda r,a: a[0] is not None)

    def _build_list(self):
        c=self.cList; I=self
        self._sm(c,'new()', lambda r,a=None: [], static=True)
        self._sm(c,'new', lambda r,a=None: [], static=True)
        self._sm(c,'filled(_,_)', lambda r,a: [a[1]]*int(a[0]), static=True)
        def idx(lst,i):
            i2=int(i)
            if i2<0: i2=len(lst)+i2
            if 0<=i2<len(lst): return lst[i2]
            I._rt('List index out of bounds.')
        self._sm(c,'add(_)',      lambda r,a: (r.append(a[0]),r)[1])
        self._sm(c,'insert(_,_)', lambda r,a: (r.insert(int(a[0]) if int(a[0])>=0 else max(0,len(r)+int(a[0])+1),a[1]),r)[1])
        self._sm(c,'removeAt(_)', lambda r,a: r.pop(int(a[0]) if int(a[0])>=0 else len(r)+int(a[0])))
        self._sm(c,'remove(_)',   lambda r,a: self._list_remove_val(r,a[0]))
        self._sm(c,'count',       lambda r,a=None: float(len(r)))
        self._sm(c,'isEmpty',     lambda r,a=None: len(r)==0)
        self._sm(c,'clear',       lambda r,a=None: (r.clear(),r)[1])
        self._sm(c,'[](_)',       lambda r,a: idx(r,a[0]))
        self._sm(c,'[_]',         lambda r,a: idx(r,a[0]))
        self._sm(c,'[]=(_,_)',    lambda r,a: self._list_set(r,a[0],a[1]))
        self._sm(c,'toString',    lambda r,a=None: '['+', '.join(I._str(x) for x in r)+']')
        self._sm(c,'contains(_)', lambda r,a: any(x==a[0] for x in r))
        self._sm(c,'indexOf(_)',  lambda r,a: float(next((i for i,x in enumerate(r) if x==a[0]),-1)))
        self._sm(c,'sort()',      lambda r,a=None: (r.sort(key=lambda x:I._str(x)),r)[1])
        self._sm(c,'sort(_)',     lambda r,a: self._list_sort_fn(r,a[0]))
        self._sm(c,'join()',      lambda r,a=None: ''.join(I._str(x) for x in r))
        self._sm(c,'join(_)',     lambda r,a: a[0].join(I._str(x) for x in r))
        self._sm(c,'where(_)',    lambda r,a: [x for x in r if I._call_fn(a[0],[x])])
        self._sm(c,'map(_)',      lambda r,a: [I._call_fn(a[0],[x]) for x in r])
        self._sm(c,'reduce(_)',   lambda r,a: self._list_reduce(r,a[0]))
        self._sm(c,'reduce(_,_)', lambda r,a: self._list_reduce2(r,a[0],a[1]))
        self._sm(c,'each(_)',     lambda r,a: [I._call_fn(a[0],[x]) for x in r] and None)
        self._sm(c,'any(_)',      lambda r,a: any(I._call_fn(a[0],[x]) for x in r))
        self._sm(c,'all(_)',      lambda r,a: all(I._call_fn(a[0],[x]) for x in r))
        self._sm(c,'skip(_)',     lambda r,a: r[int(a[0]):])
        self._sm(c,'take(_)',     lambda r,a: r[:int(a[0])])
        self._sm(c,'reversed',   lambda r,a=None: list(reversed(r)))
        self._sm(c,'first',      lambda r,a=None: r[0] if r else None)
        self._sm(c,'last',       lambda r,a=None: r[-1] if r else None)
        self._sm(c,'first(_)',   lambda r,a: r[:int(a[0])])
        self._sm(c,'last(_)',    lambda r,a: r[-int(a[0]):] if a[0] else [])
        self._sm(c,'toList',     lambda r,a=None: list(r))
        self._sm(c,'iterate(_)', lambda r,a: (0.0 if r else False) if (a[0] is None or a[0] is False) else (float(a[0]+1) if a[0]+1<len(r) else False))
        self._sm(c,'iteratorValue(_)', lambda r,a: r[int(a[0])])
        self._sm(c,'filled(_,_)', lambda r,a: [a[1]]*int(a[0]), static=True)

    def _list_remove_val(self,lst,val):
        for i,x in enumerate(lst):
            if x==val or x is val: return lst.pop(i)
        return None

    def _list_set(self,lst,idx,val):
        i=int(idx)
        if i<0: i=len(lst)+i
        if 0<=i<len(lst): lst[i]=val; return val
        self._rt('List index out of bounds.')

    def _list_sort_fn(self,lst,fn):
        import functools
        def cmp(a,b):
            r=self._call_fn(fn,[a,b])
            return -1 if r<0 else (1 if r>0 else 0)
        lst.sort(key=functools.cmp_to_key(cmp)); return lst

    def _list_reduce(self,lst,fn):
        if not lst: self._rt('Cannot reduce an empty list.')
        acc=lst[0]
        for item in lst[1:]:
            if isinstance(fn, WrenFn): acc=self._call_fn(fn,[acc,item])
            else: acc=self._dispatch(fn,'call',[acc,item])
        return acc

    def _list_reduce2(self,lst,fn,init):
        acc=init
        for x in lst: acc=self._call_fn(fn,[acc,x])
        return acc

    def _build_map(self):
        c=self.cMap; I=self
        self._sm(c,'[](_)',          lambda r,a: r.get(a[0]))
        self._sm(c,'[_]',            lambda r,a: r.get(a[0]))
        self._sm(c,'[]=(_,_)',       lambda r,a: (r.__setitem__(a[0],a[1]),a[1])[1])
        self._sm(c,'count',          lambda r,a=None: float(len(r)))
        self._sm(c,'isEmpty',        lambda r,a=None: len(r)==0)
        self._sm(c,'containsKey(_)', lambda r,a: a[0] in r)
        self._sm(c,'remove(_)',      lambda r,a: r.pop(a[0],None))
        self._sm(c,'clear',          lambda r,a=None: (r.clear(),r)[1])
        self._sm(c,'keys',           lambda r,a=None: list(r.keys()))
        self._sm(c,'values',         lambda r,a=None: list(r.values()))
        self._sm(c,'toString',       lambda r,a=None: '{'+', '.join(I._str(k)+': '+I._str(v) for k,v in r.items())+'}')
        self._sm(c,'each(_)',        lambda r,a: [I._call_fn(a[0],[k,v]) for k,v in r.items()] and None)
        self._sm(c,'toList',         lambda r,a=None: [WrenMapEntry(k,v,I.cMapEntry) for k,v in r.items()])
        self._sm(c,'iterate(_)',     lambda r,a: self._map_iter(r,a[0]))
        self._sm(c,'iteratorValue(_)', lambda r,a: self._map_iter_val(r,a[0]))

    def _map_iter(self,d,state):
        keys=list(d.keys())
        if state is None or state is False:
            return keys[0] if keys else False
        try:
            idx=keys.index(state)
            return keys[idx+1] if idx+1<len(keys) else False
        except (ValueError,IndexError): return False

    def _map_iter_val(self,d,state):
        if state in d:
            return WrenMapEntry(state, d[state], self.cMapEntry)
        return None

    def _build_range(self):
        c=self.cRange; I=self
        self._sm(c,'from',       lambda r,a=None: r.start)
        self._sm(c,'to',         lambda r,a=None: r.end)
        self._sm(c,'isInclusive',lambda r,a=None: r.inclusive)
        self._sm(c,'min',        lambda r,a=None: min(r.start,r.end))
        self._sm(c,'max',        lambda r,a=None: max(r.start,r.end))
        self._sm(c,'count',      lambda r,a=None: float(len(r.seq())))
        self._sm(c,'contains(_)',lambda r,a: self._range_contains(r,a[0]))
        self._sm(c,'toString',   lambda r,a=None: repr(r))
        self._sm(c,'toList',     lambda r,a=None: [float(x) for x in r.seq()])
        self._sm(c,'iterate(_)', lambda r,a: self._range_iter(r,a[0]))
        self._sm(c,'iteratorValue(_)', lambda r,a: float(a[0]))

    def _range_contains(self,r,v):
        if not isinstance(v,float): return False
        s,e=r.start,r.end
        if r.inclusive: return (s<=v<=e) if s<=e else (e<=v<=s)
        else: return (s<=v<e) if s<e else (e<v<=s if s>e else False)

    def _range_iter(self,r,state):
        seq=r.seq()
        if state is None or state is False:
            return float(seq[0]) if seq else False
        iv=int(state)
        try: idx=seq.index(iv)
        except ValueError: return False
        return float(seq[idx+1]) if idx+1<len(seq) else False

    def _build_fn(self):
        c=self.cFn; I=self
        def mk_call(n):
            self._sm(c,f'call({",".join(["_"]*n)})', lambda r,a: I._call_fn(r,a) if n>0 else I._call_fn(r,[]))
        self._sm(c,'call()', lambda r,a=None: I._call_fn(r,[]))
        for n in range(1,17): mk_call(n)
        self._sm(c,'arity',   lambda r,a=None: float(len(r.params) if r.params else 0))
        self._sm(c,'toString',lambda r,a=None: '(fn)')
        self._sm(c,'new(_)',  lambda r,a: a[0], static=True)

    def _build_fiber(self):
        c=self.cFiber; I=self
        self._sm(c,'call()',    lambda r,a=None: I._fiber_call(r,None))
        self._sm(c,'call(_)',   lambda r,a: I._fiber_call(r,a[0]))
        self._sm(c,'transfer()',lambda r,a=None: I._fiber_call(r,None))
        self._sm(c,'transfer(_)',lambda r,a: I._fiber_call(r,a[0]))
        self._sm(c,'try()',      lambda r,a=None: I._fiber_try(r,None))
        self._sm(c,'try(_)',     lambda r,a: I._fiber_try(r,a[0]))
        self._sm(c,'isDone',    lambda r,a=None: r.done)
        self._sm(c,'error',     lambda r,a=None: r.error)
        self._sm(c,'toString',  lambda r,a=None: '(fiber)')
        self._sm(c,'new(_)',    lambda r,a: I._new_fiber(a[0]), static=True)
        self._sm(c,'yield()',   lambda r,a=None: I._fiber_yield(None), static=True)
        self._sm(c,'yield(_)',  lambda r,a: I._fiber_yield(a[0]), static=True)
        self._sm(c,'abort(_)',  lambda r,a: self._rt(I._str(a[0])), static=True)
        self._sm(c,'current',   lambda r,a=None: I._current_fiber, static=True)

    def _new_fiber(self,fn):
        if not isinstance(fn,WrenFn): self._rt('Fiber body must be a function.')
        f = WrenFiber(fn,self); return f

    def _fiber_run(self, fiber, initial):
        """Thread target: run fiber body, signal caller on yield/done."""
        import threading
        fn=fiber.fn; env=Env(fn.closure)
        if fn.params:
            for i,p in enumerate(fn.params):
                env.define(p, initial if i==0 else None)
        # inject yield support via monkey-patching the fiber yield static method
        fiber._yield_fn = self._make_fiber_yield_fn(fiber)
        saved=self._current_fiber; self._current_fiber=fiber
        try:
            try:
                result=self._exec_block(fn.body,env)
            except _Return as r:
                result=r.value
            fiber._yield_val=result; fiber.done=True
        except WrenRuntimeError as e:
            fiber.error=str(e); fiber._yield_val=None; fiber.done=True
        except SystemExit as e:
            fiber.done=True; fiber._yield_val=None; raise
        finally:
            self._current_fiber=saved
        fiber._fiber_event.set()

    def _make_fiber_yield_fn(self, fiber):
        """Return a function that suspends the fiber thread."""
        def do_yield(val):
            fiber._yield_val=val
            fiber.is_running=False
            fiber._fiber_event.set()   # wake caller
            fiber._caller_event.wait(); fiber._caller_event.clear()  # wait for resume
            fiber.is_running=True
            return fiber._send_val
        return do_yield

    def _fiber_call(self,fiber,val):
        import threading
        if not isinstance(fiber,WrenFiber): self._rt('Not a fiber.')
        if fiber.done: self._rt('Cannot resume a finished fiber.')
        if getattr(fiber, 'is_running', False): self._rt('Cannot call a running fiber.')
        fiber.is_running = True
        if fiber._thread is None:
            fiber._caller_event=threading.Event()
            fiber._fiber_event=threading.Event()
            fiber._send_val=val
            # Patch Fiber.yield to use thread suspension
            self._active_fiber_yield_fn=self._make_fiber_yield_fn(fiber)
            t=threading.Thread(target=self._fiber_run,args=(fiber,val),daemon=True)
            fiber._thread=t; t.start()
        else:
            fiber._send_val=val
            fiber._caller_event.set()  # resume fiber
        fiber._fiber_event.wait(); fiber._fiber_event.clear()
        if fiber.error:
            fiber.is_running=False
            raise WrenRuntimeError(fiber.error)
        return fiber._yield_val

    def _fiber_try(self,fiber,val):
        import threading
        if not isinstance(fiber,WrenFiber): self._rt('Not a fiber.')
        if fiber.done: return None
        try:
            return self._fiber_call(fiber,val)
        except WrenRuntimeError as e:
            fiber.error=str(e); fiber.done=True; return None

    def _fiber_gen(self,fiber,initial):
        # Kept for compatibility but unused in thread-based model
        fn=fiber.fn; env=Env(fn.closure)
        if fn.params:
            for i,p in enumerate(fn.params):
                env.define(p, initial if i==0 else None)
        saved=self._current_fiber; self._current_fiber=fiber
        try:
            try:
                result=self._exec_block(fn.body,env)
            except _Return as r:
                result=r.value
        except WrenRuntimeError:
            self._current_fiber=saved; fiber.done=True; raise
        finally:
            self._current_fiber=saved
        fiber.done=True
        return result

    def _fiber_yield(self,val):
        # When using thread-based fibers, delegate to active fiber's yield fn
        if self._current_fiber and hasattr(self._current_fiber,'_yield_fn') and self._current_fiber._yield_fn:
            self._current_fiber._yield_fn(val)
        else:
            raise _FiberYield(val)

    def _run_scheduler(self):
        """Run all scheduled fibers (simple cooperative round-robin)"""
        import heapq
        # pending_fibers: list of (wake_time, fiber)
        while self._sched_queue:
            self._sched_queue.sort(key=lambda x: x[0])
            wake_time, fiber = self._sched_queue.pop(0)
            now = time.time()
            if wake_time > now:
                time.sleep(wake_time - now)
            if not fiber.done:
                try:
                    self._fiber_call(fiber, None)
                except WrenRuntimeError:
                    pass

    def _build_system(self):
        c=self.cSystem; I=self
        def sys_print(r,a):
            s=I._str(a[0]); sys.stdout.write(s+'\n'); sys.stdout.flush(); return a[0]
        def sys_write(r,a):
            s=I._str(a[0]); sys.stdout.write(s); sys.stdout.flush(); return a[0]
        def sys_print_all(r,a):
            items = I._to_iter(a[0])
            if items:
                for x in items:
                    sys.stdout.write(I._str(x))
                sys.stdout.write('\n')
                sys.stdout.flush()
            return None
        self._sm(c,'print(_)',   sys_print,  static=True)
        self._sm(c,'write(_)',   sys_write,  static=True)
        self._sm(c,'printAll(_)',sys_print_all, static=True)
        self._sm(c,'gc',         lambda r,a=None: None, static=True)
        self._sm(c,'clock',      lambda r,a=None: time.time(), static=True)
        self._sm(c,'exit(_)',    lambda r,a: sys.exit(int(a[0])), static=True)

    def _active_fiber_yield_fn(self): pass  # placeholder overwritten at runtime

    def _build_builtin_modules(self):
        mod_os = Env()
        cPlatform = WrenClass('Platform', self.cObject)
        cProcess = WrenClass('Process', self.cObject)
        self._sm(cPlatform, 'name', lambda r,a=None: 'windows' if os.name=='nt' else 'linux', static=True)
        self._sm(cPlatform, 'isWindows', lambda r,a=None: os.name=='nt', static=True)
        self._sm(cPlatform, 'isPosix', lambda r,a=None: os.name!='nt', static=True)
        self._sm(cPlatform, 'homePath', lambda r,a=None: os.path.expanduser('~').replace('\\','/'), static=True)
        self._sm(cPlatform, 'homedir', lambda r,a=None: os.path.expanduser('~').replace('\\','/'), static=True)
        self._sm(cProcess, 'pid', lambda r,a=None: float(os.getpid()), static=True)
        self._sm(cProcess, 'ppid', lambda r,a=None: float(os.getppid()) if hasattr(os,'getppid') else 1.0, static=True)
        self._sm(cProcess, 'cwd', lambda r,a=None: os.getcwd(), static=True)
        self._sm(cProcess, 'version', lambda r,a=None: '0.4.0', static=True)
        mod_os.define('Platform', cPlatform)
        mod_os.define('Process', cProcess)
        self._modules['os'] = mod_os

        I = self
        I._sched_counter = 0
        mod_timer = Env()
        cTimer = WrenClass('Timer', self.cObject)
        def timer_sleep(r, a):
            raw_ms = a[0]
            if not isinstance(raw_ms, (int, float)):
                I._rt('sleep ms must be a number.')
            ms = int(raw_ms)
            secs = ms / 1000.0
            if I._current_fiber and hasattr(I._current_fiber,'_yield_fn') and I._current_fiber._yield_fn:
                wake_time = time.time() + secs
                I._current_fiber._sleep_until = wake_time
                I._current_fiber._yield_fn(None)
                return None
            deadline = time.time() + secs
            while I._sched_queue:
                I._sched_queue.sort(key=lambda x: (x[0], x[1]))
                if I._sched_queue[0][0] > deadline: break
                wake_t, _, fiber = I._sched_queue.pop(0)
                now2 = time.time()
                if wake_t > now2: time.sleep(wake_t - now2)
                if not fiber.done:
                    try: I._resume_fiber_fully(fiber)
                    except WrenRuntimeError: pass
            now3 = time.time()
            if deadline > now3: time.sleep(deadline - now3)
            return None
        self._sm(cTimer, 'sleep(_)', timer_sleep, static=True)
        mod_timer.define('Timer', cTimer)
        self._modules['timer'] = mod_timer

        mod_sched = Env()
        cScheduler = WrenClass('Scheduler', self.cObject)
        def sched_add(r, a):
            fn = a[0]
            if isinstance(fn, WrenFn):
                fiber = I._new_fiber(fn)
                I._sched_counter += 1
                I._sched_queue.append((time.time(), I._sched_counter, fiber))
            return None
        self._sm(cScheduler, 'add(_)', sched_add, static=True)
        mod_sched.define('Scheduler', cScheduler)
        self._modules['scheduler'] = mod_sched

        mod_io = Env()
        cFileFlags = WrenClass('FileFlags', self.cObject)
        self._sm(cFileFlags, 'readOnly', lambda r,a=None: 1.0, static=True)
        self._sm(cFileFlags, 'writeOnly', lambda r,a=None: 2.0, static=True)
        self._sm(cFileFlags, 'readWrite', lambda r,a=None: 4.0, static=True)
        self._sm(cFileFlags, 'sync', lambda r,a=None: 8.0, static=True)
        self._sm(cFileFlags, 'create', lambda r,a=None: 16.0, static=True)
        self._sm(cFileFlags, 'exclusive', lambda r,a=None: 64.0, static=True)
        self._sm(cFileFlags, 'truncate', lambda r,a=None: 32.0, static=True)
        mod_io.define('FileFlags', cFileFlags)
        cFile = WrenClass('File', self.cObject)
        cDir = WrenClass('Directory', self.cObject)
        cStat = WrenClass('Stat', self.cObject)
        cStdin = WrenClass('Stdin', self.cObject)
        cStdout = WrenClass('Stdout', self.cObject)

        def file_create(r, a):
            p = a[0]; flags = int(a[1]) if len(a)>1 else 0
            fp = open(p, 'wb+')
            return WrenFile(p, fp, cFile)

        def file_open(r, a):
            p = a[0]; flags = int(a[1]) if len(a)>1 else 0
            if not os.path.exists(p): return None
            mode = 'rb+' if (flags & 4 or flags & 2) else 'rb'
            try: fp = open(p, mode)
            except IOError: fp = open(p, 'rb')
            return WrenFile(p, fp, cFile)

        def file_stat(r, a):
            p = a[0]
            if not os.path.exists(p): return None
            return WrenFileStat(p, cStat)

        def dir_create(r, a):
            p = a[0]
            if os.path.exists(p): I._rt('Directory already exists.')
            parent = os.path.dirname(p)
            if parent and not os.path.exists(parent): I._rt('Parent directory does not exist.')
            os.makedirs(p); return None

        self._sm(cFile, 'create(_)', lambda r,a: file_create(r,[a[0],0]), static=True)
        self._sm(cFile, 'create(_,_)', file_create, static=True)
        self._sm(cFile, 'open(_)', lambda r,a: file_open(r,[a[0],0]), static=True)
        self._sm(cFile, 'openWithFlags(_,_)', file_open, static=True)
        self._sm(cFile, 'delete(_)', lambda r,a: os.remove(a[0]) if os.path.exists(a[0]) else None, static=True)
        self._sm(cFile, 'exists(_)', lambda r,a: os.path.isfile(a[0]), static=True)
        self._sm(cFile, 'realPath(_)', lambda r,a: os.path.realpath(a[0]).replace('\\','/') if a[0] else False, static=True)
        self._sm(cFile, 'size(_)', lambda r,a: float(os.path.getsize(a[0])) if os.path.exists(a[0]) else False, static=True)
        self._sm(cFile, 'read(_)', lambda r,a: (open(a[0],'r',encoding='utf-8').read() if os.path.exists(a[0]) else ''), static=True)
        self._sm(cFile, 'stat(_)', file_stat, static=True)

        self._sm(cFile, 'isOpen', lambda r,a=None: not r.closed if isinstance(r,WrenFile) else False)
        self._sm(cFile, 'close()', lambda r,a=None: (r.fp.close(), setattr(r,'closed',True))[1] if isinstance(r,WrenFile) else None)
        self._sm(cFile, 'close', lambda r,a=None: (r.fp.close(), setattr(r,'closed',True))[1] if isinstance(r,WrenFile) else None)
        self._sm(cFile, 'read()', lambda r,a=None: r.fp.read().decode('utf-8') if isinstance(r,WrenFile) else '')
        self._sm(cFile, 'read', lambda r,a=None: r.fp.read().decode('utf-8') if isinstance(r,WrenFile) else '')
        self._sm(cFile, 'size', lambda r,a=None: float(os.path.getsize(r.path)) if isinstance(r,WrenFile) else 0.0)
        self._sm(cFile, 'stat', lambda r,a=None: WrenFileStat(r.path, cStat) if isinstance(r,WrenFile) else None)

        self._sm(cDir, 'create(_)', dir_create, static=True)
        self._sm(cDir, 'delete(_)', lambda r,a: os.rmdir(a[0]) if os.path.isdir(a[0]) else None, static=True)
        self._sm(cDir, 'exists(_)', lambda r,a: os.path.isdir(a[0]), static=True)
        self._sm(cDir, 'list(_)', lambda r,a: os.listdir(a[0]) if os.path.exists(a[0]) else [], static=True)

        def file_write_bytes(r, a):
            if not isinstance(r, WrenFile): return None
            data = a[0].encode('utf-8') if isinstance(a[0], str) else a[0]
            r.fp.write(data)
            r.fp.flush()
            return float(len(data))

        def file_read_bytes(r, a):
            if not isinstance(r, WrenFile): return ''
            cnt = int(a[0])
            data = r.fp.read(cnt)
            return data.decode('utf-8', errors='ignore')

        self._sm(cFile, 'writeBytes(_)', file_write_bytes)
        self._sm(cFile, 'writeBytes(_,_)', lambda r,a: file_write_bytes(r, [a[0]]))
        self._sm(cFile, 'readBytes(_)', file_read_bytes)
        self._sm(cFile, 'readBytes(_,_)', lambda r,a: file_read_bytes(r, [a[0]]))

        self._sm(cStat, 'path(_)', file_stat, static=True)
        self._sm(cStat, 'isFolder', lambda r,a=None: bool(r.is_dir))
        self._sm(cStat, 'isFile', lambda r,a=None: bool(r.is_file))
        self._sm(cStat, 'size', lambda r,a=None: r.size)
        self._sm(cStat, 'device', lambda r,a=None: r.device)
        self._sm(cStat, 'inode', lambda r,a=None: r.inode)
        self._sm(cStat, 'mode', lambda r,a=None: r.mode)
        self._sm(cStat, 'linkCount', lambda r,a=None: r.link_count)
        self._sm(cStat, 'user', lambda r,a=None: r.user)
        self._sm(cStat, 'group', lambda r,a=None: r.group)
        self._sm(cStat, 'specialDevice', lambda r,a=None: r.special_device)
        self._sm(cStat, 'blockSize', lambda r,a=None: r.block_size)
        self._sm(cStat, 'blocks', lambda r,a=None: r.blocks)
        self._sm(cStat, 'isDevice', lambda r,a=None: r.is_device)
        self._sm(cStat, 'isFifo', lambda r,a=None: r.is_fifo)
        self._sm(cStat, 'isSocket', lambda r,a=None: r.is_socket)
        self._sm(cStat, 'isSpecial', lambda r,a=None: r.is_special)

        self._sm(cStdin, 'isRaw', lambda r,a=None: False, static=True)
        self._sm(cStdin, 'isRaw=(_)', lambda r,a: None, static=True)
        self._sm(cStdin, 'readByte', lambda r,a=None: float(ord(sys.stdin.read(1))) if sys.stdin else -1.0, static=True)
        self._sm(cStdout, 'flush()', lambda r,a=None: sys.stdout.flush(), static=True)

        mod_io.define('File', cFile)
        mod_io.define('Directory', cDir)
        mod_io.define('Stat', cStat)
        mod_io.define('Stdin', cStdin)
        mod_io.define('Stdout', cStdout)
        self._modules['io'] = mod_io

    # ============================================================= helpers
    def _rt(self,msg): raise WrenRuntimeError(msg)

    def _str(self,val):
        if val is None:           return 'null'
        if val is True:           return 'true'
        if val is False:          return 'false'
        if isinstance(val,float): return _num_str(val)
        if isinstance(val,str):   return val
        if isinstance(val,list):  return '['+', '.join(self._str(x) for x in val)+']'
        if isinstance(val,dict):  return '{'+', '.join(self._str(k)+': '+self._str(v) for k,v in val.items())+'}'
        if isinstance(val,WrenRange): return repr(val)
        if isinstance(val,WrenSeq):   return repr(val)
        if isinstance(val,WrenMapEntry): return repr(val)
        if isinstance(val,WrenFileStat): return repr(val)
        if isinstance(val,WrenFiber): return '(fiber)'
        if isinstance(val,WrenFn):    return '(fn)'
        if isinstance(val,WrenClass): return val.name
        if isinstance(val,WrenInstance):
            m=val.klass.find_method('toString')
            if m is not None:
                try:
                    if callable(m) and not isinstance(m,WrenMethod): return str(m(val,[]))
                    if isinstance(m,WrenMethod): return str(self._invoke(val,m,[]))
                except: pass
            return f'instance of {val.klass.name}'
        return str(val)

    def _typeof(self,val):
        if val is None:           return self.cNull
        if isinstance(val,bool):  return self.cBool
        if isinstance(val,float): return self.cNum
        if isinstance(val,str):   return self.cString
        if isinstance(val,list):  return self.cList
        if isinstance(val,dict):  return self.cMap
        if isinstance(val,WrenRange):    return self.cRange
        if isinstance(val,WrenSeq):      return val.klass
        if isinstance(val,WrenMapEntry): return val.klass
        if isinstance(val,WrenFileStat): return val.klass
        if isinstance(val,WrenFile):     return val.klass
        if isinstance(val,WrenFn):       return self.cFn
        if isinstance(val,WrenFiber):    return self.cFiber
        if isinstance(val,WrenClass):    return self.cClass
        if isinstance(val,WrenInstance): return val.klass
        return self.cObject

    def _is_truthy(self,v): return v is not None and v is not False

    def _is_instance(self,val,cls):
        if not isinstance(cls,WrenClass): return False
        cur=self._typeof(val)
        while cur:
            if cur is cls: return True
            cur=cur.superclass
        return False

    def _call_fn(self,fn,args):
        if not isinstance(fn,WrenFn): self._rt('Cannot call a non-function.')
        env=Env(fn.closure)
        for i,p in enumerate(fn.params or []):
            env.define(p, args[i] if i<len(args) else None)
        try:
            res = self._exec_block(fn.body,env)
            return res if res is not None else None
        except _Return as r:
            return r.value

    def _invoke(self,recv,m,args,block_fn=None):
        env=Env(m.closure)
        env.define('this',recv)
        # super should be the superclass of the class that DEFINES this method
        if m.klass and m.klass.superclass:
            sup_cls = m.klass.superclass
        elif isinstance(recv, WrenInstance):
            sup_cls = recv.klass.superclass
        else:
            sup_cls = None
        env.define('super', sup_cls)
        for i,p in enumerate(m.params or []):
            env.define(p, args[i] if i<len(args) else None)
        if block_fn is not None and m.params and len(m.params)>len(args):
            env.define(m.params[len(args)],block_fn)
        try:
            return self._exec_block(m.body,env)
        except _Return as r:
            return r.value

    def _sig(self,name,args,block_fn=None):
        n=len(args)+(1 if block_fn is not None else 0)
        if n==0: return name
        return name+'('+ ','.join(['_']*n)+')'

    def _dispatch(self,recv,name,args,block_fn=None):
        if block_fn is not None and block_fn not in args:
            args = list(args) + [block_fn]
        sig=self._sig(name,args)
        if isinstance(recv,WrenClass):
            m=(self._find_sm(recv,sig) or self._find_sm(recv,name) or self._find_sm_arity(recv,name,len(args)) or
               self._find_m(self.cClass,sig) or self._find_m(self.cClass,name) or
               self._find_m(self.cObject,sig) or self._find_m(self.cObject,name))
            if m is None: self._rt(f'{recv.name} does not implement \'{sig}\'')
            if callable(m) and not isinstance(m,WrenMethod): return m(recv,args)
            if isinstance(m,WrenMethod): return self._invoke(recv,m,args)
        else:
            cls=self._typeof(recv)
            m=(self._find_m(cls,sig) or self._find_m(cls,name+'()') or self._find_m(cls,name) or self._find_m_arity(cls,name,len(args)))
            if m is None:
                m=(self._find_m(self.cObject,sig) or self._find_m(self.cObject,name+'()') or self._find_m(self.cObject,name) or
                   self._find_m_arity(self.cObject,name,len(args)))
            if m is None: self._rt(f'{self._str(recv)} does not implement \'{sig}\'')
            if callable(m) and not isinstance(m,WrenMethod):
                return m(recv,args)
            if isinstance(m,WrenMethod): return self._invoke(recv,m,args)
        self._rt(f'Method not found: {sig}')

    def _find_m(self,cls,sig):
        if cls is None: return None
        return cls.find_method(sig)

    def _find_sm(self,cls,sig):
        if cls is None: return None
        return cls.find_static(sig)

    def _find_m_arity(self,cls,name,n):
        if cls is None: return None
        suf='('+ ','.join(['_']*n)+')'
        m=cls.find_method(name+suf)
        if m: return m
        return cls.find_method(name)

    def _find_sm_arity(self,cls,name,n):
        if cls is None: return None
        suf='('+ ','.join(['_']*n)+')'
        m=cls.find_static(name+suf)
        if m: return m
        return cls.find_static(name)

    # ============================================================= execution
    def run(self,source):
        try:
            tokens=Lexer(source,self.module).tokenize()
            program=Parser(tokens,self.module).parse()
        except WrenCompileError as e:
            sys.stderr.write(str(e)+'\n'); sys.exit(EXIT_COMPILE_ERROR)
        try:
            self._run_program(program)
        except WrenRuntimeError as e:
            sys.stderr.write(str(e)+'\n'); sys.exit(EXIT_RUNTIME_ERROR)
        except SystemExit as e:
            sys.exit(e.code)
        sys.exit(self._exit_code)

    def _run_program(self,prog):
        for stmt in prog.stmts:
            self._exec(stmt,self.globals)

    def _exec_block(self,block,env):
        if not isinstance(block,Block): return self._exec(block,env)
        result=None
        for stmt in block.stmts:
            result=self._exec(stmt,env)
        return result

    def _exec(self,node,env):
        if isinstance(node,VarDecl):
            v=self._eval(node.init,env) if node.init else None
            env.define(node.name,v); return v

        if isinstance(node,ClassDecl):
            return self._exec_class(node,env)

        if isinstance(node,ImportStmt):
            return self._exec_import(node,env)

        if isinstance(node,IfStmt):
            c=self._eval(node.cond,env)
            if self._is_truthy(c): return self._exec(node.then_br,env)
            if node.else_br:       return self._exec(node.else_br,env)
            return None

        if isinstance(node,WhileStmt):
            result=None
            while self._is_truthy(self._eval(node.cond,env)):
                try: result=self._exec(node.body,env)
                except _Break: break
                except _Continue: continue
            return result

        if isinstance(node,ForStmt):
            seq=self._eval(node.iter_expr,env)
            items=self._to_iter(seq); result=None
            for item in items:
                le=Env(env); le.define(node.var,item)
                try: result=self._exec(node.body,le)
                except _Break: break
                except _Continue: continue
            return result

        if isinstance(node,BreakStmt):    raise _Break()
        if isinstance(node,ContinueStmt): raise _Continue()
        if isinstance(node,ReturnStmt):
            v=self._eval(node.value,env) if node.value else None; raise _Return(v)
        if isinstance(node,Block):
            return self._exec_block(node,Env(env))
        if isinstance(node,ExprStmt):
            return self._eval(node.expr,env)
        return None

    def _exec_class(self,node,env):
        sup=None
        if node.super_expr:
            sup=self._eval(node.super_expr,env)
            if not isinstance(sup,WrenClass): self._rt('Superclass must be a class.')
        existing=env.get(node.name)
        if existing is not _UNDEF and existing is not None:
            raise WrenCompileError(
                f'[{self.module} line {node.line}] Error at "{node.name}": Module variable is already defined.',
                self.module, node.line)
        cls=WrenClass(node.name, sup or self.cObject)
        env.define(node.name,cls)
        for meth in node.methods:
            self._define_method(cls,meth,env)
        return cls

    def _define_method(self,cls,meth,env):
        if meth.is_foreign or meth.body is None: return
        m=WrenMethod(meth.name,meth.params,meth.body,env,meth.is_construct,klass=cls)
        I=self

        if meth.is_construct:
            def make_ctor(klass,method):
                def ctor(recv,args):
                    inst=WrenInstance(klass)
                    me=Env(method.closure)
                    me.define('this',inst); me.define('super',klass.superclass)
                    for i,p in enumerate(method.params or []):
                        me.define(p, args[i] if i<len(args) else None)
                    try: I._exec_block(method.body,me)
                    except _Return: pass
                    return inst
                return ctor
            fn=make_ctor(cls,m)
            sig=self._method_sig(meth)
            cls.static_methods[sig]=fn
            if meth.name=='new': cls.static_methods['new']=fn
        elif meth.is_static:
            sig=self._method_sig(meth)
            cls.static_methods[sig]=m
        else:
            sig=self._method_sig(meth)
            cls.methods[sig]=m

    def _method_sig(self,meth):
        name=meth.name; params=meth.params
        if params is None: return name
        if not params: return name+'()'
        return name+'('+ ','.join(['_']*len(params))+')'

    def _exec_import(self,node,env):
        path=node.path
        if path in self._modules:
            mod_env = self._modules[path]
        else:
            resolved=self._resolve(path)
            if resolved in self._modules:
                mod_env=self._modules[resolved]
            else:
                actual=resolved
                if not os.path.exists(actual):
                    actual=resolved+'.wren'
                    if not os.path.exists(actual):
                        self._rt(f"Could not find module '{path}'.")
                with open(actual,'r',encoding='utf-8') as f: src=f.read()
                mod=Interpreter(module=path, cwd=os.path.dirname(os.path.abspath(actual)))
                mod._modules=self._modules
                mod_env=mod.globals
                self._modules[resolved]=mod_env
                self._modules[path]=mod_env
                try:
                    toks=Lexer(src,path).tokenize()
                    prog=Parser(toks,path).parse()
                    try:
                        mod._run_program(prog)
                    except _Return: pass
                except WrenCompileError as e:
                    sys.stderr.write(str(e)+'\n'); sys.exit(EXIT_COMPILE_ERROR)

        if node.names:
            for orig,alias in node.names:
                v=mod_env.get(orig)
                if v is _UNDEF: self._rt(f"Module '{path}' does not export '{orig}'.")
                env.define(alias,v)
        return None

    def _resolve(self,path):
        if path.startswith('./') or path.startswith('../'):
            return os.path.normpath(os.path.join(self.cwd,path))
        # For named packages, look for wren_modules/ going up the tree
        parts = path.split('/')
        # Walk from cwd up to root looking for wren_modules/<package>
        check = self.cwd
        for _ in range(20):
            candidate = os.path.join(check, 'wren_modules', path)
            if os.path.exists(candidate) or os.path.exists(candidate+'.wren'):
                return os.path.normpath(candidate)
            parent = os.path.dirname(check)
            if parent == check: break
            check = parent
        return os.path.normpath(os.path.join(self.cwd, path))

    def _to_iter(self,val):
        if isinstance(val,list):      return val
        if isinstance(val,WrenRange): return [float(x) for x in val.seq()]
        if isinstance(val,str):       return list(val)
        if isinstance(val,dict):      return list(val.keys())
        if isinstance(val,WrenSeq):   return val.items
        if isinstance(val,WrenFiber):
            results=[]
            while not val.done:
                v=self._fiber_call(val,None)
                if not val.done: results.append(v)
            return results
        return []

    def _eval(self,node,env):
        if node is None: return None
        if isinstance(node,Literal):      return node.value
        if isinstance(node,StringInterp): return self._eval_interp(node,env)
        if isinstance(node,TernaryExpr):
            c = self._eval(node.cond, env)
            return self._eval(node.then_br, env) if self._is_truthy(c) else self._eval(node.else_br, env)
        if isinstance(node,NameExpr):
            v=env.get(node.name)
            if v is _UNDEF:
                th = env.get('this')
                if isinstance(th, WrenInstance):
                    m = th.klass.find_method(node.name) or th.klass.find_method(node.name + '()')
                    if m:
                        return self._dispatch(th, node.name, [])
                self._rt(f"Undefined variable '{node.name}'.")
            return v
        if isinstance(node,FieldGet):
            if node.name.startswith('__'):
                cls = env.get('this')
                if isinstance(cls, WrenInstance): cls = cls.klass
                if isinstance(cls, WrenClass):
                    return cls.static_fields.get(node.name)
                self._rt('Cannot access static field outside class.')
            recv=env.get('this')
            if recv is _UNDEF or not isinstance(recv,WrenInstance):
                self._rt('Cannot access field outside of a class.')
            return recv.fields.get(node.name)
        if isinstance(node,FieldSet):
            if node.name.startswith('__'):
                cls = env.get('this')
                if isinstance(cls, WrenInstance): cls = cls.klass
                if isinstance(cls, WrenClass):
                    v=self._eval(node.value,env)
                    if node.op!='=':
                        old=cls.static_fields.get(node.name)
                        v=self._apply_compound(node.op,old,v)
                    cls.static_fields[node.name]=v; return v
                self._rt('Cannot access static field outside class.')
            recv=env.get('this')
            if not isinstance(recv,WrenInstance): self._rt('Cannot set field outside class.')
            v=self._eval(node.value,env)
            if node.op!='=':
                old=recv.fields.get(node.name); v=self._apply_compound(node.op,old,v)
            recv.fields[node.name]=v; return v
        if isinstance(node,ThisExpr):
            v=env.get('this'); return v if v is not _UNDEF else None
        if isinstance(node,SuperExpr):
            return self._eval_super(node,env)
        if isinstance(node,ListExpr):
            return [self._eval(x,env) for x in node.items]
        if isinstance(node,MapExpr):
            d={}
            for k,v in node.pairs: d[self._eval(k,env)]=self._eval(v,env)
            return d
        if isinstance(node,FnExpr):
            return WrenFn(node.params,node.body,env)
        if isinstance(node,RangeExpr):
            s=self._eval(node.start,env); e=self._eval(node.end,env)
            return WrenRange(s,e,node.inclusive)
        if isinstance(node,IsExpr):
            obj=self._eval(node.obj,env); cls=self._eval(node.cls,env)
            return self._is_instance(obj,cls)
        if isinstance(node,BinOp):
            return self._eval_binop(node,env)
        if isinstance(node,UnOp):
            return self._eval_unop(node,env)
        if isinstance(node,Assign):
            return self._eval_assign(node,env)
        if isinstance(node,SetAttr):
            return self._eval_setattr(node,env)
        if isinstance(node,GetAttr):
            obj=self._eval(node.obj,env); return self._dispatch(obj,node.name,[])
        if isinstance(node,CallMethod):
            obj=self._eval(node.obj,env)
            args=[self._eval(a,env) for a in node.args]
            bfn=WrenFn(node.bp or [],node.bb,env) if node.bb else None
            return self._dispatch(obj,node.name,args,bfn)
        if isinstance(node,Call):
            return self._eval_call(node,env)
        if isinstance(node,Subscript):
            obj=self._eval(node.obj,env)
            idx=self._eval(node.idx,env) if not isinstance(node.idx,tuple) else tuple(self._eval(i,env) for i in node.idx)
            if isinstance(idx,tuple):
                return self._dispatch(obj,'[]',list(idx))
            return self._dispatch(obj,'[]',[idx])
        if isinstance(node,SubscriptSet):
            obj=self._eval(node.obj,env)
            idx=self._eval(node.idx,env) if not isinstance(node.idx,tuple) else tuple(self._eval(i,env) for i in node.idx)
            v=self._eval(node.value,env)
            if isinstance(idx,tuple):
                return self._dispatch(obj,'[]=',list(idx)+[v])
            return self._dispatch(obj,'[]=',[idx,v])
        if isinstance(node,Block):
            return self._exec_block(node,Env(env))
        self._rt(f'Unknown node: {type(node).__name__}')

    def _eval_interp(self,node,env):
        r=''
        for p in node.parts:
            r+=(p if isinstance(p,str) else self._str(self._eval(p,env)))
        return r

    def _eval_binop(self,node,env):
        op=node.op
        if op=='&&':
            l=self._eval(node.left,env)
            return l if not self._is_truthy(l) else self._eval(node.right,env)
        if op=='||':
            l=self._eval(node.left,env)
            return l if self._is_truthy(l) else self._eval(node.right,env)
        l=self._eval(node.left,env); r=self._eval(node.right,env)
        return self._dispatch(l,op,[r])

    def _eval_unop(self,node,env):
        v=self._eval(node.operand,env)
        if node.op=='-' and isinstance(v,float): return -v
        return self._dispatch(v,node.op,[])

    def _eval_assign(self,node,env):
        v=self._eval(node.value,env)
        tgt=node.target
        if isinstance(tgt,NameExpr):
            name=tgt.name
            if node.op!='=':
                old=env.get(name)
                if old is _UNDEF:
                    th = env.get('this')
                    if isinstance(th, WrenInstance) and th.klass.find_method(name):
                        old = self._dispatch(th, name, [])
                    else:
                        self._rt(f"Undefined variable '{name}'.")
                v=self._apply_compound(node.op,old,v)
            if not env.set(name,v):
                th = env.get('this')
                if isinstance(th, WrenInstance):
                    sig_set = self._sig(name+'=', [v])
                    if th.klass.find_method(sig_set) or th.klass.find_method(name+'='):
                        return self._dispatch(th, name+'=', [v])
                self._rt(f"Undefined variable '{name}'.")
            return v
        self._rt('Invalid assignment target.')

    def _eval_setattr(self,node,env):
        obj=self._eval(node.obj,env); v=self._eval(node.value,env)
        if node.op!='=':
            old=self._dispatch(obj,node.name,[])
            v=self._apply_compound(node.op,old,v)
        return self._dispatch(obj,node.name+'=',[v])

    def _eval_call(self,node,env):
        args=[self._eval(a,env) for a in node.args]
        bfn=WrenFn(node.bp or [],node.bb,env) if node.bb else None
        if isinstance(node.callee, NameExpr):
            v = env.get(node.callee.name)
            if v is _UNDEF:
                th = env.get('this')
                if isinstance(th, WrenInstance):
                    return self._dispatch(th, node.callee.name, args, bfn)
            callee = v
        else:
            callee=self._eval(node.callee,env)
        if isinstance(callee,WrenFn):
            if bfn: args.append(bfn)
            return self._call_fn(callee,args)
        if isinstance(callee,WrenClass):
            if bfn: args.append(bfn)
            sig=self._sig('new',args)
            m=(self._find_sm(callee,sig) or self._find_sm(callee,'new') or
               self._find_sm_arity(callee,'new',len(args)))
            if m is None: self._rt(f"{callee.name} does not implement '{sig}'.")
            if callable(m) and not isinstance(m,WrenMethod): return m(callee,args)
            if isinstance(m,WrenMethod): return self._invoke(callee,m,args)
        self._rt(f'Cannot call non-function value.')

    def _eval_super(self,node,env):
        recv=env.get('this')
        sup=env.get('super')
        # sup should be a WrenClass (the superclass of the defining class)
        if not isinstance(sup, WrenClass):
            cls=self._typeof(recv)
            sup=cls.superclass if cls else None
        name=node.method or 'new'
        args=[self._eval(a,env) for a in node.args]
        bfn=WrenFn(node.bp or [],node.bb,env) if node.bb else None
        if bfn: args.append(bfn)
        if sup:
            sig=self._sig(name,args)
            m=(sup.find_method(sig) or sup.find_method(name) or
               self._find_m_arity(sup,name,len(args)))
            if m is None:
                # also search static
                m=(sup.find_static(sig) or sup.find_static(name) or
                   self._find_sm_arity(sup,name,len(args)))
            if m:
                if callable(m) and not isinstance(m,WrenMethod): return m(recv,args)
                if isinstance(m,WrenMethod):
                    # For super calls, we must set sup relative to m.klass, not recv.klass
                    env2=Env(m.closure)
                    env2.define('this',recv)
                    env2.define('super', m.klass.superclass if m.klass else None)
                    for i,p in enumerate(m.params or []):
                        env2.define(p, args[i] if i<len(args) else None)
                    try:
                        return self._exec_block(m.body,env2)
                    except _Return as r:
                        return r.value
        self._rt(f'Super method not found: {name}')

    def _apply_compound(self,op,old,val):
        base=op[:-1]
        return self._dispatch(old,base,[val])

    def _resume_fiber_fully(self, fiber):
        """Resume a fiber until it's done. For threaded fibers, run until done or yielding on sleep."""
        while not fiber.done:
            try:
                self._fiber_call(fiber, None)
                # If fiber yielded (not done), it may be sleeping
                if not fiber.done and hasattr(fiber, '_sleep_until'):
                    wake = fiber._sleep_until
                    del fiber._sleep_until
                    self._sched_counter += 1
                    self._sched_queue.append((wake, self._sched_counter, fiber))
                    break
            except WrenRuntimeError:
                break

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv)<2:
        sys.stderr.write('Usage: wren <file>\n'); sys.exit(1)
    filepath=sys.argv[1]
    try:
        with open(filepath,'r',encoding='utf-8') as f: source=f.read()
    except FileNotFoundError:
        sys.stderr.write(f'File not found: {filepath}\n'); sys.exit(1)
    cwd=os.path.dirname(os.path.abspath(filepath))
    interp=Interpreter(module=filepath, cwd=cwd)
    interp.run(source)

if __name__=='__main__':
    main()
