"""Routina Plus: Settings screen + hidden 8-bit Nemesis-style strategy game 'For Thy Lord'.

Run:  python routina_plus.py            (starts Routina with Settings and the secret game)
      python routina_plus.py --selftest (headless checks)
Place fortcore.py, game_hooks.py and this file next to your Routina file ('app (2).py' or 'app.py').
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import tkinter as tk
import wave
from array import array
from datetime import date, datetime
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from tkinter import font as tkfont

import fortcore as fc
import game_hooks
from fortcore import GameError

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

LW, LH = 320, 240

# ============================================================================= colour helpers
def h2r(h):
    """Hex string to an RGB tuple."""
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def r2h(c):
    """RGB tuple to a hex string."""
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)


def mixh(a, b, t):
    """Blend hex colour a toward b by t."""
    ra, rb = h2r(a), h2r(b)
    return r2h([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def shadeh(a, f):
    """Scale a hex colour's brightness by f."""
    return r2h([v * f for v in h2r(a)])


def snap(c):
    """Snap an RGB tuple to 4 levels per channel."""
    return tuple(min(255, int(round(v / 85.0)) * 85) for v in c)


class Palette:
    """16-slot 8-bit palette derived from the Theme."""

    SEMANTIC = [(170, 0, 0), (255, 170, 0), (85, 170, 0), (170, 170, 170)]

    def __init__(self, theme):
        """Derive the palette from the theme colours."""
        bg, pn, tx, ac, bt = theme.background, theme.panel, theme.text, theme.accent, theme.button
        raw = [shadeh(bg, 0.5), shadeh(bg, 0.75), mixh(bg, tx, 0.3), shadeh(pn, 0.7), mixh(pn, tx, 0.3), tx,
               mixh(tx, bg, 0.35), shadeh(ac, 0.55), ac, mixh(ac, "#ffffff", 0.4), shadeh(bt, 0.6), mixh(bt, tx, 0.3)]
        self.colors = [r2h(snap(h2r(c))) for c in raw] + [r2h(c) for c in self.SEMANTIC]
        self.version = theme.palette_version

    def __getitem__(self, i):
        """Return the hex colour of slot i (int or hex digit)."""
        return self.colors[int(i, 16)] if isinstance(i, str) else self.colors[i]


GLOW = ["D", "D", "9", "D"]

# ============================================================================= pixel font 5x7
FONT_SRC = """A 0E 11 11 1F 11 11 11|B 1E 11 11 1E 11 11 1E|C 0E 11 10 10 10 11 0E|D 1E 11 11 11 11 11 1E|E 1F 10 10 1E 10 10 1F|
F 1F 10 10 1E 10 10 10|G 0E 11 10 17 11 11 0F|H 11 11 11 1F 11 11 11|I 0E 04 04 04 04 04 0E|J 07 02 02 02 02 12 0C|
K 11 12 14 18 14 12 11|L 10 10 10 10 10 10 1F|M 11 1B 15 15 11 11 11|N 11 11 19 15 13 11 11|O 0E 11 11 11 11 11 0E|
P 1E 11 11 1E 10 10 10|Q 0E 11 11 11 15 12 0D|R 1E 11 11 1E 14 12 11|S 0F 10 10 0E 01 01 1E|T 1F 04 04 04 04 04 04|
U 11 11 11 11 11 11 0E|V 11 11 11 11 11 0A 04|W 11 11 11 15 15 15 0A|X 11 11 0A 04 0A 11 11|Y 11 11 0A 04 04 04 04|
Z 1F 01 02 04 08 10 1F|0 0E 11 13 15 19 11 0E|1 04 0C 04 04 04 04 0E|2 0E 11 01 02 04 08 1F|3 1F 02 04 02 01 11 0E|
4 02 06 0A 12 1F 02 02|5 1F 10 1E 01 01 11 0E|6 06 08 10 1E 11 11 0E|7 1F 01 02 04 08 08 08|8 0E 11 11 0E 11 11 0E|
9 0E 11 11 0F 01 02 0C|. 00 00 00 00 00 0C 0C|, 00 00 00 00 0C 04 08|: 00 0C 0C 00 0C 0C 00|! 04 04 04 04 04 00 04|
? 0E 11 01 02 04 00 04|- 00 00 00 1F 00 00 00|+ 00 04 04 1F 04 04 00|/ 01 01 02 04 08 10 10|( 02 04 08 08 08 04 02|
) 08 04 02 02 02 04 08|' 04 04 08 00 00 00 00|% 18 19 02 04 08 13 03|# 0A 0A 1F 0A 1F 0A 0A|= 00 00 1F 00 1F 00 00|
* 00 04 15 0E 15 04 00|< 02 04 08 10 08 04 02|> 08 04 02 01 02 04 08|_ 00 00 00 00 00 00 1F|" 0A 0A 00 00 00 00 00|
  00 00 00 00 00 00 00"""
FONT = {}
for _ent in FONT_SRC.replace("\n", "").split("|"):
    _parts = _ent.split(" ")
    if _ent.startswith("  "):
        FONT[" "] = [0] * 7
    elif len(_parts) >= 8:
        FONT[_parts[0]] = [int(x, 16) for x in _parts[1:8]]
FONT.setdefault(" ", [0] * 7)

# ============================================================================= sprite data
def _hl(x0, x1, y, ch):
    """Horizontal pixel run."""
    return [(x, y, ch) for x in range(x0, x1 + 1)]


def _vl(x, y0, y1, ch):
    """Vertical pixel run."""
    return [(x, y, ch) for y in range(y0, y1 + 1)]


BODY = [
    "................",
    ".....oooooo.....",
    "....oHHHHHHo....",
    "....oHHHHHHo....",
    "....oHHHHHHo....",
    ".....oooooo.....",
    "...ooTTTTTToo...",
    "..oTTTTTTTTTTo..",
    "..oTTTTTTTTTTo..",
    "..oTTTTTTTTTTo..",
    "...ooTTTTTToo...",
    ".....oLLLLo.....",
    ".....oLooLo.....",
    ".....oLooLo.....",
    ".....oFooFo.....",
    "................",
]
CROWN = _hl(5, 10, 1, "D") + [(5, 0, "D"), (7, 0, "D"), (8, 0, "D"), (10, 0, "D")]
SPR = {
    "archer": dict(reg={"H": "5", "T": "8", "L": "7", "F": "0"}, extra=_hl(5, 10, 2, "7"),
                   w0=_vl(13, 4, 11, "D") + _vl(14, 5, 10, "5"), w1=_vl(13, 4, 11, "D") + [(14, 7, "F"), (15, 7, "F"), (12, 7, "5")]),
    "wizard": dict(reg={"H": "5", "T": "B", "L": "4", "F": "0"},
                   extra=[(7, 0, "4"), (8, 0, "4")] + _hl(6, 9, 1, "4") + _hl(4, 11, 2, "4"),
                   w0=_vl(13, 3, 12, "D") + [(13, 2, "9"), (12, 2, "9"), (14, 2, "9"), (13, 1, "9")],
                   w1=_vl(13, 3, 12, "D") + [(13, 2, "9"), (12, 2, "9"), (14, 2, "9"), (13, 1, "9"), (15, 2, "9"), (15, 4, "9"), (14, 4, "5")]),
    "rogue": dict(reg={"H": "6", "T": "6", "L": "3", "F": "0"}, extra=_hl(5, 10, 3, "1"),
                  w0=_hl(12, 14, 8, "F"), w1=[(12, 7, "F"), (13, 6, "F"), (14, 5, "F"), (15, 4, "F"), (12, 8, "F")]),
    "goon": dict(reg={"H": "5", "T": "F", "L": "3", "F": "0"}, extra=_hl(5, 10, 2, "F"),
                 w0=_vl(13, 2, 13, "F") + [(13, 1, "F")], w1=_hl(11, 15, 8, "F")),
    "captain": dict(reg={"H": "5", "T": "C", "L": "3", "F": "0"},
                    extra=_hl(5, 10, 2, "F") + [(7, 0, "C"), (8, 0, "C"), (7, 1, "C"), (8, 1, "C")],
                    w0=_vl(13, 5, 11, "F") + [(12, 10, "D"), (14, 10, "D")], w1=_hl(11, 15, 7, "F")),
    "lord": dict(reg={"H": "5", "T": "C", "L": "D", "F": "0"}, extra=CROWN + _vl(3, 7, 12, "C") + _vl(12, 7, 12, "C"),
                 w0=_vl(13, 3, 12, "D") + [(12, 3, "C"), (14, 3, "C")], w1=_hl(11, 15, 7, "D")),
}
SKULL = ["................", "....oooooooo....", "...o55555555o...", "..o5555555555o..", "..o5555555555o..",
         "..o55oo55oo55o..", "..o55oo55oo55o..", "..o5555oo5555o..", "...o55555555o...", "....o5o55o5o....",
         "....o5o55o5o....", ".....oooooo....."]
CHAR_NAMES = ("archer", "wizard", "rogue", "goon", "captain", "lord")


def _grid_to_px(rows, mapping=None):
    """Convert rows of characters to a pixel dict."""
    px = {}
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                px[(x, y)] = (mapping or {}).get(ch, ch)
    return px


def _char_pixels(name, frame, legendary, tick):
    """Build one character frame from the base body, overlays and offsets."""
    d = SPR[name]
    reg = dict(d["reg"], o="0")
    base = _grid_to_px(BODY, reg)
    for x, y, ch in d["extra"]:
        base[(x, y)] = ch
    if legendary:
        for x, y, ch in CROWN:
            base[(x, y)] = ch
        glow = GLOW[tick % 4]
        for k, v in list(base.items()):
            if v == "0":
                base[k] = glow
    out = {}
    if frame <= 1:
        for (x, y), ch in base.items():
            out[(x, y + 1 if (frame == 1 and y < 14) else y)] = ch
        for x, y, ch in d["w0"]:
            out[(x, y + 1 if (frame == 1 and y < 14) else y)] = ch
        if frame == 1:
            for (x, y), ch in base.items():
                if y >= 14:
                    out[(x, y)] = ch
    elif frame <= 3:
        dx = 1 if frame == 2 else 2
        for (x, y), ch in base.items():
            out[(x + dx, y)] = ch
        for x, y, ch in (d["w0"] if frame == 2 else d["w1"]):
            out[(x + dx, y)] = ch
    else:
        f, s = [(1.0, 0.3), (0.6, 0.7), (0.3, 1.0)][min(frame - 4, 2)]
        for (x, y), ch in base.items():
            out[(x + int((15 - y) * s), 15 - int((15 - y) * f))] = ch
    return {k: v for k, v in out.items() if 0 <= k[0] < 16 and 0 <= k[1] < 16}


def _tile_pixels(name):
    """Build a 16x16 tile."""
    px = {}
    for y in range(16):
        for x in range(16):
            if name == "grass":
                ch = "7" if (x * 5 + y * 11) % 13 == 0 else "E"
            elif name == "road":
                ch = "6" if (x * 3 + y * 7) % 9 == 0 else "4"
            elif name == "wall":
                ch = "0" if (y % 4 == 3 or (x + (y // 4) * 4) % 8 == 7) else ("6" if y % 4 == 0 else "4")
            else:
                ch = "."
                if x == 2:
                    ch = "6"
                elif 3 <= x <= 12 and 2 <= y <= 9 and not (y >= 8 and 6 <= x <= 9):
                    ch = "D" if (7 <= x <= 8 and 4 <= y <= 6) else "8"
            if ch != ".":
                px[(x, y)] = ch
    return px


def _fortress_pixels(conquered):
    """Build the 32x32 fortress."""
    g = [["."] * 32 for _ in range(32)]

    def fill(x0, y0, x1, y1, ch):
        """Fill a rectangle."""
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                g[yy][xx] = ch
    fill(5, 14, 26, 31, "4")
    fill(0, 8, 7, 31, "6")
    fill(24, 8, 31, 31, "6")
    for x in range(0, 8, 2):
        fill(x, 5, x, 7, "6")
        fill(24 + x, 5, 24 + x, 7, "6")
    for x in range(5, 27, 3):
        fill(x, 12, min(x + 1, 26), 13, "4")
    for y in range(16, 32, 4):
        fill(5, y, 26, y, "0")
    fill(12, 20, 19, 31, "0")
    fill(13, 18, 18, 19, "0")
    fill(3, 12, 4, 14, "0")
    fill(27, 12, 28, 14, "0")
    fill(15, 2, 15, 13, "6")
    fill(16, 2, 21, 6, "8" if conquered else "C")
    out = [row[:] for row in g]
    for y in range(32):
        for x in range(32):
            if g[y][x] == ".":
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < 32 and 0 <= yy < 32 and g[yy][xx] != ".":
                        out[y][x] = "0"
    return _grid_to_px(["".join(r) for r in out])


def _spark_pixels(frame):
    """Build a hit spark frame."""
    px = {}
    n = 2 + frame * 2
    for k in range(1, n + 1):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            px[(8 + dx * k, 8 + dy * k)] = "D" if k % 2 else "5"
        if k <= n - 1 and frame > 0:
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                px[(8 + dx * k, 8 + dy * k)] = "D"
    px[(8, 8)] = "5"
    return {k: v for k, v in px.items() if 0 <= k[0] < 16 and 0 <= k[1] < 16}


def _coin_pixels():
    """Build the token coin."""
    px = {}
    for y in range(16):
        for x in range(16):
            r = math.hypot(x - 7.5, y - 7.5)
            if r <= 6.5:
                px[(x, y)] = "0" if r > 5.5 else ("D" if not (7 <= x <= 8 and 4 <= y <= 11) else "9")
    return px


def sprite_pixels(name, frame=0, legendary=False, tick=0):
    """Return (pixel dict, size) for a named sprite."""
    if name in SPR:
        return _char_pixels(name, frame, legendary, tick), 16
    if name in ("grass", "road", "wall", "banner"):
        return _tile_pixels(name), 16
    if name == "fortress":
        return _fortress_pixels(frame == 1), 32
    if name == "spark":
        return _spark_pixels(frame), 16
    if name == "skull":
        return _grid_to_px(SKULL), 16
    return _coin_pixels(), 16


class SpriteRenderer:
    """Renders pixel maps and 5x7 text into cached PhotoImages (keyed by palette_version and scale)."""

    def __init__(self, theme, root):
        """Create a renderer bound to a theme."""
        self.theme, self.root = theme, root
        self.pal = Palette(theme)
        self.cache = {}
        self.field_cache = {}

    def sync(self):
        """Rebuild the palette if the theme changed."""
        if self.pal.version != self.theme.palette_version:
            self.pal = Palette(self.theme)
            self.cache.clear()
            self.field_cache.clear()

    def color(self, c):
        """Resolve a slot index or hex string."""
        return c if isinstance(c, str) and c.startswith("#") else self.pal[c]

    def get(self, name, frame=0, scale=3, mirrored=False, legendary=False, tick=0):
        """Return a cached sprite image."""
        self.sync()
        t = tick % 4 if legendary else 0
        key = (name, frame, self.pal.version, scale, mirrored, legendary, t)
        img = self.cache.get(key)
        if img is None:
            if len(self.cache) > 2500:
                self.cache.clear()
            px, size = sprite_pixels(name, frame, legendary, t)
            img = tk.PhotoImage(master=self.root, width=size * scale, height=size * scale)
            for (x, y), ch in px.items():
                xx = (size - 1 - x) if mirrored else x
                img.put(self.pal[ch], to=(xx * scale, y * scale, (xx + 1) * scale, (y + 1) * scale))
            self.cache[key] = img
        return img

    def text(self, s, color, px):
        """Return a cached image of text in the 5x7 font (px = pixel size)."""
        self.sync()
        s = str(s).upper()
        col = self.color(color)
        key = ("t", s, col, px)
        img = self.cache.get(key)
        if img is None:
            if len(self.cache) > 2500:
                self.cache.clear()
            img = tk.PhotoImage(master=self.root, width=max(1, (len(s) * 6 - 1) * px), height=7 * px)
            for i, ch in enumerate(s):
                rows = FONT.get(ch, FONT["?"])
                for y, bits in enumerate(rows):
                    x = 0
                    while x < 5:
                        if bits & (1 << (4 - x)):
                            x0 = x
                            while x < 5 and bits & (1 << (4 - x)):
                                x += 1
                            img.put(col, to=((i * 6 + x0) * px, y * px, (i * 6 + x) * px, (y + 1) * px))
                        else:
                            x += 1
            self.cache[key] = img
        return img

    def field(self, scale):
        """Return the pre-composed battlefield background."""
        self.sync()
        img = self.field_cache.get(scale)
        if img is None:
            img = tk.PhotoImage(master=self.root, width=fc.FIELD_COLS * 16 * scale, height=fc.FIELD_ROWS * 16 * scale)
            for c in range(fc.FIELD_COLS):
                tname = "road" if c <= 2 else ("wall" if c >= 8 else "grass")
                tile = self.get(tname, 0, scale)
                for r in range(fc.FIELD_ROWS):
                    img.tk.call(img.name, "copy", tile.name, "-to", c * 16 * scale, r * 16 * scale)
            self.field_cache[scale] = img
        return img


def pick_family(root, heading=False):
    """Pick the first installed font from the chain (blackletter first for headings)."""
    try:
        fams = {f.lower(): f for f in tkfont.families(root)}
    except Exception:
        return "TkDefaultFont"
    chain = (["UnifrakturCook", "Blackadder ITC", "Old English Text MT", "MedievalSharp"] if heading else []) + \
        ["Georgia", "Palatino Linotype", "Times New Roman", "Times", "DejaVu Serif", "Liberation Serif", "serif"]
    for f in chain:
        if f.lower() in fams:
            return fams[f.lower()]
    return "TkDefaultFont"


# ============================================================================= animation engine
EASE = {
    "linear": lambda t: t,
    "out_cubic": lambda t: 1 - (1 - t) ** 3,
    "in_out_quad": lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2,
    "out_back": lambda t: 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2,
}


class AnimEngine:
    """One central ~60 fps loop: tickers, tweens, and screen transitions."""

    def __init__(self, root, theme):
        """Start the loop."""
        self.root, self.theme = root, theme
        self.tickers, self._id = {}, 0
        self.overlays = set()
        self.busy = False
        self._next = None
        self.running = True
        self.last = time.perf_counter()
        self._job = None
        self._loop()

    def add_ticker(self, fn) -> int:
        """Register fn(dt_ms); return False from fn to remove it."""
        self._id += 1
        self.tickers[self._id] = fn
        return self._id

    def remove(self, handle) -> None:
        """Remove a ticker."""
        self.tickers.pop(handle, None)

    def tween(self, duration_ms, fn, easing="out_cubic", on_done=None) -> int:
        """Animate fn(progress 0..1) with easing; instant when Reduce motion is on."""
        if self.theme.reduce_motion or duration_ms <= 0:
            fn(1.0)
            if on_done:
                on_done()
            return -1
        st = {"t": 0.0}
        ease = EASE.get(easing, EASE["out_cubic"])

        def step(dt):
            """Advance this tween."""
            st["t"] += dt
            p = min(1.0, st["t"] / duration_ms)
            fn(ease(p))
            if p >= 1.0:
                if on_done:
                    on_done()
                return False
            return True
        return self.add_ticker(step)

    def _loop(self):
        """Run one frame; idle slowly while the window is hidden."""
        if not self.running:
            return
        try:
            visible = bool(self.root.winfo_viewable())
        except tk.TclError:
            return
        now = time.perf_counter()
        dt = min((now - self.last) * 1000.0, 100.0)
        self.last = now
        delay = 250
        if visible:
            delay = 16
            for h, fn in list(self.tickers.items()):
                try:
                    keep = fn(dt)
                except Exception:
                    keep = False
                if keep is False:
                    self.tickers.pop(h, None)
        self._job = self.root.after(delay, self._loop)

    def transition(self, host, build_next, kind=None) -> None:
        """Cover host with a block dissolve or slide, swap screens at the midpoint, then reveal."""
        self._next = build_next
        if self.busy:
            return
        if self.theme.reduce_motion:
            fn, self._next = self._next, None
            fn()
            return
        self.busy = True
        kind = kind or random.choice(("dissolve", "slide"))
        dur = random.randint(250, 400)
        host.update_idletasks()
        w, h = max(host.winfo_width(), 8), max(host.winfo_height(), 8)
        col = shadeh(self.theme.accent, 0.45)
        order = list(range(64))
        random.shuffle(order)
        blocks = []
        if kind == "dissolve":
            for i in range(64):
                blocks.append(tk.Frame(host, bg=col, bd=0))
        else:
            blocks.append(tk.Frame(host, bg=col, bd=0))
        for b in blocks:
            self.overlays.add(b)
        st = {"t": 0.0, "swapped": False}

        def show_blocks(n_hidden_first, covered):
            """Place the dissolve blocks: covered=True shows the first n, False hides the first n."""
            for i, idx in enumerate(order):
                vis = (i < n_hidden_first) if covered else (i >= n_hidden_first)
                b = blocks[idx]
                if vis:
                    b.place(x=int((idx % 8) * w / 8), y=int((idx // 8) * h / 8), width=int(w / 8) + 2, height=int(h / 8) + 2)
                else:
                    b.place_forget()

        def finish():
            """Remove the overlay widgets."""
            for b in blocks:
                self.overlays.discard(b)
                try:
                    b.destroy()
                except tk.TclError:
                    pass
            self.busy = False

        def step(dt):
            """Advance the transition."""
            st["t"] += dt
            p = min(1.0, st["t"] / dur)
            try:
                if p < 0.5:
                    c = p * 2
                    if kind == "dissolve":
                        show_blocks(int(c * 64), True)
                    else:
                        blocks[0].place(x=0, y=0, width=max(1, int(c * w)), height=h)
                else:
                    if not st["swapped"]:
                        st["swapped"] = True
                        fn, self._next = self._next, None
                        if fn:
                            fn()
                        for b in blocks:
                            b.lift()
                    u = (p - 0.5) * 2
                    if kind == "dissolve":
                        show_blocks(int(u * 64), False)
                    else:
                        x0 = int(u * w)
                        blocks[0].place(x=x0, y=0, width=max(1, w - x0), height=h)
            except tk.TclError:
                finish()
                return False
            except Exception:
                finish()
                raise
            if p >= 1.0:
                finish()
                return False
            return True
        self.add_ticker(step)

    def shutdown(self) -> None:
        """Stop the loop and remove overlays."""
        self.running = False
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except tk.TclError:
                pass
        for o in list(self.overlays):
            try:
                o.destroy()
            except tk.TclError:
                pass
        self.tickers.clear()


# ============================================================================= audio
RATE = 16000
THEME_SPECS = {
    "menu": dict(bpm=100, bars=12, roots=[45, 41, 48, 43], arp=[0, 3, 7, 12], scale=[0, 3, 5, 7, 10, 12, 15], seed=7),
    "battle": dict(bpm=150, bars=16, roots=[40, 40, 43, 38], arp=[0, 7, 12, 7], scale=[0, 3, 5, 6, 7, 10, 12], seed=11),
}


def _midi(n):
    """MIDI note number to frequency."""
    return 440.0 * 2 ** ((n - 69) / 12.0)


def _write_wav(path, buf):
    """Write a mono 16-bit WAV from an int list."""
    arr = array("h", [max(-32767, min(32767, v)) for v in buf])
    if sys.byteorder == "big":
        arr.byteswap()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(arr.tobytes())


def _add_note(buf, freq, start, length, wave_kind, amp):
    """Mix one square or triangle note into buf."""
    inc = freq / RATE
    att, rel = int(RATE * 0.004), int(RATE * 0.03)
    for i in range(min(length, len(buf) - start)):
        ph = (i * inc) % 1.0
        v = (1.0 if ph < 0.5 else -1.0) if wave_kind == "sq" else 4 * abs(ph - 0.5) - 1.0
        env = min(1.0, i / att if att else 1.0, (length - i) / rel if rel else 1.0)
        buf[start + i] += int(v * amp * env)


def synth_theme(name, path):
    """Render a 20-40 s chiptune loop (square lead/arp + triangle bass) to a WAV file."""
    sp = THEME_SPECS[name]
    rnd = random.Random(sp["seed"])
    step = 60.0 / sp["bpm"] / 2
    n_steps = sp["bars"] * 8
    sl = int(step * RATE)
    buf = [0] * (n_steps * sl)
    for s in range(n_steps):
        root = sp["roots"][(s // 8) % len(sp["roots"])]
        start = s * sl
        if s % 2 == 0:
            _add_note(buf, _midi(root), start, int(sl * 1.9), "tri", 7000)
        _add_note(buf, _midi(root + 24 + sp["arp"][s % len(sp["arp"])]), start, int(sl * 0.8), "sq", 2200)
        if rnd.random() < 0.7:
            note = root + 36 + rnd.choice(sp["scale"])
            _add_note(buf, _midi(note), start, int(sl * rnd.choice((0.9, 1.8))), "sq", 3600)
    _write_wav(path, buf)


def synth_sfx(kind, path):
    """Render a short square-wave effect."""
    seq = {"hit": [880, 660, 440], "win": [523, 659, 784, 1047], "lose": [440, 330, 247, 196],
           "click": [1200], "coin": [988, 1319]}[kind]
    buf = [0] * int(RATE * 0.07 * len(seq))
    for i, f in enumerate(seq):
        _add_note(buf, f, int(i * RATE * 0.07), int(RATE * 0.07), "sq", 6000)
    _write_wav(path, buf)


class AudioPlayer:
    """Chiptune playback (winsound / afplay / aplay / paplay / pygame.mixer) that fails silently."""

    def __init__(self, theme):
        """Start generating audio in a background thread."""
        self.theme = theme
        self.dir = None
        self.files = {}
        self.sfx_snd = {}
        self.ready = False
        self.current = None
        self.mixer = None
        self.proc = None
        self.stop_evt = threading.Event()
        self.alive = True
        self.last_mute = theme.mute
        theme.subscribe(self._on_theme)
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        """Generate WAVs and optionally init pygame.mixer (never raises)."""
        try:
            self.dir = tempfile.mkdtemp(prefix="ftl_audio_")
            for n in THEME_SPECS:
                if not self.alive:
                    return
                p = os.path.join(self.dir, n + ".wav")
                synth_theme(n, p)
                self.files[n] = p
            sfx_files = {}
            for k in ("hit", "win", "lose", "click", "coin"):
                p = os.path.join(self.dir, "sfx_" + k + ".wav")
                synth_sfx(k, p)
                sfx_files[k] = p
            try:
                import pygame
                pygame.mixer.init(frequency=RATE, size=-16, channels=1)
                self.mixer = pygame.mixer
                self.sfx_snd = {k: pygame.mixer.Sound(p) for k, p in sfx_files.items()}
            except Exception:
                self.mixer = None
            self.ready = True
            if self.current and self.alive:
                self._start(self.current)
        except Exception:
            self.ready = False

    def _on_theme(self, theme):
        """React to the Mute toggle."""
        if theme.mute != self.last_mute:
            self.last_mute = theme.mute
            if theme.mute:
                self._halt()
            elif self.current:
                self._start(self.current)

    def _loop_proc(self, path):
        """Loop an external player process on non-Windows systems."""
        exe = None
        if sys.platform == "darwin":
            exe = shutil.which("afplay")
            cmd = [exe, path] if exe else None
        else:
            exe = shutil.which("paplay") or shutil.which("aplay")
            cmd = ([exe, path] if exe and exe.endswith("paplay") else [exe, "-q", path]) if exe else None
        if not cmd:
            return
        evt = threading.Event()
        self.stop_evt = evt

        def run():
            """Respawn the player until stopped."""
            while not evt.is_set():
                try:
                    self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.proc.wait()
                except Exception:
                    return
        threading.Thread(target=run, daemon=True).start()

    def _start(self, name):
        """Begin looping a theme."""
        path = self.files.get(name)
        if not path or self.theme.mute or not self.alive:
            return
        self._halt()
        try:
            if self.mixer:
                self.mixer.music.load(path)
                self.mixer.music.play(-1)
            elif sys.platform.startswith("win"):
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            else:
                self._loop_proc(path)
        except Exception:
            pass

    def _halt(self):
        """Stop whatever is playing."""
        try:
            self.stop_evt.set()
            if self.proc is not None:
                self.proc.terminate()
                self.proc = None
        except Exception:
            pass
        try:
            if self.mixer:
                self.mixer.music.stop()
            elif sys.platform.startswith("win"):
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def play_theme(self, name):
        """Play 'menu' or 'battle' (no-op if already playing)."""
        if self.current == name:
            return
        self.current = name
        if self.ready:
            self._start(name)

    def sfx(self, name):
        """Play a sound effect when pygame.mixer is available."""
        try:
            if self.mixer and not self.theme.mute and name in self.sfx_snd:
                self.sfx_snd[name].play()
        except Exception:
            pass

    def stop(self):
        """Stop playback and forget the current theme."""
        self.current = None
        self._halt()

    def shutdown(self):
        """Stop audio and delete temp files."""
        self.alive = False
        self.stop()
        self.theme.unsubscribe(self._on_theme)
        try:
            if self.mixer:
                self.mixer.quit()
        except Exception:
            pass
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)


# ============================================================================= ttk styling
def style_ttk(root, th):
    """Skin ttk widgets from the Theme."""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    bg, pn, tx, ac, bt = th.background, th.panel, th.text, th.accent, th.button
    st.configure(".", background=bg, foreground=tx, fieldbackground=pn)
    st.configure("TFrame", background=bg)
    st.configure("TLabel", background=bg, foreground=tx)
    st.configure("TNotebook", background=bg, borderwidth=0)
    st.configure("TNotebook.Tab", background=bt, foreground=tx, padding=(12, 6))
    st.map("TNotebook.Tab", background=[("selected", pn)], foreground=[("selected", ac)])
    st.configure("Treeview", background=pn, fieldbackground=pn, foreground=tx, rowheight=22, borderwidth=0)
    st.map("Treeview", background=[("selected", ac)], foreground=[("selected", bg)])
    st.configure("Treeview.Heading", background=bt, foreground=ac, relief="flat")
    st.map("Treeview.Heading", background=[("active", mixh(bt, tx, 0.2))])
    st.configure("TCombobox", fieldbackground=pn, background=bt, foreground=tx, arrowcolor=ac)
    st.map("TCombobox", fieldbackground=[("readonly", pn)], foreground=[("readonly", tx)])
    st.configure("TCheckbutton", background=bg, foreground=tx)
    st.configure("TRadiobutton", background=bg, foreground=tx)
    st.map("TRadiobutton", background=[("active", bg)], foreground=[("active", ac)])
    st.map("TCheckbutton", background=[("active", bg)], foreground=[("active", ac)])
    st.configure("TEntry", fieldbackground=pn, foreground=tx)
    st.configure("Vertical.TScrollbar", background=bt, troughcolor=pn, arrowcolor=ac)
    root.option_add("*TCombobox*Listbox.background", pn)
    root.option_add("*TCombobox*Listbox.foreground", tx)
    root.option_add("*TCombobox*Listbox.selectBackground", ac)


# ============================================================================= game context and pixel view
class GameCtx:
    """Shared game services: theme, db, engine, audio, renderer, core and token counter."""

    def __init__(self, root, theme, db, engine):
        """Create the context."""
        self.root, self.theme, self.db, self.engine = root, theme, db, engine
        self.audio = None
        self.rend = SpriteRenderer(theme, root)
        self.core = None
        self.tokens, self.shown, self.owned, self._acc = 0, 0.0, 0, 0.0

    def ensure_core(self):
        """Create the GameCore lazily."""
        if self.core is None:
            self.core = fc.GameCore(self.db, random.Random())

    def refresh(self):
        """Reload the token balance and owned count."""
        try:
            self.tokens = self.db.balance()["balance"]
            self.owned = self.core.owned_count() if self.core else 0
        except Exception:
            pass

    def tick(self, dt):
        """Advance the animated token counter."""
        self._acc += dt
        if self._acc > 800:
            self._acc = 0
            self.refresh()
        if self.theme.reduce_motion:
            self.shown = self.tokens
        else:
            self.shown += (self.tokens - self.shown) * min(1.0, dt / 140.0)
            if abs(self.tokens - self.shown) < 0.5:
                self.shown = self.tokens


class PixelView(tk.Canvas):
    """320x240 logical canvas scaled by an integer, with immediate-mode drawing helpers and hit zones."""

    def __init__(self, master, ctx, scale):
        """Create the view and register it with the animation engine."""
        super().__init__(master, width=LW * scale, height=LH * scale, highlightthickness=0, bd=0, bg=ctx.rend.pal[1])
        self.ctx, self.S = ctx, scale
        self.hot, self.hover, self.pressed, self.screen, self.t = [], None, None, None, 0.0
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: setattr(self, "hover", None))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._h = ctx.engine.add_ticker(self._frame)

    def destroy(self):
        """Stop the ticker then destroy."""
        self.ctx.engine.remove(self._h)
        super().destroy()

    def go(self, screen):
        """Switch screens with a transition."""
        self.ctx.engine.transition(self.master, lambda: self.set_screen(screen))

    def set_screen(self, screen):
        """Switch screens instantly."""
        self.screen = screen
        self.hot, self.hover, self.pressed = [], None, None
        screen.enter(self)

    def _frame(self, dt):
        """Per-frame update and redraw."""
        try:
            if not self.winfo_exists():
                return False
        except tk.TclError:
            return False
        self.t += dt / 1000.0
        self.ctx.tick(dt)
        if self.screen:
            self.screen.update(dt)
            self.redraw()
        return True

    def redraw(self):
        """Redraw everything."""
        self.ctx.rend.sync()
        self.configure(bg=self.ctx.rend.pal[1])
        self.delete("all")
        self.hot = []
        self.screen.draw(self)

    def _at(self, e):
        """Return the top hit zone under an event."""
        lx, ly = e.x / self.S, e.y / self.S
        for z in reversed(self.hot):
            if z[0] <= lx < z[2] and z[1] <= ly < z[3]:
                return z
        return None

    def _motion(self, e):
        """Track hover and cursor."""
        z = self._at(e)
        self.hover = z[4] if z else None
        self.configure(cursor="hand2" if (z and z[5] and z[6]) else "")

    def _press(self, e):
        """Remember the pressed zone."""
        z = self._at(e)
        self.pressed = z[4] if z else None

    def _release(self, e):
        """Fire the callback if released on the pressed zone."""
        z = self._at(e)
        if z and z[4] == self.pressed and z[5] and z[6]:
            self.pressed = None
            if self.ctx.audio:
                self.ctx.audio.sfx("click")
            z[5]()
        self.pressed = None

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, stipple=None):
        """Draw a rectangle in logical coordinates (colours are palette slots or hex)."""
        S, r = self.S, self.ctx.rend
        kw = {"fill": r.color(fill) if fill is not None else "", "outline": r.color(outline) if outline is not None else "",
              "width": S if outline is not None else 0}
        if stipple:
            kw["stipple"] = stipple
        self.create_rectangle(x0 * S, y0 * S, x1 * S, y1 * S, **kw)

    def text(self, x, y, s, color=5, size=1, anchor="nw"):
        """Draw 5x7 pixel-font text."""
        img = self.ctx.rend.text(s, color, size * self.S)
        self.create_image(x * self.S, y * self.S, image=img, anchor=anchor)

    def sprite(self, x, y, name, frame=0, mirrored=False, legendary=False, anchor="nw"):
        """Draw a sprite."""
        img = self.ctx.rend.get(name, frame, self.S, mirrored, legendary, int(self.t * 8))
        self.create_image(x * self.S, y * self.S, image=img, anchor=anchor)

    def zone(self, x0, y0, x1, y1, zid, cb=None, enabled=True):
        """Register a clickable/hoverable zone."""
        self.hot.append((x0, y0, x1, y1, zid, cb, enabled))

    def button(self, x0, y0, x1, y1, label, cb, enabled=True, zid=None):
        """Draw a pixel button with hover and press states."""
        zid = zid or label
        hov = enabled and self.hover == zid
        prs = hov and self.pressed == zid
        self.rect(x0, y0, x1, y1, 7 if prs else ("B" if hov else "A"), 8 if enabled else 6)
        self.text((x0 + x1) / 2, (y0 + y1) / 2 + (1 if prs else 0), label, 5 if enabled else 6, 1, "center")
        self.zone(x0, y0, x1, y1, zid, cb, enabled)


def draw_header(v, ctx, title):
    """Draw the shared header bar."""
    v.rect(0, 0, LW, 16, 3)
    v.rect(0, 15, LW, 16, 6)
    v.sprite(0, 0, "banner")
    v.sprite(LW - 16, 0, "banner")
    v.text(20, 4, title[:15], 9)
    v.sprite(114, 0, "coin")
    v.text(132, 4, "%d" % round(ctx.shown), "D")
    v.text(180, 4, "OWNED %d/%d" % (ctx.owned, fc.MAX_OWNED_UNITS), 6)


# ============================================================================= menu
class MenuScreen:
    """Second main menu: animated title and a button stack."""

    def __init__(self, gm):
        """Bind to the game menu controller."""
        self.gm = gm

    def enter(self, v):
        """Start the menu music."""
        if self.gm.ctx.audio:
            self.gm.ctx.audio.play_theme("menu")
        self.gm.ctx.refresh()

    def update(self, dt):
        """No per-frame state."""

    def draw(self, v):
        """Draw the title, parade and buttons."""
        ctx, t = self.gm.ctx, v.t
        v.rect(0, 0, LW, LH, 1)
        for x in range(0, LW, 16):
            v.sprite(x, 224, "grass")
        title, size = "FOR THY LORD", 3
        x0 = (LW - (len(title) * 6 - 1) * size) / 2
        by = 20 + (0 if ctx.theme.reduce_motion else math.sin(t * 2) * 2)
        for i, ch in enumerate(title):
            if ch == " ":
                continue
            g = 1 if ctx.theme.reduce_motion else int((math.sin(t * 3 - i * 0.6) + 1) * 1.5)
            v.text(x0 + i * 6 * size + 1, by + 1, ch, 0, size)
            v.text(x0 + i * 6 * size, by, ch, ("7", "8", "9", "D")[max(0, min(3, g))], size)
        v.text(LW / 2, 52, "A NEMESIS-STYLE STRATEGY", 6, 1, "n")
        fr = int(t * 8) % 2
        for i, n in enumerate(("archer", "wizard", "rogue")):
            v.sprite(40 + i * 24, 66, n, fr, False, n == "wizard")
        for i, n in enumerate(("goon", "captain", "lord")):
            v.sprite(232 + i * 24, 66, n, fr, True)
        for i, (lab, cb) in enumerate((("PLAY", self.gm.play), ("COPYRIGHT NOTICE", self.gm.copyright),
                                       ("INVENTORY", self.gm.inventory), ("BACK TO ROUTINA", self.gm.close))):
            v.button(100, 100 + i * 24, 220, 118 + i * 24, lab, cb)
        v.text(LW / 2, 204, "TOKENS %d   OWNED %d/%d" % (round(ctx.shown), ctx.owned, fc.MAX_OWNED_UNITS), 6, 1, "n")


class CopyrightWindow(tk.Toplevel):
    """Popup showing the exact copyright notice."""

    def __init__(self, root, theme):
        """Build the notice window."""
        super().__init__(root)
        self.title("Copyright notice")
        self.configure(bg=theme.panel)
        self.resizable(False, False)
        tk.Label(self, text=fc.COPYRIGHT_TEXT, wraplength=440, justify="left", bg=theme.panel, fg=theme.text,
                 font=(pick_family(root), 12), padx=22, pady=20).pack()
        tk.Button(self, text="Close", command=self.destroy, bg=theme.button, fg=theme.accent,
                  activebackground=mixh(theme.button, theme.text, 0.2), bd=1, padx=14, pady=4).pack(pady=(0, 16))
        self.transient(root)


# ============================================================================= inventory
class SacrificeDialog(tk.Toplevel):
    """Choose exactly 100 other non-legendary ready units to sacrifice."""

    def __init__(self, master, core, target, on_done, theme):
        """Build the selection dialog."""
        super().__init__(master)
        self.title("Sacrifice 100 units for %s" % target["name"])
        self.configure(bg=theme.background)
        self.core, self.target, self.on_done = core, target, on_done
        self.geometry("620x560")
        self.units = [u for u in core.list_units(status="ready", limit=fc.MAX_OWNED_UNITS)
                      if not u["legendary"] and u["id"] != target["id"]]
        self.info = ttk.Label(self, text="")
        self.info.pack(pady=6)
        fr = ttk.Frame(self)
        fr.pack(fill="both", expand=True, padx=8)
        self.tree = ttk.Treeview(fr, columns=("name", "class", "level", "kills"), show="headings", selectmode="extended")
        for c, w in (("name", 220), ("class", 90), ("level", 70), ("kills", 70)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w)
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for u in self.units:
            self.tree.insert("", "end", iid=str(u["id"]), values=(u["name"], u["class"], u["level"], u["kills"]))
        bar = ttk.Frame(self)
        bar.pack(pady=8)
        ttk.Button(bar, text="Select weakest 100", command=self.weakest).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear", command=lambda: self.tree.selection_set(())).pack(side="left", padx=4)
        self.ok = ttk.Button(bar, text="Confirm sacrifice", command=self.confirm)
        self.ok.pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_count())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])
        self.update_count()
        self.transient(master)

    def weakest(self):
        """Select the 100 weakest candidates."""
        ids = [str(u["id"]) for u in reversed(self.units)][:fc.LEGENDARY_SACRIFICE]
        self.tree.selection_set(ids)

    def update_count(self):
        """Show the selection count and gate the confirm button."""
        n = len(self.tree.selection())
        self.info.configure(text="Selected %d / %d" % (n, fc.LEGENDARY_SACRIFICE))
        self.ok.state(["!disabled"] if n == fc.LEGENDARY_SACRIFICE else ["disabled"])

    def confirm(self):
        """Run the sacrifice."""
        ids = [int(i) for i in self.tree.selection()]
        try:
            self.core.make_legendary_sacrifice(self.target["id"], ids)
        except GameError as e:
            messagebox.showerror("Sacrifice", str(e), parent=self)
            return
        self.destroy()
        self.on_done("%s is now Legendary." % self.target["name"])


class InventoryFrame(tk.Frame):
    """Paged, filterable inventory with recruit, upgrade and Legendary actions."""

    PAGE = 100

    def __init__(self, master, gm):
        """Build the inventory screen."""
        th = gm.ctx.theme
        super().__init__(master, bg=th.background)
        self.gm, self.ctx, self.core, self.page = gm, gm.ctx, gm.ctx.core, 0
        body = (pick_family(self), 11)
        head = (pick_family(self, True), 24, "bold")
        top = tk.Frame(self, bg=th.background)
        top.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(top, text="Inventory", font=head, bg=th.background, fg=th.accent).pack(side="left")
        self.tok = tk.Label(top, text="", font=body, bg=th.background, fg=th.text)
        self.tok.pack(side="right")
        fl = tk.Frame(self, bg=th.background)
        fl.pack(fill="x", padx=14, pady=4)
        self.fc_cls, self.fc_lvl, self.fc_st = tk.StringVar(value="All"), tk.StringVar(value="All"), tk.StringVar(value="ready")
        for lab, var, vals in (("Class", self.fc_cls, ["All", "archer", "wizard", "rogue"]),
                               ("Level", self.fc_lvl, ["All", "1", "2", "3", "Legendary"]),
                               ("Status", self.fc_st, ["All", "ready", "dead", "sacrificed"])):
            tk.Label(fl, text=lab, bg=th.background, fg=th.text, font=body).pack(side="left", padx=(8, 2))
            cb = ttk.Combobox(fl, textvariable=var, values=vals, state="readonly", width=10)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self.reset_page())
        ttk.Button(fl, text="<", width=3, command=lambda: self.turn(-1)).pack(side="left", padx=(20, 2))
        self.pg = tk.Label(fl, text="", bg=th.background, fg=th.text, font=body, width=18)
        self.pg.pack(side="left")
        ttk.Button(fl, text=">", width=3, command=lambda: self.turn(1)).pack(side="left")
        cols = ("name", "title", "class", "level", "legendary", "origin", "kills", "status")
        fr = tk.Frame(self, bg=th.background)
        fr.pack(fill="both", expand=True, padx=14, pady=4)
        self.tree = ttk.Treeview(fr, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, (170, 170, 70, 50, 80, 80, 50, 80)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        act = tk.Frame(self, bg=th.background)
        act.pack(fill="x", padx=14, pady=4)
        tk.Label(act, text="Recruit", bg=th.background, fg=th.text, font=body).pack(side="left")
        self.qty = tk.Spinbox(act, from_=1, to=100, width=4, bg=th.panel, fg=th.text, insertbackground=th.text)
        self.qty.pack(side="left", padx=4)
        for cls in fc.PRICES:
            self._btn(act, "%s (%d)" % (cls.title(), fc.PRICES[cls]), lambda c=cls: self.buy(c)).pack(side="left", padx=3)
        act2 = tk.Frame(self, bg=th.background)
        act2.pack(fill="x", padx=14, pady=(0, 4))
        self._btn(act2, "Upgrade selected", self.upgrade).pack(side="left", padx=3)
        self._btn(act2, "Legendary (%d tokens)" % fc.LEGENDARY_COST, self.leg_tokens).pack(side="left", padx=3)
        self._btn(act2, "Legendary (sacrifice %d)" % fc.LEGENDARY_SACRIFICE, self.leg_sac).pack(side="left", padx=3)
        self._btn(act2, "Back", gm.show_menu).pack(side="right", padx=3)
        self.msg = tk.Label(self, text="", bg=th.background, fg=th.accent, font=body, anchor="w")
        self.msg.pack(fill="x", padx=16, pady=(0, 8))
        self._h = self.ctx.engine.add_ticker(self._tick)
        self.reload()

    def _btn(self, parent, text, cmd):
        """Create a themed button."""
        th = self.ctx.theme
        return tk.Button(parent, text=text, command=cmd, bg=th.button, fg=th.accent, activebackground=mixh(th.button, th.text, 0.2),
                         activeforeground=th.accent, bd=1, padx=8, pady=3, cursor="hand2")

    def destroy(self):
        """Remove the ticker."""
        self.ctx.engine.remove(self._h)
        super().destroy()

    def _tick(self, dt):
        """Keep the animated token label current."""
        try:
            self.tok.configure(text="Tokens: %d    Owned: %d/%d" % (round(self.ctx.shown), self.ctx.owned, fc.MAX_OWNED_UNITS))
        except tk.TclError:
            return False
        return True

    def _filters(self):
        """Return (class, level, status) filter values."""
        c = None if self.fc_cls.get() == "All" else self.fc_cls.get()
        lv = self.fc_lvl.get()
        lv = None if lv == "All" else (fc.LEGENDARY_LEVEL if lv == "Legendary" else int(lv))
        st = None if self.fc_st.get() == "All" else self.fc_st.get()
        return c, lv, st

    def reset_page(self):
        """Go to page 0 and reload."""
        self.page = 0
        self.reload()

    def turn(self, d):
        """Change page."""
        self.page = max(0, self.page + d)
        self.reload()

    def reload(self):
        """Fill the tree with the current page."""
        c, lv, st = self._filters()
        total = self.core.count_units(c, lv, st)
        pages = max(1, math.ceil(total / self.PAGE))
        self.page = min(self.page, pages - 1)
        self.tree.delete(*self.tree.get_children())
        for u in self.core.list_units(c, lv, st, self.page * self.PAGE, self.PAGE):
            self.tree.insert("", "end", iid=str(u["id"]), values=(
                u["name"], u.get("title") or "", u["class"], 4 if u["legendary"] else u["level"],
                "Legendary" if u["legendary"] else "", u["origin"], u["kills"], u["status"]))
        self.pg.configure(text="Page %d/%d  (%d units)" % (self.page + 1, pages, total))
        self.ctx.refresh()

    def say(self, s):
        """Show a status message and reload."""
        self.msg.configure(text=s)
        self.reload()

    def sel(self):
        """Return the selected unit id or None."""
        s = self.tree.selection()
        return int(s[0]) if s else None

    def buy(self, cls):
        """Recruit one or several units."""
        try:
            n = max(1, min(100, int(self.qty.get())))
        except ValueError:
            n = 1
        got = 0
        try:
            for _ in range(n):
                self.core.buy_unit(cls)
                got += 1
            self.say("Recruited %d %s." % (got, cls))
        except GameError as e:
            self.say("Recruited %d. %s" % (got, e))

    def _act(self, fn, ok_msg):
        """Run a unit action on the selection."""
        uid = self.sel()
        if uid is None:
            self.msg.configure(text="Select a unit first.")
            return
        try:
            fn(uid)
            self.say(ok_msg)
        except GameError as e:
            self.msg.configure(text=str(e))

    def upgrade(self):
        """Upgrade the selection."""
        self._act(self.core.upgrade_unit, "Upgraded.")

    def leg_tokens(self):
        """Make the selection Legendary with tokens."""
        self._act(self.core.make_legendary_tokens, "Legendary!")

    def leg_sac(self):
        """Open the sacrifice dialog."""
        uid = self.sel()
        if uid is None:
            self.msg.configure(text="Select a unit first.")
            return
        u = self.core.unit(uid)
        if u["legendary"] or u["status"] != "ready":
            self.msg.configure(text="This unit cannot become Legendary.")
            return
        SacrificeDialog(self, self.core, u, self.say, self.ctx.theme)


# ============================================================================= world / wanted screens
class WorldScreen:
    """5x4 campaign map with the Wanted board and New campaign."""

    CW, CH, GX, GY = 44, 42, 4, 20

    def __init__(self, win):
        """Bind to the raid window."""
        self.win, self.ctx = win, win.gm.ctx
        self.msg, self.confirm_t = "", -99.0

    def enter(self, v):
        """Refresh data and play menu music."""
        self.v = v
        self.ctx.ensure_core()
        self.ctx.refresh()
        self.ctx.audio and self.ctx.audio.play_theme("menu")
        self.regions = self.ctx.core.world()

    def update(self, dt):
        """No per-frame state."""

    def region_click(self, r):
        """Start a raid on a hostile region."""
        if r["state"] != "hostile":
            self.msg = "NOT AVAILABLE: %s" % ("CONQUERED" if r["state"] == "conquered" else "UNKNOWN LAND")
            return
        try:
            raid = self.ctx.core.start_raid(r["id"])
        except GameError as e:
            self.msg = str(e)
            return
        self.win.go(RaidScreen(self.win, raid))

    def new_campaign(self):
        """Regenerate the map after a confirming second press."""
        if self.v.t - self.confirm_t > 3:
            self.confirm_t = self.v.t
            self.msg = "PRESS AGAIN TO CONFIRM NEW CAMPAIGN"
            return
        self.ctx.core.new_campaign()
        self.regions = self.ctx.core.world()
        self.msg = "A NEW CAMPAIGN BEGINS"
        self.confirm_t = -99.0

    def draw(self, v):
        """Draw the map, side buttons and hover info."""
        ctx = self.ctx
        v.rect(0, 0, LW, LH, 1)
        draw_header(v, ctx, "CAMPAIGN")
        info = ""
        for r in self.regions:
            x, y = self.GX + r["gx"] * self.CW, self.GY + r["gy"] * self.CH
            st = r["state"]
            blink = "C" if int(v.t * 2) % 2 == 0 else "D"
            v.rect(x + 1, y + 1, x + self.CW - 1, y + self.CH - 1, 3 if st != "conquered" else 7,
                   blink if st == "hostile" else (8 if st == "conquered" else 6))
            if st == "hidden":
                v.text(x + self.CW / 2, y + 16, "?", 6, 2, "center")
            else:
                v.sprite(x + 6, y + 2, "fortress", 1 if st == "conquered" else 0)
                v.text(x + 2, y + 34, r["name"].upper()[:7], 5 if st == "hostile" else 9)
            v.zone(x, y, x + self.CW, y + self.CH, ("reg", r["id"]), lambda r=r: self.region_click(r))
            if v.hover == ("reg", r["id"]):
                info = {"hidden": "UNKNOWN LAND", "hostile": "%s  RAIDS %d  CLICK TO RAID" % (r["fname"], r["raids"] or 0),
                        "conquered": "%s  CONQUERED" % r["fname"]}[st]
        v.button(232, 24, 314, 42, "WANTED", lambda: self.win.go(WantedScreen(self.win)))
        v.button(232, 48, 314, 66, "NEW CAMPAIGN", self.new_campaign)
        v.button(232, 72, 314, 90, "CLOSE", self.win.close)
        done = sum(1 for r in self.regions if r["state"] == "conquered")
        host = sum(1 for r in self.regions if r["state"] == "hostile")
        v.text(232, 104, "CONQUERED %d/%d" % (done, len(self.regions)), 9)
        v.text(232, 116, "HOSTILE %d" % host, "C")
        v.text(232, 128, "RED BLINK = RAID", 6)
        if self.ctx.core.campaign_won():
            v.text(LW / 2, 196, "THE REALM IS CONQUERED!", "D", 1, "n")
        v.text(6, 208, (info or self.msg).upper()[:52], 5)
        v.text(6, 224, "TURN OR SLAY ENEMIES. THEY REMEMBER.", 6)


class WantedScreen:
    """Wanted/Intel board showing only what is known."""

    def __init__(self, win):
        """Bind to the raid window."""
        self.win, self.ctx = win, win.gm.ctx

    def enter(self, v):
        """Load the board."""
        self.rows = self.ctx.core.nem.wanted_board(11)

    def update(self, dt):
        """No per-frame state."""

    def draw(self, v):
        """Draw the board."""
        v.rect(0, 0, LW, LH, 1)
        draw_header(v, self.ctx, "WANTED")
        if not self.rows:
            v.text(LW / 2, 100, "NO ONE IS KNOWN YET. SCOUT OR FIGHT.", 6, 1, "center")
        y = 22
        for k in self.rows:
            nm = k["name"] if k["name"] == "???" else (k["name"] + (" " + k["epithet"] if k.get("epithet") else ""))
            v.text(6, y, ("*" if k["rival"] else " ") + nm.upper()[:26], "C" if k["rival"] else 5)
            tail = k["rank"].upper()[:3] + (" L%d V%d" % (k["level"], k["victories"]) if k["intel"] >= 2 else "") + " I%d" % k["intel"]
            v.text(LW - 6, y, tail, 6, 1, "ne")
            sub = ""
            if k["intel"] >= 2:
                sub = ", ".join(k["traits"])
            if k.get("title"):
                sub = (k["title"] + "  " + sub).strip()
            if k["intel"] >= 3 and k.get("history"):
                sub = k["history"][0][2]
            v.text(14, y + 8, sub.upper()[:48], 6)
            y += 17
        v.button(232, 218, 314, 236, "BACK", lambda: self.win.go(WorldScreen(self.win)))


# ============================================================================= raid screen
FX, FY = 4, 20


class RaidScreen:
    """Scout, deploy and battle on the 12x8 field."""

    def __init__(self, win, raid):
        """Bind to the window and an in-memory raid."""
        self.win, self.ctx, self.core, self.raid = win, win.gm.ctx, win.gm.ctx.core, raid
        win.raid_screen = self
        self.sel = self.tray_sel = None
        self.tray = 0
        self.msgs = ["RAID ON %s." % raid.region["name"].upper(), "SCOUT, THEN DEPLOY UP TO %d UNITS." % fc.MAX_DEPLOY]
        self.duel = None
        self.fx = []
        self.summary = None
        self.avail = []
        self.v = None

    # ---- helpers
    def say(self, s):
        """Add a message line."""
        self.msgs = (self.msgs + [s])[-10:]

    def err(self, e):
        """Show a rejected action."""
        self.say("! " + str(e))

    def ename(self, e):
        """Return the enemy name respecting intel."""
        return e["name"] if e["intel"] >= 1 else "???"

    def refresh_avail(self):
        """Reload deployable units."""
        self.avail = [u for u in self.core.list_units(status="ready", limit=400) if u["id"] not in self.raid.units]
        self.tray = max(0, min(self.tray, max(0, (len(self.avail) - 1) // 8)))

    def enter(self, v):
        """Start battle music and load the tray."""
        self.v = v
        self.ctx.audio and self.ctx.audio.play_theme("battle")
        self.ctx.refresh()
        self.refresh_avail()

    # ---- actions
    def do_scout(self):
        """Spend a token to scout."""
        try:
            self.core.scout(self.raid)
            self.say("SCOUTS STUDIED THE LORD AND A CAPTAIN.")
            self.ctx.audio and self.ctx.audio.sfx("coin")
        except GameError as e:
            self.err(e)
        self.ctx.refresh()

    def to_deploy(self):
        """Go to deployment."""
        self.core.to_deploy(self.raid)
        self.say("PICK UNITS BELOW, THEN CLICK A CELL IN THE ROAD (LEFT 3 COLUMNS).")

    def auto_deploy(self):
        """Fill free cells with the best units."""
        self.core.to_deploy(self.raid)
        free = [(c, r) for c in (2, 1, 0) for r in (3, 4, 2, 5, 1, 6, 0, 7) if not self.core.occupied(self.raid, c, r)]
        for u in list(self.avail):
            if len(self.raid.units) >= fc.MAX_DEPLOY or not free:
                break
            try:
                self.core.deploy(self.raid, u["id"], *free.pop(0))
            except GameError as e:
                self.err(e)
                break
        self.refresh_avail()

    def start_battle(self):
        """Begin battle."""
        try:
            self.core.start_battle(self.raid)
            self.sel = self.tray_sel = None
            self.say("BATTLE! CLICK A UNIT, MOVE, THEN CLICK AN ENEMY IN RANGE.")
        except GameError as e:
            self.err(e)

    def next_round(self):
        """Advance the round or retreat when rounds run out."""
        try:
            if self.core.next_round(self.raid):
                self.say("ROUND %d." % self.raid.round)
                self.sel = None
            else:
                self.say("THE ROUNDS ARE SPENT. RETREAT!")
                self.finish()
        except GameError as e:
            self.err(e)

    def leave(self):
        """Leave before fighting."""
        self.win.raid_screen = None
        self.win.go(WorldScreen(self.win))

    def finish(self):
        """End the raid and show the summary."""
        if self.summary:
            return
        self.summary = self.core.end_raid(self.raid)
        self.ctx.refresh()
        self.sel = None
        a = self.ctx.audio
        if a:
            a.sfx("win" if self.summary["lord_down"] else "lose")

    def back_to_map(self):
        """Return to the campaign map."""
        self.win.raid_screen = None
        self.win.go(WorldScreen(self.win))

    def choose(self, choice, step=False):
        """Turn or kill the defeated enemy."""
        try:
            res = self.core.resolve_win(self.raid, choice, step)
        except GameError as e:
            self.err(e)
            return
        e = res["enemy"]
        self.fx.append(dict(kind="defeat", cell=(e["col"], e["row"]), name=e["rank"], mirror=True, t0=self.v.t, dur=0.5))
        if choice == "turn" and res["line"]:
            self.say('%s: "%s"' % (e["name"], res["line"]))
        self.say("%s %s. +%d TOKENS" % (e["name"], "JOINS YOU" if choice == "turn" else "IS SLAIN", res["bounty"]))
        self.ctx.audio and self.ctx.audio.sfx("coin")
        self.ctx.refresh()
        self.refresh_avail()
        if self.core.raid_over(self.raid):
            self.finish()

    def begin_duel(self, uid, eid):
        """Roll an attack; the animation reveals the result."""
        raid = self.raid
        e, u = raid.enemies[eid], raid.units[uid]
        en = self.ename(e)
        try:
            d = self.core.attack(raid, uid, eid)
        except GameError as ex:
            self.err(ex)
            return
        self.say('%s: "%s"' % (en, d["pre"]))
        self.duel = dict(d=d, t=3000.0 if self.ctx.theme.reduce_motion else 0.0, u=u, en=en, ce=(e["col"], e["row"]),
                         cu=(u["col"], u["row"]), rank=e["rank"], rng=random.Random(d["roll"]))
        self.sel = None

    def finish_duel(self):
        """Apply the visual and message results of a duel."""
        du = self.duel
        d, u = du["d"], du["u"]
        self.duel = None
        self.fx.append(dict(kind="spark", cell=du["ce"], t0=self.v.t, dur=0.3))
        if d["win"]:
            self.say('%s: "%s"' % (du["en"], d["line"]))
            self.say("%s WINS. CHOOSE: TURN OR KILL." % u["name"])
            self.ctx.audio and self.ctx.audio.sfx("hit")
        else:
            self.fx.append(dict(kind="defeat", cell=du["cu"], name=u["class"], mirror=False, t0=self.v.t, dur=0.5, leg=bool(u["legendary"])))
            self.say('%s: "%s"' % (du["en"], d["line"]))
            self.say("%s %s." % (u["name"], "RETURNS TO INVENTORY" if d["survived"] else "FALLS FOR GOOD"))
            self.ctx.audio and self.ctx.audio.sfx("lose")
        self.ctx.refresh()
        self.refresh_avail()
        if not d["win"] and self.core.raid_over(self.raid):
            self.finish()

    def cell_click(self, c, r):
        """Handle a click on a field cell."""
        raid = self.raid
        if self.duel or self.summary:
            return
        occ = self.core.occupied(raid, c, r)
        try:
            if raid.phase in ("scout", "deploy"):
                if occ and occ[0] == "unit":
                    self.core.undeploy(raid, occ[1])
                    self.refresh_avail()
                elif occ is None and self.tray_sel is not None:
                    self.core.deploy(raid, self.tray_sel, c, r)
                    self.tray_sel = None
                    self.refresh_avail()
            elif raid.phase == "battle" and not raid.pending:
                if occ and occ[0] == "unit":
                    self.sel = occ[1]
                elif occ and occ[0] == "enemy" and self.sel is not None:
                    self.begin_duel(self.sel, occ[1])
                elif occ is None and self.sel is not None:
                    self.core.move(raid, self.sel, c, r)
        except GameError as e:
            self.err(e)

    # ---- per frame
    def update(self, dt):
        """Advance the duel timeline and effects."""
        if self.duel:
            self.duel["t"] += dt
            if self.duel["t"] >= 2100:
                self.finish_duel()
        if self.v:
            self.fx = [f for f in self.fx if self.v.t - f["t0"] < f["dur"]]

    def enemy_lines(self, e):
        """Info lines for an enemy limited by intel."""
        i = e["intel"]
        L = [(e["name"].upper()[:19] if i >= 1 else "???", 5)]
        if i >= 1 and e["epithet"]:
            L.append((e["epithet"].upper()[:19], 6))
        L.append(("%s%s" % (e["rank"].upper(), (" LV%d" % e["level"]) if i >= 2 else ""), 9))
        if i >= 2:
            for ln in textwrap.wrap(", ".join(e["traits"]).upper(), 19):
                L.append((ln, "D"))
            L.append(("VICTORIES %d" % e["victories"], 6))
        if i >= 1 and e["title"]:
            for ln in textwrap.wrap(e["title"].upper(), 19):
                L.append((ln, "C"))
        if i >= 1 and e["scars"]:
            L.append(("SCARS %d" % e["scars"], "C"))
        if e["rival"] and i >= 1:
            L.append(("** RIVAL x3 **", "C"))
        L.append(("INTEL " + "*" * i + "-" * (3 - i), 6))
        return L

    def side_lines(self, v):
        """Build the side-panel text."""
        raid, L = self.raid, [("PHASE: %s R%d/%d" % (self.raid.phase.upper(), self.raid.round, fc.MAX_ROUNDS), "D")]
        occ = None
        if isinstance(v.hover, tuple) and v.hover[0] == "cell":
            occ = self.core.occupied(raid, v.hover[1], v.hover[2])
        if occ and occ[0] == "enemy":
            e = raid.enemies[occ[1]]
            L += self.enemy_lines(e)
            u = raid.units.get(self.sel) if self.sel is not None else None
            if u and raid.phase == "battle":
                L.append(("ODDS %d%%" % self.core.win_chance_for(u, e), "E"))
        elif occ and occ[0] == "unit":
            u = raid.units[occ[1]]
            L += [(u["name"].upper()[:19], 5), ("%s LV%s" % (u["class"].upper(), "L" if u["legendary"] else u["level"]), 9),
                  ("KILLS %d" % u["kills"], 6)]
        elif v.hover and isinstance(v.hover, tuple) and v.hover[0] == "tray" and v.hover[1] < len(self.avail[self.tray * 8:self.tray * 8 + 8]):
            u = self.avail[self.tray * 8 + v.hover[1]]
            L += [(u["name"].upper()[:19], 5), ("%s LV%s" % (u["class"].upper(), "L" if u["legendary"] else u["level"]), 9),
                  ("KILLS %d" % u["kills"], 6)]
        else:
            tips = {"scout": ["SCOUTING RAISES", "INTEL ON THE LORD", "AND ONE CAPTAIN."],
                    "deploy": ["PICK A UNIT BELOW,", "CLICK A ROAD CELL.", "CLICK A UNIT TO", "REMOVE IT."],
                    "battle": ["MOVE THEN ATTACK.", "ARCHER MV2 RNG3", "WIZARD MV2 RNG2", "ROGUE  MV3 RNG1",
                               "LEVEL SETS ODDS."], "done": ["RAID OVER."]}[raid.phase]
            L += [(t, 6) for t in tips]
        return L

    def draw(self, v):
        """Draw the whole raid screen."""
        ctx, raid, S, core = self.ctx, self.raid, v.S, self.core
        v.rect(0, 0, LW, LH, 1)
        draw_header(v, ctx, "RAID " + raid.region["name"].upper()[:10])
        v.create_image(FX * S, FY * S, image=ctx.rend.field(S), anchor="nw")
        v.rect(FX - 1, FY - 1, FX + fc.FIELD_COLS * 16 + 1, FY + fc.FIELD_ROWS * 16 + 1, None, 8)
        tick = int(v.t * 8)
        u_sel = raid.units.get(self.sel) if self.sel is not None else None
        pend = raid.pending["enemy_id"] if raid.pending else None
        if u_sel and not u_sel["spent"] and raid.phase == "battle" and not raid.pending and not self.duel:
            mv = fc.ROLES[u_sel["class"]]["move"]
            if not u_sel["moved"] and not u_sel["attacked"]:
                for c in range(fc.FIELD_COLS):
                    for r in range(fc.FIELD_ROWS):
                        if max(abs(c - u_sel["col"]), abs(r - u_sel["row"])) <= mv and not core.occupied(raid, c, r):
                            v.rect(FX + c * 16, FY + r * 16, FX + c * 16 + 16, FY + r * 16 + 16, 8, None, "gray25")
            if not u_sel["attacked"]:
                rg = fc.ROLES[u_sel["class"]]["rng"]
                for e in raid.enemies.values():
                    if max(abs(e["col"] - u_sel["col"]), abs(e["row"] - u_sel["row"])) <= rg:
                        v.rect(FX + e["col"] * 16 + 1, FY + e["row"] * 16 + 1, FX + e["col"] * 16 + 15, FY + e["row"] * 16 + 15, None, "C")
        for e in raid.enemies.values():
            x, y = FX + e["col"] * 16, FY + e["row"] * 16
            v.sprite(x, y, e["rank"], 6 if e["id"] == pend else (tick + e["id"]) % 2, True)
            for k in range(e["level"] if e["intel"] >= 2 else 0):
                v.rect(x + 3 + k * 4, y + 14, x + 5 + k * 4, y + 16, 9)
            if e["rival"] and e["intel"] >= 1:
                v.rect(x, y, x + 16, y + 16, None, "C")
        for u in raid.units.values():
            if u["spent"]:
                continue
            x, y = FX + u["col"] * 16, FY + u["row"] * 16
            atk = self.duel and self.duel["u"]["id"] == u["id"]
            v.sprite(x, y, u["class"], 2 if atk else tick % 2, False, bool(u["legendary"]))
            for k in range(4 if u["legendary"] else u["level"]):
                v.rect(x + 2 + k * 3, y + 14, x + 4 + k * 3, y + 16, "D" if u["legendary"] else 9)
            if u["id"] == self.sel:
                v.rect(x, y, x + 16, y + 16, None, "D")
            elif u["attacked"] and raid.phase == "battle":
                v.rect(x, y, x + 16, y + 16, 1, None, "gray50")
        for f in self.fx:
            c, r = f["cell"]
            x, y = FX + c * 16, FY + r * 16
            age = v.t - f["t0"]
            if f["kind"] == "spark":
                v.sprite(x, y, "spark", min(2, int(age * 12)))
            else:
                v.sprite(x, y, f["name"], 4 + min(2, int(age * 6)), f["mirror"], f.get("leg", False))
        for c in range(fc.FIELD_COLS):
            for r in range(fc.FIELD_ROWS):
                v.zone(FX + c * 16, FY + r * 16, FX + c * 16 + 16, FY + r * 16 + 16, ("cell", c, r), lambda c=c, r=r: self.cell_click(c, r))
        v.rect(200, 20, 316, 148, 3, 6)
        for i, (tx, col) in enumerate(self.side_lines(v)[:13]):
            v.text(204, 24 + i * 9, tx, col)
        v.rect(4, 152, 196, 190, 3, 6)
        wrapped = []
        for m in self.msgs[-6:]:
            wrapped += textwrap.wrap(m.upper(), 31) or [""]
        for i, ln in enumerate(wrapped[-4:]):
            v.text(8, 155 + i * 9, ln, 5)
        locked = bool(self.duel or self.summary)
        if raid.phase in ("scout", "deploy"):
            page = self.avail[self.tray * 8:self.tray * 8 + 8]
            v.button(4, 194, 16, 214, "<", lambda: setattr(self, "tray", max(0, self.tray - 1)), self.tray > 0, "tray_l")
            v.button(184, 194, 196, 214, ">", lambda: setattr(self, "tray", self.tray + 1), (self.tray + 1) * 8 < len(self.avail), "tray_r")
            for i, u in enumerate(page):
                x = 20 + i * 20
                if u["id"] == self.tray_sel:
                    v.rect(x - 2, 194, x + 18, 214, None, "D")
                v.sprite(x, 195, u["class"], tick % 2, False, bool(u["legendary"]))
                v.text(x + 8, 213, "L" if u["legendary"] else str(u["level"]), "D" if u["legendary"] else 6, 1, "n")
                v.zone(x - 2, 194, x + 18, 214, ("tray", i), lambda uid=u["id"]: setattr(self, "tray_sel", uid))
            v.text(8, 226, "DEPLOYED %d/%d   READY %d" % (len(raid.units), fc.MAX_DEPLOY, len(self.avail)), 6)
        elif raid.phase == "battle":
            if raid.pending:
                d = raid.pending
                e = raid.enemies.get(d["enemy_id"])
                b = fc.BOUNTY[e["rank"]] * (fc.RIVAL_MULT if e["rival"] else 1) if e else 0
                v.button(4, 194, 64, 214, "TURN", lambda: self.choose("turn"), not locked)
                v.button(68, 194, 128, 214, "KILL", lambda: self.choose("kill"), not locked)
                v.button(132, 194, 196, 214, "KILL+STEP", lambda: self.choose("kill", True), not locked)
                v.text(8, 222, "BOUNTY %d TOKENS%s" % (b, " (RIVAL)" if e and e["rival"] else ""), "D")
            else:
                n = len(core.active_units(raid))
                v.text(8, 198, "UNITS ON FIELD %d" % n, 9)
                v.text(8, 210, "EACH UNIT: MOVE THEN ATTACK ONCE", 6)
                v.text(8, 222, "ROUND %d OF %d" % (raid.round, fc.MAX_ROUNDS), 6)
        acts = {"scout": [("SCOUT (-%d)" % fc.SCOUT_COST, self.do_scout, ctx.tokens >= fc.SCOUT_COST), ("TO DEPLOY", self.to_deploy, True),
                          ("LEAVE", self.leave, True)],
                "deploy": [("AUTO DEPLOY", self.auto_deploy, bool(self.avail)), ("START BATTLE", self.start_battle, bool(raid.units)),
                           ("LEAVE", self.leave, True)],
                "battle": [("NEXT ROUND", self.next_round, not raid.pending), ("RETREAT", self.finish, not raid.pending)],
                "done": [("BACK TO MAP", self.back_to_map, True)]}[raid.phase]
        for i, (lab, cb, en) in enumerate(acts):
            v.button(200, 152 + i * 26, 316, 174 + i * 26, lab, cb, en and not locked or (raid.phase == "done" and not self.duel))
        if self.duel:
            self.draw_duel(v)
        if self.summary:
            self.draw_summary(v)

    def draw_duel(self, v):
        """Draw the animated odds bar and dice."""
        du, d, t = self.duel, self.duel["d"], self.duel["t"]
        v.rect(40, 46, 280, 176, 3, "D")
        v.sprite(54, 56, du["u"]["class"], 2, False, bool(du["u"]["legendary"]))
        v.sprite(250, 56, du["rank"], 2, True)
        v.text(LW / 2, 56, "DUEL!", "D", 2, "n")
        v.text(LW / 2, 76, "%s VS %s" % (du["u"]["name"][:10], du["en"][:10]), 5, 1, "n")
        v.text(60, 92, "ODDS %d%%  (ROLL D100, WIN IF <= %d)" % (d["chance"], d["chance"]), 9)
        bx0, bx1, by0, by1 = 60, 260, 104, 116
        v.rect(bx0, by0, bx1, by1, 1, 6)
        v.rect(bx0, by0, bx0 + (bx1 - bx0) * d["chance"] / 100.0, by1, 8)
        settle = min(1.0, max(0.0, (t - 900) / 300.0))
        wob = abs(((t / 250.0) % 2) - 1) * 100
        pos = wob * (1 - settle) + d["roll"] * settle
        shown = int(pos) if t < 1200 else d["roll"]
        mx = bx0 + (bx1 - bx0) * max(1, min(100, pos)) / 100.0
        v.rect(mx - 1, by0 - 3, mx + 1, by1 + 3, "D")
        v.text(LW / 2, 124, "%d" % max(1, shown), 5, 3, "n")
        if t >= 1200:
            if d["win"]:
                v.text(LW / 2, 152, "HIT! THE ENEMY IS DEFEATED", "E", 1, "n")
            else:
                v.text(LW / 2, 148, "MISS. SURVIVE ROLL %d / %d%%: %s" % (
                    d["survive_roll"], d["survive_chance"], "SURVIVED" if d["survived"] else "FELL"), "C", 1, "n")
                v.text(LW / 2, 160, "THE ENEMY WINS THE DUEL", "C", 1, "n")

    def draw_summary(self, v):
        """Draw the end-of-raid overlay."""
        s = self.summary
        v.rect(50, 34, 270, 212, 3, "D")
        v.text(LW / 2, 42, "FORTRESS FALLEN!" if s["lord_down"] else "RAID ENDED", "D", 2, "n")
        lines = ["BOUNTY +%d TOKENS" % s["bounty"], "SLAIN %d  TURNED %d  LOST %d" % (s["kills"], s["turned"], s["losses"])]
        if s["dead"]:
            lines.append("FALLEN: " + ", ".join(s["dead"]))
        lines += s["events"]
        wr = []
        for ln in lines:
            wr += textwrap.wrap(ln.upper(), 34) or [""]
        for i, ln in enumerate(wr[:14]):
            v.text(58, 64 + i * 9, ln, 5)
        v.button(110, 192, 210, 208, "BACK TO MAP", self.back_to_map)


class RaidWindow(tk.Toplevel):
    """Popup window holding the campaign map and raids."""

    def __init__(self, gm):
        """Open the popup on the world map."""
        super().__init__(gm.app.root)
        self.gm = gm
        self.raid_screen = None
        self.title("For Thy Lord")
        self.resizable(False, False)
        self.configure(bg=gm.ctx.rend.pal[1])
        self.view = PixelView(self, gm.ctx, gm.S)
        self.view.pack()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.view.set_screen(WorldScreen(self))

    def go(self, screen):
        """Switch screens with a transition."""
        self.view.go(screen)

    def close(self):
        """Persist an unfinished battle as a retreat, then close."""
        rs = self.raid_screen
        try:
            if rs and rs.raid.phase == "battle" and not rs.raid.done:
                if rs.raid.pending:
                    rs.core.resolve_win(rs.raid, "kill")
                rs.core.end_raid(rs.raid)
        except Exception:
            pass
        self.gm.raidwin = None
        if self.gm.ctx.audio:
            self.gm.ctx.audio.play_theme("menu")
        self.gm.ctx.refresh()
        self.destroy()


# ============================================================================= game menu controller
class GameMenu:
    """The hidden second main menu embedded over the Routina window."""

    def __init__(self, app, ctx, on_close):
        """Create the overlay frame and show the menu."""
        self.app, self.ctx, self.on_close = app, ctx, on_close
        root = app.root
        self.saved_geo = root.geometry()
        big = root.winfo_screenwidth() >= 1000 and root.winfo_screenheight() >= 830
        self.S = 3 if big else 2
        if big:
            root.geometry("%dx%d" % (LW * 3 + 40, LH * 3 + 80))
        self.raidwin = None
        self.frame = tk.Frame(root, bg=ctx.rend.pal[1])
        self.frame._keep = True
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.frame.lift()
        self.inner = tk.Frame(self.frame, bg=ctx.rend.pal[1])
        self.inner.place(relx=0.5, rely=0.5, anchor="center")
        self.child = None
        self._show("menu")

    def _show(self, kind):
        """Replace the inner screen."""
        if self.child is not None:
            self.child.destroy()
        if kind == "menu":
            v = PixelView(self.inner, self.ctx, self.S)
            v.pack()
            v.set_screen(MenuScreen(self))
            self.child = v
        else:
            self.ctx.ensure_core()
            self.child = InventoryFrame(self.inner, self)
            self.child.pack()

    def show_menu(self):
        """Transition to the menu."""
        self.ctx.engine.transition(self.frame, lambda: self._show("menu"))

    def inventory(self):
        """Transition to the inventory."""
        self.ctx.engine.transition(self.frame, lambda: self._show("inv"))

    def copyright(self):
        """Open the copyright window."""
        CopyrightWindow(self.app.root, self.ctx.theme)

    def play(self):
        """Open the game popup."""
        if self.raidwin is not None:
            try:
                self.raidwin.lift()
                return
            except tk.TclError:
                self.raidwin = None
        self.ctx.ensure_core()
        self.raidwin = RaidWindow(self)

    def close(self):
        """Close everything, stop audio and timers, and return to Routina."""
        if self.raidwin is not None:
            try:
                self.raidwin.close()
            except Exception:
                pass
        if self.ctx.audio:
            self.ctx.audio.stop()
        try:
            if self.child is not None:
                self.child.destroy()
            self.frame.destroy()
            self.app.root.geometry(self.saved_geo)
        except tk.TclError:
            pass
        self.on_close()


# ============================================================================= Routina-compatible standalone host
class SettingsWindow(tk.Toplevel):
    """Settings screen for the standalone Routina-compatible task host."""

    def __init__(self, app):
        """Build settings controls and live chart preview."""
        super().__init__(app.root)
        self.app = app
        self.title("Routina Settings")
        self.geometry("850x690")
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.configure(bg=app.theme.background)
        self._build()
        self.theme_token = app.theme.subscribe(self.apply_theme)
        self.apply_theme(app.theme)

    def _build(self):
        """Create color, preference, path, chart, and data controls."""
        th = self.app.theme
        self.body = tk.Frame(self, padx=14, pady=12)
        self.body.pack(fill="both", expand=True)
        tk.Label(self.body, text="Settings", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        colors = tk.LabelFrame(self.body, text="Theme colours", padx=8, pady=6)
        colors.pack(fill="x", pady=6)
        self.color_buttons = {}
        row = tk.Frame(colors); row.pack(fill="x")
        for key in fc.THEME_KEYS:
            b = tk.Button(row, text=key.title(), command=lambda k=key: self.pick_color(k))
            b.pack(side="left", padx=3, pady=3, fill="x", expand=True)
            self.color_buttons[key] = b
        tk.Button(colors, text="Reset to default", command=self.reset_theme).pack(anchor="e")
        flags = tk.Frame(self.body); flags.pack(fill="x", pady=4)
        self.mute_var = tk.BooleanVar(value=th.mute)
        self.motion_var = tk.BooleanVar(value=th.reduce_motion)
        tk.Checkbutton(flags, text="Mute", variable=self.mute_var, command=self.save_flags).pack(side="left")
        tk.Checkbutton(flags, text="Reduce motion", variable=self.motion_var, command=self.save_flags).pack(side="left", padx=12)
        pathbox = tk.LabelFrame(self.body, text="Data folder", padx=8, pady=6); pathbox.pack(fill="x", pady=6)
        self.path_var = tk.StringVar(value=str(Path(self.app.db.path).parent))
        tk.Entry(pathbox, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        tk.Button(pathbox, text="Browse…", command=self.browse).pack(side="left", padx=4)
        tk.Button(pathbox, text="Apply / migrate", command=self.apply_path).pack(side="left")
        chartbox = tk.LabelFrame(self.body, text="Task completions", padx=8, pady=5); chartbox.pack(fill="both", expand=True, pady=5)
        line = tk.Frame(chartbox); line.pack(fill="x")
        self.chart_var = tk.StringVar(value=self.app.db.get_config("chart_type", "bar"))
        ttk.Combobox(line, textvariable=self.chart_var, values=("bar", "line", "pie", "histogram"), state="readonly", width=14).pack(side="left")
        tk.Button(line, text="Update chart", command=self.draw_chart).pack(side="left", padx=6)
        tk.Button(line, text="View data", command=self.view_data).pack(side="left")
        self.chart_frame = tk.Frame(chartbox); self.chart_frame.pack(fill="both", expand=True)
        if HAVE_MPL:
            self.fig = Figure(figsize=(6, 2.2), dpi=90)
            self.ax = self.fig.add_subplot(111)
            self.chart = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
            self.chart.get_tk_widget().pack(fill="both", expand=True)
            self.draw_chart()
        else:
            tk.Label(self.chart_frame, text="Install matplotlib to display charts.").pack(pady=25)
        tk.Button(self.body, text="Open secret game", command=self.open_game).pack(anchor="e", pady=4)

    def apply_theme(self, theme):
        """Apply the current theme to this window and its controls."""
        bg, fg, panel, button = theme.background, theme.text, theme.panel, theme.button
        try:
            self.configure(bg=bg)
            for w in (self.body,): w.configure(bg=bg)
            for w in self.winfo_children(): self._skin(w, bg, fg, panel, button)
            for key, b in self.color_buttons.items(): b.configure(bg=theme.colors[key], fg=fg)
        except tk.TclError:
            pass

    def _skin(self, widget, bg, fg, panel, button):
        """Recursively recolor common Tk widgets."""
        try:
            if isinstance(widget, (tk.Frame, tk.LabelFrame)): widget.configure(bg=panel if isinstance(widget, tk.LabelFrame) else bg)
            elif isinstance(widget, tk.Label): widget.configure(bg=bg, fg=fg)
            elif isinstance(widget, (tk.Button, tk.Checkbutton)): widget.configure(bg=button, fg=fg, activebackground=panel, activeforeground=fg)
            elif isinstance(widget, tk.Entry): widget.configure(bg=panel, fg=fg, insertbackground=fg)
        except tk.TclError:
            pass
        for child in widget.winfo_children(): self._skin(child, bg, fg, panel, button)

    def pick_color(self, key):
        """Open a picker and apply a selected theme colour immediately."""
        color = colorchooser.askcolor(color=self.app.theme.colors[key], parent=self, title="Choose " + key)
        if color and color[1] and self.app.theme.set_color(key, color[1]):
            self.app.db.save_theme(self.app.theme)

    def reset_theme(self):
        """Restore the default theme and persist it."""
        self.app.theme.reset(); self.app.db.save_theme(self.app.theme)

    def save_flags(self):
        """Persist mute and reduce-motion preferences."""
        self.app.theme.set_flag("mute", self.mute_var.get())
        self.app.theme.set_flag("reduce_motion", self.motion_var.get())
        self.app.db.save_theme(self.app.theme)
        self.app.db.set_config("mute", str(int(self.mute_var.get())))
        self.app.db.set_config("reduce_motion", str(int(self.motion_var.get())))
        if self.app.game_ctx and self.app.game_ctx.audio:
            self.app.game_ctx.audio._on_theme(self.app.theme)

    def browse(self):
        """Choose an existing data folder."""
        p = filedialog.askdirectory(parent=self, initialdir=self.path_var.get())
        if p: self.path_var.set(p)

    def apply_path(self):
        """Validate a new data folder, offer migration, then switch databases."""
        target = self.path_var.get().strip()
        ok, msg = fc.validate_data_path(target)
        if not ok:
            messagebox.showerror("Invalid data folder", msg, parent=self); return
        old = Path(self.app.db.path).parent
        if Path(target).resolve() != old.resolve():
            if not messagebox.askyesno("Move Routina data?", "Migrate the existing database to this folder?", parent=self): return
            try:
                fc.migrate_data(old, target)
                replacement = fc.Database(fc.db_file(target))
                self.app.db.close(); self.app.db = replacement
                self.app.fallback_data_dir = str(old)
                self.app._bind_tasks()
                fc.save_bootstrap(self.app.app_dir, target)
                self.path_var.set(target)
            except Exception as exc:
                messagebox.showerror("Migration failed", str(exc), parent=self); return
        self.app.db.set_config("data_path_note", target)

    def draw_chart(self):
        """Render the selected completion chart and remember its type."""
        if not HAVE_MPL: return
        kind = self.chart_var.get()
        self.app.db.set_config("chart_type", kind)
        data = fc.completion_series(self.app.db, 30)
        labels = [str(x[0])[-5:] for x in data]; vals = [x[1] for x in data]
        self.ax.clear()
        if vals:
            if kind == "line": self.ax.plot(labels, vals, marker="o")
            elif kind == "pie": self.ax.pie(vals, labels=labels, autopct="%1.0f%%")
            elif kind == "histogram": self.ax.hist(vals, bins=min(10, max(1, len(set(vals)))))
            else: self.ax.bar(labels, vals)
        else: self.ax.text(.5, .5, "No completions yet", ha="center", va="center", transform=self.ax.transAxes)
        self.ax.set_title("Task completions by date")
        if kind != "pie": self.ax.tick_params(axis="x", labelrotation=35, labelsize=7)
        self.fig.tight_layout(); self.chart.draw_idle()

    def view_data(self):
        """Open the whitelisted sortable data viewer and CSV export."""
        DataViewer(self, self.app.db)

    def open_game(self):
        """Open the hidden game menu."""
        self.app.open_game()


class DataViewer(tk.Toplevel):
    """Sortable, explicitly whitelisted task and configuration viewer."""

    def __init__(self, parent, db):
        """Build the table and dataset selector."""
        super().__init__(parent); self.db = db; self.title("Routina data")
        self.geometry("720x420")
        bar = ttk.Frame(self); bar.pack(fill="x", padx=8, pady=8)
        self.dataset = tk.StringVar(value="Tasks")
        ttk.Combobox(bar, textvariable=self.dataset, values=fc.DATASETS, state="readonly").pack(side="left")
        ttk.Button(bar, text="Show", command=self.refresh).pack(side="left", padx=5)
        ttk.Button(bar, text="Export CSV", command=self.export).pack(side="right")
        self.tree = ttk.Treeview(self, show="headings"); self.tree.pack(fill="both", expand=True, padx=8, pady=6)
        self.refresh()

    def refresh(self):
        """Load the selected safe dataset into sortable columns."""
        cols, rows = fc.viewer_rows(self.db, self.dataset.get())
        self.tree.delete(*self.tree.get_children()); self.tree.configure(columns=cols)
        for col in cols:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort(c, False))
            self.tree.column(col, width=max(100, 600 // max(1, len(cols))))
        for row in rows: self.tree.insert("", "end", values=row)

    def sort(self, col, reverse):
        """Sort visible rows by the selected column."""
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        for _, key in sorted(data, reverse=reverse): self.tree.move(key, "", "end")
        self.tree.heading(col, command=lambda: self.sort(col, not reverse))

    def export(self):
        """Export the selected whitelisted dataset to CSV."""
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            try: fc.export_csv(self.db, self.dataset.get(), path)
            except OSError as exc: messagebox.showerror("Export failed", str(exc), parent=self)


class RoutinaApp:
    """Minimal standalone task-list host compatible with the game hook."""

    def __init__(self, root=None):
        """Open persistent task data and build the Routina window."""
        self.root = root or tk.Tk(); self.app_dir = Path(__file__).resolve().parent
        self.db = fc.open_database(self.app_dir)
        self.fallback_data_dir = str(self.app_dir)
        self.theme = self.db.load_theme()
        self.theme.set_flag("mute", self.db.get_config("mute", "0") == "1")
        self.theme.set_flag("reduce_motion", self.db.get_config("reduce_motion", "0") == "1")
        self.game_ctx = None; self.game_menu = None
        self.root.title("Routina Plus"); self.root.geometry("560x620")
        self._build(); self.theme.subscribe(self.apply_theme); self.apply_theme(self.theme); self._bind_tasks()
        if self.db.last_warning: self.root.after(400, lambda: messagebox.showwarning("Data warning", self.db.last_warning, parent=self.root))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(5000, self._check_data_path)

    def _check_data_path(self):
        """Fall back to the previous usable database folder if the active one fails."""
        if not self.root.winfo_exists(): return
        current = str(Path(self.db.path).parent)
        ok, reason = fc.validate_data_path(current)
        if not ok:
            fallback_ok, fallback_reason = fc.validate_data_path(self.fallback_data_dir)
            if fallback_ok:
                try:
                    replacement = fc.Database(fc.db_file(self.fallback_data_dir))
                    self.db.close(); self.db = replacement; self._bind_tasks(); self.refresh_tasks()
                    fc.save_bootstrap(self.app_dir, self.fallback_data_dir)
                    messagebox.showwarning("Data folder unavailable", "The current data folder became unavailable (%s). Routina returned to %s." % (reason, self.fallback_data_dir), parent=self.root)
                except Exception as exc:
                    messagebox.showerror("Data folder unavailable", str(exc), parent=self.root)
            else:
                messagebox.showerror("Data folder unavailable", "Current folder: %s. Previous folder: %s." % (reason, fallback_reason), parent=self.root)
        self.root.after(5000, self._check_data_path)

    def _build(self):
        """Build the task list and application controls."""
        self.outer = tk.Frame(self.root, padx=18, pady=14); self.outer.pack(fill="both", expand=True)
        self.title_label = tk.Label(self.outer, text="Routina", font=("Segoe UI", 22, "bold")); self.title_label.pack(anchor="w")
        controls = tk.Frame(self.outer); controls.pack(fill="x", pady=10)
        self.entry = tk.Entry(controls); self.entry.pack(side="left", fill="x", expand=True); self.entry.bind("<Return>", lambda _e: self.add_task())
        tk.Button(controls, text="Add task", command=self.add_task).pack(side="left", padx=5)
        self.tasks = ttk.Treeview(self.outer, columns=("done", "task", "created"), show="headings", selectmode="browse")
        for col, label, width in (("done", "Done", 55), ("task", "Task", 330), ("created", "Created", 110)):
            self.tasks.heading(col, text=label); self.tasks.column(col, width=width, anchor="w")
        self.tasks.pack(fill="both", expand=True); self.tasks.bind("<Double-1>", lambda _e: self.toggle_selected())
        row = tk.Frame(self.outer); row.pack(fill="x", pady=8)
        tk.Button(row, text="Complete / reopen", command=self.toggle_selected).pack(side="left")
        tk.Button(row, text="Delete", command=self.delete_selected).pack(side="left", padx=6)
        tk.Button(row, text="Settings", command=self.settings).pack(side="right")
        self.status = tk.Label(self.outer, anchor="w"); self.status.pack(fill="x")

    def apply_theme(self, theme):
        """Restyle the task host whenever theme values change."""
        try:
            self.root.configure(bg=theme.background)
            for w in (self.outer,): w.configure(bg=theme.background)
            for child in self.outer.winfo_children(): SettingsWindow._skin(self, child, theme.background, theme.text, theme.panel, theme.button)
            self.title_label.configure(fg=theme.accent)
            style_ttk(self.root, theme)
        except tk.TclError: pass

    def _bind_tasks(self):
        """Bind the single completion hook to this open database."""
        game_hooks.bind(self.db)

    def refresh_tasks(self):
        """Reload task rows from SQLite."""
        self.tasks.delete(*self.tasks.get_children())
        for r in self.db.conn.execute("SELECT id,name,completed,created_at FROM tasks ORDER BY completed,id"):
            self.tasks.insert("", "end", iid=str(r[0]), values=("✓" if r[2] else "□", r[1], r[3][:10]))
        self.status.configure(text="%d tokens earned from completed tasks" % self.db.balance()["total_earned"])

    def add_task(self):
        """Add a task and refresh the list."""
        name = self.entry.get().strip()
        if not name: return
        with self.db.tx() as c: c.execute("INSERT INTO tasks(name,created_at) VALUES(?,?)", (name, fc.now()))
        self.entry.delete(0, "end"); self.refresh_tasks()

    def toggle_selected(self):
        """Toggle completion and award once for the task and completion date."""
        sel = self.tasks.selection()
        if not sel: return
        tid = int(sel[0]); row = self.db.conn.execute("SELECT completed FROM tasks WHERE id=?", (tid,)).fetchone()
        completed = not bool(row[0]); today = date.today().isoformat()
        with self.db.tx() as c:
            c.execute("UPDATE tasks SET completed=? WHERE id=?", (int(completed), tid))
            if completed: c.execute("INSERT OR IGNORE INTO task_completions(task_id,completion_date) VALUES(?,?)", (tid, today))
        if completed: game_hooks.on_task_completed("%d:%s" % (tid, today))
        self.refresh_tasks()

    def delete_selected(self):
        """Delete the selected task and its completion history."""
        sel = self.tasks.selection()
        if not sel: return
        tid = int(sel[0])
        with self.db.tx() as c:
            c.execute("DELETE FROM task_completions WHERE task_id=?", (tid,)); c.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.refresh_tasks()

    def settings(self):
        """Open the Settings screen."""
        SettingsWindow(self)

    def open_game(self):
        """Show the hidden game menu with shared theme and persistent database."""
        if self.game_menu: return
        engine = AnimEngine(self.root, self.theme)
        self.game_ctx = GameCtx(self.root, self.theme, self.db, engine)
        self.game_ctx.audio = AudioPlayer(self.theme)
        self.game_ctx.audio.play_theme("menu")
        self.game_menu = GameMenu(self, self.game_ctx, self._game_closed)

    def _game_closed(self):
        """Return focus to Routina after the game closes."""
        self.game_menu = None; self.game_ctx = None; self.root.deiconify(); self.root.lift()

    def close(self):
        """Stop game services and close the database cleanly."""
        if self.game_menu: self.game_menu.close()
        self.db.close(); self.root.destroy()


def main():
    """Launch the standalone Routina Plus application."""
    if "--selftest" in sys.argv:
        return 0 if fc.run_all() else 1
    app = RoutinaApp(); app.root.mainloop(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
