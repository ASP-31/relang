# pipes (JavaScript Implementation)

Animated pipes terminal screensaver rewritten in JavaScript for Node.js.

| Field | Value |
|-------|-------|
| **Type** | Easy |
| **Score** | 100 |
| **Language** | JavaScript (Node.js) |

## Prerequisites

- Node.js 18.0+

## Build

No build required — runs directly with Node.js.

## Run

```bash
node target/index.js
```

You can pass standard options:

```bash
node target/index.js -p 3 -f 50 -P 1 -R
```

### Options

```
  -h, --help            Show help message
  -p, --pipes PIPES     Number of pipes
  -f, --fps FPS         Frames per second (20-100)
  -s, --steady STEADY   Steadiness (5-15)
  -r, --limit LIMIT     Character limit before reset
  -R, --random          Random start
  -B, --no-bold         Disable bold
  -C, --no-color        Disable color
  -P, --pipe-style 0-9  Change pipe style (0-9)
  -K, --keep-style      Keep style on wrap
  -S, --save-config     Save current settings as default
  -v, --version         Show version
```

### Interactive Controls

While running in terminal:
- `P` / `O` : Increase / decrease steadiness
- `F` / `D` : Increase / decrease FPS
- `B`       : Toggle bold
- `C`       : Toggle color
- `K`       : Toggle keep style on wrap
- `?` / `ESC` / `Ctrl+C` : Quit

## Validate

Volunteer-verified — demonstrate the program working during review.

## Submit

```bash
source setup.sh # or setup.bat on Windows
relang "node target/index.js"
```
