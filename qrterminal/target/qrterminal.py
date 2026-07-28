#!/usr/bin/env python3
"""
qrterminal — QR code generator for the terminal.

A Python port of github.com/mdp/qrterminal (Go). Renders QR codes to the
terminal using either full-block ANSI-colored cells or Unicode half-block
characters for higher density.

Reference CLI flags (matching the Go binary):
  -l LEVEL  Error correction level: L, M, or H (default L)
  -q N      Quiet zone (white border) in modules (default 2)
  -s        Disable sixel graphics output (default: disabled)
  -v        Verbose mode

Content is read from argv as a single space-joined string; if no args are
given, stdin is read until EOF.
"""

from __future__ import annotations

import argparse
import sys

import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_H

# ANSI: a foreground + background pair rendered as two spaces gives one
# thick "cell" the same way the Go reference does (BLACK = "\033[40m  \033[0m").
ANSI_RESET = "\033[0m"
ANSI_BG_BLACK = "\033[40m"  # black background
ANSI_BG_WHITE = "\033[47m"  # white background

# Full-block characters used for the half-block style (matches the Go side).
WHITE_WHITE = "█"  # both rows of the cell are white
BLACK_WHITE = "▀"  # top row white, bottom row black
WHITE_BLACK = "▄"  # top row black, bottom row white
BLACK_BLACK = " "  # both rows are black (rendered with black background)

LEVEL_NAME_TO_CONSTANT = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "H": ERROR_CORRECT_H,
}


def render_full_blocks(matrix: list[list[bool]], quiet_zone: int) -> str:
    """Render the QR matrix using full-block ANSI-colored cells.

    Each QR module becomes two adjacent spaces with a black or white ANSI
    background colour, framed by a quiet_zone-wide white border.
    """
    w = len(matrix)
    out: list[str] = []

    # Top border
    top = (ANSI_BG_WHITE + "  " + ANSI_RESET) * (w + quiet_zone * 2) + "\n"
    out.append(top * quiet_zone)

    # Body
    for row in matrix:
        out.append(ANSI_BG_WHITE + "  " + ANSI_RESET)  # left border
        for module in row:
            if module:
                out.append(ANSI_BG_BLACK + "  " + ANSI_RESET)
            else:
                out.append(ANSI_BG_WHITE + "  " + ANSI_RESET)
        # right border (quiet_zone - 1 trailing cells, since the left one
        # already covers the first column of the border)
        out.append((ANSI_BG_WHITE + "  " + ANSI_RESET) * max(quiet_zone - 1, 0))
        out.append("\n")

    # Bottom border (one fewer row than the top, mirroring the Go layout)
    bottom = (
        (ANSI_BG_WHITE + "  " + ANSI_RESET) * (w + quiet_zone * 2) + "\n"
    ) * max(quiet_zone - 1, 0)
    out.append(bottom)
    return "".join(out)


def render_half_blocks(matrix: list[list[bool]], quiet_zone: int) -> str:
    """Render two rows of the QR matrix per line using Unicode half-block
    characters — matches the Go reference's writeHalfBlocks output.
    """
    w = len(matrix)
    out: list[str] = []

    # Top border: if quiet_zone is odd, leading half-block row is white-on-black,
    # then quiet_zone//2 full white rows.
    if quiet_zone % 2 != 0:
        out.append((BLACK_WHITE * (w + quiet_zone * 2)) + "\n")
        for _ in range(quiet_zone // 2):
            out.append((WHITE_WHITE * (w + quiet_zone * 2)) + "\n")
    else:
        for _ in range(quiet_zone // 2):
            out.append((WHITE_WHITE * (w + quiet_zone * 2)) + "\n")

    # Body: process two rows at a time.
    for i in range(0, w, 2):
        out.append(WHITE_WHITE * quiet_zone)  # left border
        for j in range(w):
            curr_black = matrix[i][j]
            next_black = matrix[i + 1][j] if i + 1 < w else False
            if curr_black and next_black:
                out.append(BLACK_BLACK)
            elif curr_black and not next_black:
                out.append(BLACK_WHITE)
            elif not curr_black and not next_black:
                out.append(WHITE_WHITE)
            else:
                out.append(WHITE_BLACK)
        out.append((WHITE_WHITE * max(quiet_zone - 1, 0)) + "\n")

    # Bottom border
    if quiet_zone % 2 == 0:
        for _ in range(quiet_zone // 2 - 1):
            out.append((WHITE_WHITE * (w + quiet_zone * 2)) + "\n")
        out.append((BLACK_WHITE * (w + quiet_zone * 2)) + "\n")
    else:
        for _ in range(quiet_zone // 2):
            out.append((WHITE_WHITE * (w + quiet_zone * 2)) + "\n")
    return "".join(out)


def build_matrix(text: str, level_name: str) -> list[list[bool]]:
    """Encode `text` into a QR matrix using the requested error correction level."""
    qr = qrcode.QRCode(
        version=None,  # auto-fit
        error_correction=LEVEL_NAME_TO_CONSTANT[level_name],
        box_size=1,  # we render at our own resolution
        border=0,  # the quiet zone is rendered separately
    )
    qr.add_data(text)
    qr.make(fit=True)
    return qr.modules


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qrterminal",
        description="QR code generator for the terminal.",
    )
    parser.add_argument(
        "-l", choices=["L", "M", "H"], default="L",
        help="Error correction level (default: L)",
    )
    parser.add_argument(
        "-q", type=int, default=2,
        help="Quiet zone border size in modules (default: 2)",
    )
    parser.add_argument(
        "-s", action="store_true",
        help="Disable sixel graphics output (default: disabled)",
    )
    parser.add_argument(
        "-v", action="store_true",
        help="Output debugging information",
    )
    parser.add_argument(
        "text", nargs=argparse.REMAINDER,
        help="Text to encode; if omitted, read from stdin",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    content = " ".join(args.text).strip()
    if not content:
        content = sys.stdin.read().strip()

    if not content:
        sys.stderr.write("qrterminal: no content to encode\n")
        return 1

    if args.v:
        sys.stdout.write(f"Level: {args.l}\n")
        sys.stdout.write(f"Quietzone Border Size: {args.q}\n")
        sys.stdout.write(f"Encoded data: {content}\n\n")

    # The Go reference uses half-block mode when the user opts in via
    # GenerateHalfBlock, but the default CLI invocation uses full-block
    # mode with ANSI backgrounds. We mirror that — full-block by default.
    sys.stdout.write("\n")
    matrix = build_matrix(content, args.l)
    sys.stdout.write(render_full_blocks(matrix, args.q))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
