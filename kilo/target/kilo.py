#!/usr/bin/env python3
"""
Kilo - A simple text editor in Python.
Ported from the C reference implementation (kilo.c) by Salvatore Sanfilippo.
Supports POSIX (Linux, macOS, WSL) and Windows.
"""

import sys
import os
import time
import signal

# Try loading termios and tty for POSIX systems
try:
    import termios
    import tty
    import fcntl
    import struct
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False

# Enable Windows VT100 escape sequence processing and msvcrt key reading if on Windows
if sys.platform == 'win32':
    import msvcrt
    import ctypes

    def enable_vt100_windows():
        try:
            kernel32 = ctypes.windll.kernel32
            h_out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_out, ctypes.byref(mode)):
                kernel32.SetConsoleMode(h_out, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass

    enable_vt100_windows()


KILO_VERSION = "0.0.1"
KILO_QUIT_TIMES = 3

# Syntax highlight types
HL_NORMAL = 0
HL_NONPRINT = 1
HL_COMMENT = 2      # Single line comment
HL_MLCOMMENT = 3    # Multi-line comment
HL_KEYWORD1 = 4
HL_KEYWORD2 = 5
HL_STRING = 6
HL_NUMBER = 7
HL_MATCH = 8        # Search match

HL_HIGHLIGHT_STRINGS = (1 << 0)
HL_HIGHLIGHT_NUMBERS = (1 << 1)

# Key actions
KEY_NULL = 0
CTRL_C = 3
CTRL_D = 4
CTRL_F = 6
CTRL_H = 8
TAB = 9
CTRL_L = 12
ENTER = 13
CTRL_Q = 17
CTRL_S = 19
CTRL_U = 21
ESC = 27
BACKSPACE = 127

ARROW_LEFT = 1000
ARROW_RIGHT = 1001
ARROW_UP = 1002
ARROW_DOWN = 1003
DEL_KEY = 1004
HOME_KEY = 1005
END_KEY = 1006
PAGE_UP = 1007
PAGE_DOWN = 1008


class EditorSyntax:
    def __init__(self, filematch, keywords, singleline_comment_start, multiline_comment_start, multiline_comment_end, flags):
        self.filematch = filematch
        self.keywords = keywords
        self.singleline_comment_start = singleline_comment_start
        self.multiline_comment_start = multiline_comment_start
        self.multiline_comment_end = multiline_comment_end
        self.flags = flags


C_HL_extensions = [".c", ".h", ".cpp", ".hpp", ".cc"]
C_HL_keywords = [
    # C Keywords
    "auto", "break", "case", "continue", "default", "do", "else", "enum",
    "extern", "for", "goto", "if", "register", "return", "sizeof", "static",
    "struct", "switch", "typedef", "union", "volatile", "while", "NULL",
    # C++ Keywords
    "alignas", "alignof", "and", "and_eq", "asm", "bitand", "bitor", "class",
    "compl", "constexpr", "const_cast", "deltype", "delete", "dynamic_cast",
    "explicit", "export", "false", "friend", "inline", "mutable", "namespace",
    "new", "noexcept", "not", "not_eq", "nullptr", "operator", "or", "or_eq",
    "private", "protected", "public", "reinterpret_cast", "static_assert",
    "static_cast", "template", "this", "thread_local", "throw", "true", "try",
    "typeid", "typename", "virtual", "xor", "xor_eq",
    # C types
    "int|", "long|", "double|", "float|", "char|", "unsigned|", "signed|",
    "void|", "short|", "auto|", "const|", "bool|"
]

HLDB = [
    EditorSyntax(
        C_HL_extensions,
        C_HL_keywords,
        "//", "/*", "*/",
        HL_HIGHLIGHT_STRINGS | HL_HIGHLIGHT_NUMBERS
    )
]


class EditorRow:
    def __init__(self, idx=0, chars=""):
        self.idx = idx
        self.chars = chars
        self.render = ""
        self.hl = []
        self.hl_oc = False

    @property
    def size(self):
        return len(self.chars)

    @property
    def rsize(self):
        return len(self.render)


class EditorConfig:
    def __init__(self):
        self.cx = 0
        self.cy = 0
        self.rowoff = 0
        self.coloff = 0
        self.screenrows = 0
        self.screencols = 0
        self.numrows = 0
        self.rawmode = False
        self.row = []
        self.dirty = 0
        self.filename = None
        self.statusmsg = ""
        self.statusmsg_time = 0
        self.syntax = None
        self.orig_termios = None


E = EditorConfig()


# --- Low level terminal handling ---

def disable_raw_mode(fd=0):
    if E.rawmode and HAS_TERMIOS and E.orig_termios:
        termios.tcsetattr(fd, termios.TCSAFLUSH, E.orig_termios)
        E.rawmode = False


def editor_at_exit():
    disable_raw_mode(0)


def enable_raw_mode(fd=0):
    if E.rawmode:
        return 0
    if not HAS_TERMIOS or not os.isatty(fd):
        return -1

    E.orig_termios = termios.tcgetattr(fd)
    raw = termios.tcgetattr(fd)

    raw[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
    raw[1] &= ~(termios.OPOST)
    raw[2] |= (termios.CS8)
    raw[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)

    raw[6][termios.VMIN] = 0
    raw[6][termios.VTIME] = 1

    termios.tcsetattr(fd, termios.TCSAFLUSH, raw)
    E.rawmode = True
    return 0


def editor_read_key(fd=0):
    if sys.platform == 'win32':
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'):
            ch2 = msvcrt.getch()
            code = ch2[0]
            if code == 72:     # Up
                return ARROW_UP
            elif code == 80:   # Down
                return ARROW_DOWN
            elif code == 75:   # Left
                return ARROW_LEFT
            elif code == 77:   # Right
                return ARROW_RIGHT
            elif code == 83:   # Delete
                return DEL_KEY
            elif code == 71:   # Home
                return HOME_KEY
            elif code == 79:   # End
                return END_KEY
            elif code == 73:   # Page Up
                return PAGE_UP
            elif code == 81:   # Page Down
                return PAGE_DOWN
            return ESC
        else:
            byte_val = ch[0]
            if byte_val == 13:
                return ENTER
            elif byte_val == 8:
                return BACKSPACE
            return byte_val

    while True:
        try:
            c = os.read(fd, 1)
            if not c:
                continue
            ch = c[0]
        except OSError:
            sys.exit(1)

        if ch == ESC:
            # Check for escape sequences
            try:
                seq0 = os.read(fd, 1)
                if not seq0:
                    return ESC
                seq1 = os.read(fd, 1)
                if not seq1:
                    return ESC
            except OSError:
                return ESC

            s0 = chr(seq0[0])
            s1 = chr(seq1[0])

            if s0 == '[':
                if '0' <= s1 <= '9':
                    try:
                        seq2 = os.read(fd, 1)
                        if not seq2:
                            return ESC
                    except OSError:
                        return ESC
                    s2 = chr(seq2[0])
                    if s2 == '~':
                        if s1 == '3':
                            return DEL_KEY
                        elif s1 == '5':
                            return PAGE_UP
                        elif s1 == '6':
                            return PAGE_DOWN
                else:
                    if s1 == 'A':
                        return ARROW_UP
                    elif s1 == 'B':
                        return ARROW_DOWN
                    elif s1 == 'C':
                        return ARROW_RIGHT
                    elif s1 == 'D':
                        return ARROW_LEFT
                    elif s1 == 'H':
                        return HOME_KEY
                    elif s1 == 'F':
                        return END_KEY
            elif s0 == 'O':
                if s1 == 'H':
                    return HOME_KEY
                elif s1 == 'F':
                    return END_KEY
            return ESC
        else:
            return ch


def get_cursor_position(ifd=0, ofd=1):
    try:
        os.write(ofd, b"\x1b[6n")
    except OSError:
        return -1, -1

    buf = ""
    while len(buf) < 32:
        try:
            c = os.read(ifd, 1)
            if not c:
                break
            ch = chr(c[0])
            buf += ch
            if ch == 'R':
                break
        except OSError:
            break

    if not buf.startswith("\x1b[") or not buf.endswith("R"):
        return -1, -1

    try:
        parts = buf[2:-1].split(";")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return -1, -1


def get_window_size(ifd=0, ofd=1):
    # 1. Try termios ioctl (Unix)
    if HAS_TERMIOS:
        try:
            res = fcntl.ioctl(ofd, termios.TIOCGWINSZ, b'\0' * 8)
            rows, cols, _, _ = struct.unpack('HHHH', res)
            if cols != 0 and rows != 0:
                return rows, cols
        except Exception:
            pass

    # 2. Try os.get_terminal_size() (Cross-platform Python 3.3+)
    try:
        size = os.get_terminal_size()
        if size.columns != 0 and size.lines != 0:
            return size.lines, size.columns
    except Exception:
        pass

    # 3. Fallback to querying terminal directly via escape sequence
    orig_row, orig_col = get_cursor_position(ifd, ofd)
    if orig_row != -1:
        try:
            os.write(ofd, b"\x1b[999C\x1b[999B")
            rows, cols = get_cursor_position(ifd, ofd)
            seq = f"\x1b[{orig_row};{orig_col}H".encode('latin1')
            os.write(ofd, seq)
            if rows != -1 and cols != -1:
                return rows, cols
        except Exception:
            pass

    # 4. Default fallback
    return 24, 80


# --- Syntax Highlighting ---

def is_separator(c):
    if c is None or c == '\0':
        return True
    if c.isspace():
        return True
    return c in ",.()+-/*=~%[];"


def editor_row_has_open_comment(row):
    if row.hl and row.rsize > 0 and row.hl[-1] == HL_MLCOMMENT:
        if row.rsize < 2 or row.render[-2:] != "*/":
            return True
    return False


def editor_update_syntax(row):
    row.hl = [HL_NORMAL] * row.rsize

    if E.syntax is None:
        return

    keywords = E.syntax.keywords
    scs = E.syntax.singleline_comment_start
    mcs = E.syntax.multiline_comment_start
    mce = E.syntax.multiline_comment_end

    p = row.render
    i = 0

    prev_sep = True
    in_string = None
    in_comment = False

    if row.idx > 0 and editor_row_has_open_comment(E.row[row.idx - 1]):
        in_comment = True

    while i < len(p):
        ch = p[i]
        prev_hl = row.hl[i - 1] if i > 0 else HL_NORMAL

        # Handle // comments
        if prev_sep and scs and p[i:i + len(scs)] == scs:
            for j in range(i, len(p)):
                row.hl[j] = HL_COMMENT
            return

        # Handle multi line comments
        if in_comment:
            row.hl[i] = HL_MLCOMMENT
            if mce and p[i:i + len(mce)] == mce:
                for k in range(len(mce)):
                    if i + k < len(p):
                        row.hl[i + k] = HL_MLCOMMENT
                i += len(mce)
                in_comment = False
                prev_sep = True
                continue
            else:
                prev_sep = False
                i += 1
                continue
        elif mcs and p[i:i + len(mcs)] == mcs:
            for k in range(len(mcs)):
                if i + k < len(p):
                    row.hl[i + k] = HL_MLCOMMENT
            i += len(mcs)
            in_comment = True
            prev_sep = False
            continue

        # Handle "" and ''
        if in_string:
            row.hl[i] = HL_STRING
            if ch == '\\' and i + 1 < len(p):
                row.hl[i + 1] = HL_STRING
                i += 2
                prev_sep = False
                continue
            if ch == in_string:
                in_string = None
            i += 1
            prev_sep = False
            continue
        else:
            if ch in ('"', "'"):
                in_string = ch
                row.hl[i] = HL_STRING
                i += 1
                prev_sep = False
                continue

        # Handle non printable chars
        if not (32 <= ord(ch) <= 126):
            row.hl[i] = HL_NONPRINT
            i += 1
            prev_sep = False
            continue

        # Handle numbers
        if (ch.isdigit() and (prev_sep or prev_hl == HL_NUMBER)) or (ch == '.' and i > 0 and prev_hl == HL_NUMBER):
            row.hl[i] = HL_NUMBER
            i += 1
            prev_sep = False
            continue

        # Handle keywords
        if prev_sep and keywords:
            kw_match = False
            for kw in keywords:
                kw2 = kw.endswith('|')
                klen = len(kw) - 1 if kw2 else len(kw)
                if p[i:i + klen] == kw[:klen]:
                    next_char = p[i + klen] if (i + klen) < len(p) else '\0'
                    if is_separator(next_char):
                        hl_type = HL_KEYWORD2 if kw2 else HL_KEYWORD1
                        for k in range(klen):
                            row.hl[i + k] = hl_type
                        i += klen
                        kw_match = True
                        break
            if kw_match:
                prev_sep = False
                continue

        prev_sep = is_separator(ch)
        i += 1

    oc = editor_row_has_open_comment(row)
    if row.hl_oc != oc and row.idx + 1 < E.numrows:
        editor_update_syntax(E.row[row.idx + 1])
    row.hl_oc = oc


def editor_syntax_to_color(hl):
    if hl in (HL_COMMENT, HL_MLCOMMENT):
        return 36  # cyan
    elif hl == HL_KEYWORD1:
        return 33  # yellow
    elif hl == HL_KEYWORD2:
        return 32  # green
    elif hl == HL_STRING:
        return 35  # magenta
    elif hl == HL_NUMBER:
        return 31  # red
    elif hl == HL_MATCH:
        return 34  # blue
    else:
        return 37  # white


def editor_select_syntax_highlight(filename):
    if not filename:
        return
    for s in HLDB:
        for pattern in s.filematch:
            if pattern.startswith('.'):
                if filename.endswith(pattern):
                    E.syntax = s
                    return
            else:
                if pattern in filename:
                    E.syntax = s
                    return


# --- Editor rows implementation ---

def editor_update_row(row):
    # Expand tabs
    render_list = []
    idx = 0
    for c in row.chars:
        if c == '\t':
            render_list.append(' ')
            idx += 1
            while idx % 8 != 0:
                render_list.append(' ')
                idx += 1
        else:
            render_list.append(c)
            idx += 1

    row.render = "".join(render_list)
    editor_update_syntax(row)


def editor_insert_row(at, s):
    if at < 0 or at > E.numrows:
        return
    new_row = EditorRow(idx=at, chars=s)
    E.row.insert(at, new_row)
    for j in range(at + 1, len(E.row)):
        E.row[j].idx = j
    editor_update_row(new_row)
    E.numrows += 1
    E.dirty += 1


def editor_del_row(at):
    if at < 0 or at >= E.numrows:
        return
    del E.row[at]
    for j in range(at, len(E.row)):
        E.row[j].idx = j
    E.numrows -= 1
    E.dirty += 1


def editor_rows_to_string():
    lines = [row.chars for row in E.row]
    return "\n".join(lines) + ("\n" if lines else "")


def editor_row_insert_char(row, at, c):
    if at < 0 or at > row.size:
        pad = at - row.size
        row.chars = row.chars + (" " * pad) + chr(c)
    else:
        row.chars = row.chars[:at] + chr(c) + row.chars[at:]
    editor_update_row(row)
    E.dirty += 1


def editor_row_append_string(row, s):
    row.chars += s
    editor_update_row(row)
    E.dirty += 1


def editor_row_del_char(row, at):
    if at < 0 or at >= row.size:
        return
    row.chars = row.chars[:at] + row.chars[at + 1:]
    editor_update_row(row)
    E.dirty += 1


def editor_insert_char(c):
    filerow = E.rowoff + E.cy
    filecol = E.coloff + E.cx

    if filerow >= E.numrows:
        while E.numrows <= filerow:
            editor_insert_row(E.numrows, "")

    row = E.row[filerow]
    editor_row_insert_char(row, filecol, c)
    if E.cx == E.screencols - 1:
        E.coloff += 1
    else:
        E.cx += 1
    E.dirty += 1


def editor_insert_newline():
    filerow = E.rowoff + E.cy
    filecol = E.coloff + E.cx

    if filerow >= E.numrows:
        if filerow == E.numrows:
            editor_insert_row(filerow, "")
            _fix_cursor_after_newline()
        return

    row = E.row[filerow]
    if filecol >= row.size:
        filecol = row.size

    if filecol == 0:
        editor_insert_row(filerow, "")
    else:
        editor_insert_row(filerow + 1, row.chars[filecol:])
        row = E.row[filerow]
        row.chars = row.chars[:filecol]
        editor_update_row(row)

    _fix_cursor_after_newline()


def _fix_cursor_after_newline():
    if E.cy == E.screenrows - 1:
        E.rowoff += 1
    else:
        E.cy += 1
    E.cx = 0
    E.coloff = 0


def editor_del_char():
    filerow = E.rowoff + E.cy
    filecol = E.coloff + E.cx

    if filerow >= E.numrows or (filecol == 0 and filerow == 0):
        return

    row = E.row[filerow]
    if filecol == 0:
        prev_row = E.row[filerow - 1]
        filecol = prev_row.size
        editor_row_append_string(prev_row, row.chars)
        editor_del_row(filerow)
        if E.cy == 0:
            E.rowoff -= 1
        else:
            E.cy -= 1
        E.cx = filecol
        if E.cx >= E.screencols:
            shift = (E.screencols - E.cx) + 1
            E.cx -= shift
            E.coloff += shift
    else:
        editor_row_del_char(row, filecol - 1)
        if E.cx == 0 and E.coloff > 0:
            E.coloff -= 1
        else:
            E.cx -= 1

    if filerow < E.numrows:
        editor_update_row(E.row[filerow if filecol != 0 else filerow - 1])
    E.dirty += 1


def editor_open(filename):
    E.dirty = 0
    E.filename = filename

    if not os.path.exists(filename):
        return 1

    try:
        with open(filename, "r", encoding="latin1") as f:
            for line in f:
                line = line.rstrip("\r\n")
                editor_insert_row(E.numrows, line)
        E.dirty = 0
        return 0
    except OSError:
        sys.exit(1)


def editor_save():
    if not E.filename:
        return 1

    buf = editor_rows_to_string()
    try:
        with open(E.filename, "w", encoding="latin1") as f:
            f.write(buf)
        E.dirty = 0
        editor_set_status_message(f"{len(buf)} bytes written on disk")
        return 0
    except OSError as err:
        editor_set_status_message(f"Can't save! I/O error: {err}")
        return 1


# --- Terminal update ---

def editor_refresh_screen():
    ab = []

    ab.append("\x1b[?25l")  # Hide cursor
    ab.append("\x1b[H")     # Go home

    for y in range(E.screenrows):
        filerow = E.rowoff + y

        if filerow >= E.numrows:
            if E.numrows == 0 and y == E.screenrows // 3:
                welcome = f"Kilo editor -- version {KILO_VERSION}\x1b[0K\r\n"
                welcomelen = len(welcome) - len("\x1b[0K\r\n")
                padding = (E.screencols - welcomelen) // 2
                if padding > 0:
                    ab.append("~")
                    padding -= 1
                ab.append(" " * padding)
                ab.append(welcome)
            else:
                ab.append("~\x1b[0K\r\n")
            continue

        r = E.row[filerow]
        len_render = r.rsize - E.coloff
        current_color = -1

        if len_render > 0:
            if len_render > E.screencols:
                len_render = E.screencols
            c_slice = r.render[E.coloff:E.coloff + len_render]
            hl_slice = r.hl[E.coloff:E.coloff + len_render]

            for j in range(len_render):
                hl = hl_slice[j]
                ch = c_slice[j]
                if hl == HL_NONPRINT:
                    ab.append("\x1b[7m")
                    sym = chr(ord('@') + ord(ch)) if ord(ch) <= 26 else '?'
                    ab.append(sym)
                    ab.append("\x1b[0m")
                elif hl == HL_NORMAL:
                    if current_color != -1:
                        ab.append("\x1b[39m")
                        current_color = -1
                    ab.append(ch)
                else:
                    color = editor_syntax_to_color(hl)
                    if color != current_color:
                        current_color = color
                        ab.append(f"\x1b[{color}m")
                    ab.append(ch)

        ab.append("\x1b[39m")
        ab.append("\x1b[0K")
        ab.append("\r\n")

    # Status bar - Row 1
    ab.append("\x1b[0K")
    ab.append("\x1b[7m")

    fname = E.filename if E.filename else "[No Name]"
    mod_str = "(modified)" if E.dirty else ""
    status = f"{fname[:20]} - {E.numrows} lines {mod_str}"
    rstatus = f"{E.rowoff + E.cy + 1}/{E.numrows}"

    slen = len(status)
    if slen > E.screencols:
        status = status[:E.screencols]
        slen = E.screencols

    ab.append(status)
    while slen < E.screencols:
        if E.screencols - slen == len(rstatus):
            ab.append(rstatus)
            break
        else:
            ab.append(" ")
            slen += 1

    ab.append("\x1b[0m\r\n")

    # Status bar - Row 2
    ab.append("\x1b[0K")
    msglen = len(E.statusmsg)
    if msglen > 0 and (time.time() - E.statusmsg_time) < 5:
        ab.append(E.statusmsg[:E.screencols])

    # Cursor position
    cx = 1
    filerow = E.rowoff + E.cy
    if filerow < E.numrows:
        row = E.row[filerow]
        for j in range(E.coloff, min(E.cx + E.coloff, row.size)):
            if row.chars[j] == '\t':
                cx += 7 - (cx % 8)
            cx += 1

    ab.append(f"\x1b[{E.cy + 1};{cx}H")
    ab.append("\x1b[?25h")  # Show cursor

    buf_str = "".join(ab)
    try:
        sys.stdout.write(buf_str)
        sys.stdout.flush()
    except OSError:
        pass


def editor_set_status_message(msg):
    E.statusmsg = msg
    E.statusmsg_time = time.time()


# --- Find mode ---

def editor_find(fd=0):
    query = ""
    last_match = -1
    find_next = 0
    saved_hl_line = -1
    saved_hl = None

    saved_cx = E.cx
    saved_cy = E.cy
    saved_coloff = E.coloff
    saved_rowoff = E.rowoff

    def restore_hl():
        nonlocal saved_hl_line, saved_hl
        if saved_hl is not None and 0 <= saved_hl_line < E.numrows:
            E.row[saved_hl_line].hl = saved_hl[:]
            saved_hl = None
            saved_hl_line = -1

    while True:
        editor_set_status_message(f"Search: {query} (Use ESC/Arrows/Enter)")
        editor_refresh_screen()

        c = editor_read_key(fd)
        if c in (DEL_KEY, CTRL_H, BACKSPACE):
            if len(query) > 0:
                query = query[:-1]
            last_match = -1
        elif c in (ESC, ENTER):
            if c == ESC:
                E.cx = saved_cx
                E.cy = saved_cy
                E.coloff = saved_coloff
                E.rowoff = saved_rowoff
            restore_hl()
            editor_set_status_message("")
            return
        elif c in (ARROW_RIGHT, ARROW_DOWN):
            find_next = 1
        elif c in (ARROW_LEFT, ARROW_UP):
            find_next = -1
        elif isinstance(c, int) and 32 <= c <= 126:
            query += chr(c)
            last_match = -1

        if last_match == -1:
            find_next = 1

        if find_next and query:
            match_offset = -1
            current = last_match
            for _ in range(E.numrows):
                current += find_next
                if current == -1:
                    current = E.numrows - 1
                elif current == E.numrows:
                    current = 0

                idx = E.row[current].render.find(query)
                if idx != -1:
                    match_offset = idx
                    break

            find_next = 0
            restore_hl()

            if match_offset != -1:
                row = E.row[current]
                last_match = current
                saved_hl_line = current
                saved_hl = row.hl[:]
                for k in range(len(query)):
                    if match_offset + k < len(row.hl):
                        row.hl[match_offset + k] = HL_MATCH

                E.cy = 0
                E.cx = match_offset
                E.rowoff = current
                E.coloff = 0
                if E.cx > E.screencols:
                    diff = E.cx - E.screencols
                    E.cx -= diff
                    E.coloff += diff


# --- Editor events handling ---

def editor_move_cursor(key):
    filerow = E.rowoff + E.cy
    filecol = E.coloff + E.cx
    row = E.row[filerow] if filerow < E.numrows else None

    if key == ARROW_LEFT:
        if E.cx == 0:
            if E.coloff > 0:
                E.coloff -= 1
            else:
                if filerow > 0:
                    E.cy -= 1
                    E.cx = E.row[filerow - 1].size
                    if E.cx > E.screencols - 1:
                        E.coloff = E.cx - E.screencols + 1
                        E.cx = E.screencols - 1
        else:
            E.cx -= 1
    elif key == ARROW_RIGHT:
        if row and filecol < row.size:
            if E.cx == E.screencols - 1:
                E.coloff += 1
            else:
                E.cx += 1
        elif row and filecol == row.size:
            E.cx = 0
            E.coloff = 0
            if E.cy == E.screenrows - 1:
                E.rowoff += 1
            else:
                E.cy += 1
    elif key == ARROW_UP:
        if E.cy == 0:
            if E.rowoff > 0:
                E.rowoff -= 1
        else:
            E.cy -= 1
    elif key == ARROW_DOWN:
        if filerow < E.numrows:
            if E.cy == E.screenrows - 1:
                E.rowoff += 1
            else:
                E.cy += 1

    filerow = E.rowoff + E.cy
    filecol = E.coloff + E.cx
    row = E.row[filerow] if filerow < E.numrows else None
    rowlen = row.size if row else 0
    if filecol > rowlen:
        E.cx -= filecol - rowlen
        if E.cx < 0:
            E.coloff += E.cx
            E.cx = 0


def editor_process_keypress(fd=0):
    if not hasattr(editor_process_keypress, "quit_times"):
        editor_process_keypress.quit_times = KILO_QUIT_TIMES

    c = editor_read_key(fd)

    if c == ENTER:
        editor_insert_newline()
    elif c == CTRL_C:
        pass
    elif c == CTRL_Q:
        if E.dirty and editor_process_keypress.quit_times > 0:
            editor_set_status_message(
                f"WARNING!!! File has unsaved changes. Press Ctrl-Q {editor_process_keypress.quit_times} more times to quit."
            )
            editor_process_keypress.quit_times -= 1
            return
        disable_raw_mode(fd)
        sys.exit(0)
    elif c == CTRL_S:
        editor_save()
    elif c == CTRL_F:
        editor_find(fd)
    elif c in (BACKSPACE, CTRL_H, DEL_KEY):
        editor_del_char()
    elif c in (PAGE_UP, PAGE_DOWN):
        if c == PAGE_UP and E.cy != 0:
            E.cy = 0
        elif c == PAGE_DOWN and E.cy != E.screenrows - 1:
            E.cy = E.screenrows - 1
        times = E.screenrows
        while times > 0:
            editor_move_cursor(ARROW_UP if c == PAGE_UP else ARROW_DOWN)
            times -= 1
    elif c in (ARROW_UP, ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT):
        editor_move_cursor(c)
    elif c == CTRL_L:
        pass
    elif c == ESC:
        pass
    elif isinstance(c, int) and 0 <= c <= 255:
        editor_insert_char(c)

    editor_process_keypress.quit_times = KILO_QUIT_TIMES


def update_window_size():
    rows, cols = get_window_size(0, 1)
    if rows == -1 or cols == -1:
        rows, cols = 24, 80
    E.screenrows = rows - 2  # Room for status bar
    E.screencols = cols


def handle_sigwinch(signum, frame):
    update_window_size()
    if E.cy >= E.screenrows:
        E.cy = E.screenrows - 1
    if E.cx >= E.screencols:
        E.cx = E.screencols - 1
    editor_refresh_screen()


def init_editor():
    E.cx = 0
    E.cy = 0
    E.rowoff = 0
    E.coloff = 0
    E.numrows = 0
    E.row = []
    E.dirty = 0
    E.filename = None
    E.syntax = None
    update_window_size()
    try:
        signal.signal(signal.SIGWINCH, handle_sigwinch)
    except Exception:
        pass


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: kilo <filename>\n")
        sys.exit(1)

    filename = sys.argv[1]
    init_editor()
    editor_select_syntax_highlight(filename)
    editor_open(filename)
    enable_raw_mode(0)
    editor_set_status_message("HELP: Ctrl-S = save | Ctrl-Q = quit | Ctrl-F = find")

    try:
        while True:
            editor_refresh_screen()
            editor_process_keypress(0)
    finally:
        disable_raw_mode(0)


if __name__ == "__main__":
    main()
