# Asciiquarium (Python Edition)

An aquarium animation in ASCII art converted from Perl to Python 3.

## Features Preserved
- Full multi-layered Z-depth rendering (castle, seaweed, small/medium fish, sharks, ships, whales, sea monsters, big fish, bubbles, blood splat).
- Collision physics (sharks eat small fish with blood splat animations, bubbles pop at the waterline).
- Color mask system supporting HSL tailing, eye highlighting, and dynamic random fish color generation.
- Interactive controls: `q` to quit, `r` to redraw/re-randomize, `p` to pause/resume.
- Command-line flags: `-c` / `--classic` for classic artwork mode, `-v` / `--version`.

## Running

### On Linux / macOS
Standard Python 3 includes `curses` out of the box:
```bash
python3 asciiquarium.py
```

### On Windows
Install `windows-curses` if standard `curses` is not present:
```bash
pip install windows-curses
python asciiquarium.py
```

## Classic Mode
To run in classic mode (disables newer fish and monster models):
```bash
python asciiquarium.py -c
```
