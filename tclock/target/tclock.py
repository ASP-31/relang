#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tclock_sphere.py - A glowing sphere that follows the mouse cursor,
with a red 7-segment style digital clock in a black rectangle inscribed inside the sphere.

Requires: Pillow (pip install pillow)
Standard library: tkinter (ships with most Python installs)
"""

import tkinter as tk
import time
from PIL import Image, ImageTk

# ============================================================
# BIG DIGIT FONT (same box-drawing glyphs as the original tclock)
# ============================================================

DIGITS_LINES = {
    "0": [" \u250f\u2501\u2513", " \u2503 \u2503", "    ", " \u2503 \u2503", " \u2517\u2501\u251b"],
    "1": ["    ", "   \u2503", "    ", "   \u2503", "    "],
    "2": [" \u250f\u2501\u2513", "   \u2503", " \u250f\u2501\u251b", " \u2503  ", " \u2517\u2501\u2513"],
    "3": [" \u250f\u2501\u2513", "   \u2503", " \u250f\u2501\u251b", "   \u2503", " \u2517\u2501\u251b"],
    "4": ["    ", " \u2503 \u2503", " \u2517\u2501\u252b", "   \u2503", "    "],
    "5": [" \u250f\u2501\u2513", " \u2503  ", " \u2517\u2501\u2513", "   \u2503", " \u2517\u2501\u251b"],
    "6": [" \u250f\u2501\u2513", " \u2503  ", " \u2523\u2501\u2513", " \u2503 \u2503", " \u2517\u2501\u251b"],
    "7": [" \u250f\u2501\u2513", "   \u2503", "    ", "   \u2503", "    "],
    "8": [" \u250f\u2501\u2513", " \u2503 \u2503", " \u2523\u2501\u252b", " \u2503 \u2503", " \u2517\u2501\u251b"],
    "9": [" \u250f\u2501\u2513", " \u2503 \u2503", " \u2517\u2501\u252b", "   \u2503", " \u2517\u2501\u251b"],
    ":": ["    ", "  : ", "    ", "  : ", "    "],
    ":_blink": ["    ", "  . ", "    ", "  . ", "    "],
    " ": ["     ", "     ", "     ", "     ", "     "],
}


def time_string(num_str: str, blink: bool) -> str:
    lines = [""] * 5
    for ch in num_str:
        if ch == ":":
            pattern = DIGITS_LINES[":"] if blink else DIGITS_LINES[":_blink"]
        else:
            pattern = DIGITS_LINES.get(ch, DIGITS_LINES[" "])
        for i in range(5):
            lines[i] += pattern[i] + " "
    return "\n".join(lines)


# ============================================================
# SPHERE IMAGE (built once with Pillow - radial gradient "moon")
# ============================================================

def make_sphere_image(size: int, pixel_size: int = 8) -> Image.Image:
    """Render a shaded, pixel-art style sphere with a soft outer glow."""
    pad = size // 6           # extra black margin for the glow
    full_canvas = size + pad * 2
    low = max(8, full_canvas // pixel_size)   # low-res grid dimension

    img = Image.new("RGB", (low, low), (0, 0, 0))
    px = img.load()

    cx = cy = low / 2
    r = (size / 2) / pixel_size
    glow_r = 1.18

    # light source offset (upper-left) for a simple shaded look
    lx, ly = -0.42, -0.5

    for y in range(low):
        for x in range(low):
            dx = (x - cx) / r
            dy = (y - cy) / r
            dist = (dx * dx + dy * dy) ** 0.5

            if dist <= 1.0:
                # inside the sphere: shade based on distance from light dir
                dz = (max(0.0, 1.0 - dx * dx - dy * dy)) ** 0.5
                ndotl = dx * lx + dy * ly + dz * 0.75
                ndotl = max(0.0, min(1.0, (ndotl + 1) / 2 * 1.15))
                base = 90 + int(ndotl * 165)
                base = max(0, min(255, base))
                px[x, y] = (base, base, min(255, base + 3))
            elif dist <= glow_r:
                # soft glow falloff outside the sphere edge
                t = (dist - 1.0) / (glow_r - 1.0)
                strength = max(0.0, min(1.0, 0.47 * (1 - t) ** 2))
                g = int(255 * strength)
                px[x, y] = (g, g, g)

    # Scale the low-res sphere up to full size with NEAREST
    img = img.resize((full_canvas, full_canvas), Image.NEAREST)
    return img


# ============================================================
# APP
# ============================================================

class SphereClockApp:
    SIZE = 320           # sphere diameter in px
    PIXEL_SIZE = 8       # size of each pixel-art block
    EASE = 0.12          # follow smoothing factor
    BAND_FRAC = 0.35     # height fraction of the inscribed black rectangle
    BAND_W_FRAC = 0.95   # width fraction to keep box inscribed inside the sphere

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("tclock - cursor sphere")

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")

        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.canvas = tk.Canvas(root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Pre-render the sphere once
        self.sphere_pil = make_sphere_image(self.SIZE, self.PIXEL_SIZE)
        self.sphere_img = ImageTk.PhotoImage(self.sphere_pil)

        self.sphere_item = self.canvas.create_image(
            -1000, -1000, image=self.sphere_img, anchor="center"
        )

        # Inscribed dark rectangle band
        self.band_h = int(self.SIZE * self.BAND_FRAC)
        self.band_w = int(self.SIZE * self.BAND_W_FRAC)
        self.band_item = self.canvas.create_rectangle(
            0, 0, 0, 0, fill="black", outline="", width=0
        )

        # Red digits centered inside the box
        self.text_item = self.canvas.create_text(
            0, 0, text="", fill="#ff2b2b", font=("Consolas", 8),
            justify="center", anchor="center"
        )

        # Mouse tracking
        self.root.update_idletasks()
        start_x = self.root.winfo_pointerx() - self.root.winfo_rootx()
        start_y = self.root.winfo_pointery() - self.root.winfo_rooty()
        self.mouse_x = start_x
        self.mouse_y = start_y
        self.pos_x = float(start_x)
        self.pos_y = float(start_y)

        self.root.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Motion>", self.on_motion)

        self.blink = True
        self.last_second = -1

        self.animate()
        self.update_clock()

    def on_motion(self, event):
        self.mouse_x = event.x
        self.mouse_y = event.y

    def animate(self):
        self.pos_x += (self.mouse_x - self.pos_x) * self.EASE
        self.pos_y += (self.mouse_y - self.pos_y) * self.EASE

        # Move sphere
        self.canvas.coords(self.sphere_item, self.pos_x, self.pos_y)

        # Move inscribed box
        half_h = self.band_h / 2
        half_w = self.band_w / 2
        self.canvas.coords(
            self.band_item,
            self.pos_x - half_w, self.pos_y - half_h,
            self.pos_x + half_w, self.pos_y + half_h
        )

        # Move text
        self.canvas.coords(self.text_item, self.pos_x, self.pos_y)

        # Maintain proper z-stacking: sphere -> box -> text
        self.canvas.tag_raise(self.band_item, self.sphere_item)
        self.canvas.tag_raise(self.text_item, self.band_item)

        self.root.after(16, self.animate)

    def update_clock(self):
        now = time.localtime()
        if now.tm_sec != self.last_second:
            self.blink = not self.blink
            self.last_second = now.tm_sec

        # 12-hour format without leading zero on the hour (e.g. "3:01:57")
        hour_12 = now.tm_hour % 12
        if hour_12 == 0:
            hour_12 = 12
            
        num_str = f"{hour_12}:{now.tm_min:02d}:{now.tm_sec:02d}"
        display = time_string(num_str, self.blink)
        self.canvas.itemconfigure(self.text_item, text=display)

        self.root.after(200, self.update_clock)


def main():
    root = tk.Tk()
    app = SphereClockApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
