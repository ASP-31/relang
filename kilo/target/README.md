# Kilo (Python Port)

A minimal text editor implemented in Python 3, ported from the original C implementation by Salvatore Sanfilippo (antirez).

## Prerequisites

- Python 3.6+

## Run

```bash
python3 kilo/target/kilo.py <filename>
```

Example:
```bash
python3 kilo/target/kilo.py test.txt
```

## Keybindings

- **Ctrl-S**: Save file
- **Ctrl-Q**: Quit (prompts if file has unsaved changes)
- **Ctrl-F**: Find string (ESC/Enter to exit search, Arrow keys to navigate matches)
- **Arrow Keys / Page Up / Page Down**: Navigate cursor
- **Backspace / Del / Ctrl-H**: Delete character

## Features

- Native raw terminal mode using `termios` & VT100 escape sequences
- Tab expansion and soft horizontal scrolling
- C/C++ syntax highlighting with ANSI color codes
- Dynamic window size detection and `SIGWINCH` resize handling
