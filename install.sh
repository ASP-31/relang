#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKER="# === reLang setup"

BLOCK="# === reLang setup (installed by install.sh) ===
export PATH=\"$INSTALL_DIR:\$PATH\"
relang() {
  python3 \"$INSTALL_DIR/relang-submit.py\" \"\$@\"
}
# === end reLang setup ==="

rc_files=()
case "$(basename "${SHELL:-/bin/bash}")" in
  zsh)
    rc_files+=("$HOME/.zshrc")
    [[ "$(uname)" == "Darwin" ]] && rc_files+=("$HOME/.zprofile")
    ;;
  bash)
    if [[ "$(uname)" == "Darwin" ]] && [ -f "$HOME/.bash_profile" ]; then
      rc_files+=("$HOME/.bash_profile")
    fi
    rc_files+=("$HOME/.bashrc")
    ;;
esac

if [ ${#rc_files[@]} -eq 0 ]; then
  for f in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    [ -f "$f" ] && rc_files+=("$f")
  done
fi

if [ ${#rc_files[@]} -eq 0 ]; then
  [[ "$(uname)" == "Darwin" ]] && rc_files+=("$HOME/.zshrc") || rc_files+=("$HOME/.bashrc")
fi

unique_rc=()
for f in "${rc_files[@]}"; do
  skip=
  for u in "${unique_rc[@]}"; do [ "$u" = "$f" ] && skip=1; done
  [ -n "$skip" ] || unique_rc+=("$f")
done

installed=0
for rc in "${unique_rc[@]}"; do
  if [ -f "$rc" ] && grep -qF "$MARKER" "$rc" 2>/dev/null; then
    echo "  Already installed in $rc"
    continue
  fi
  echo "$BLOCK" >> "$rc"
  echo "  Installed in $rc"
  installed=1
done

if [ $installed -eq 0 ]; then
  echo "  Already installed in all detected rc files."
fi

echo ""
echo "Open a new terminal or run:"
for rc in "${unique_rc[@]}"; do echo "  source $rc"; done
echo ""
echo "Then use: relang <your-program-command>"
