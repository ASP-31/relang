#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$SCRIPT_DIR:$PATH"
relang() {
  python3 "$SCRIPT_DIR/relang-submit.py" "$@"
}
echo "Ready. Use 'relang <args>' to run relang-submit.py from anywhere."
