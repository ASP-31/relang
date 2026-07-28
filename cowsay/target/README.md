# cowsay (Python target implementation)

A Python port of the `cowsay` configurable talking cow command-line utility.

## Prerequisites

- Python 3.6+ (No external package dependencies needed)

## Run

To run the say version:
```bash
python cowsay/target/cli.py "Hello, world!"
```

To run the think version:
```bash
python cowsay/target/cli.py --think "Hmm..."
```

Piping input from stdin is supported:
```bash
echo "Hello from stdin" | python cowsay/target/cli.py
```

## Other Options

- `-f <cowname>`: Specify a cow file to use (e.g. `-f elephant`, `-f tux`)
- `-l`: List all available cowfiles
- `-r`: Select a random cowfile
- `-e <eyes>`: Specify custom eyes (e.g. `-e "@@"`)
- `-T <tongue>`: Specify custom tongue (e.g. `-T "U "`)
- `-W <column>`: Wrap words at column width (default: 40)
- `-n`: Disable word wrapping
- Mode flags: `-b` (Borg), `-d` (Dead), `-g` (Greedy), `-p` (Paranoia), `-s` (Stoned), `-t` (Tired), `-w` (Wired), `-y` (Youthful)

## Testing and Submission

To submit via `relang`:
```bash
# On Linux/macOS
source setup.sh
relang "python cowsay/target/cli.py"

# On Windows
setup.bat
relang "python cowsay/target/cli.py"
```
