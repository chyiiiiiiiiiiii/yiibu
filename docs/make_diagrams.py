#!/usr/bin/env python3
"""Render docs/diagrams/*.png from house_style.json and the real renderers.

The diagrams are GENERATED, not drawn: the pill comes from modules/title.py and
every position comes from house_style.json, so the picture cannot drift from
the spec the gates enforce. Re-run after changing either:

    python3 docs/make_diagrams.py
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

from title import render_title_png, _find_font  # noqa: E402

OUT_DIR = os.path.join(SKILL, "docs", "diagrams")
W, H = 1080, 1920
SCALE = 0.5                       # published at 540x960

HS = json.load(open(os.path.join(SKILL, "house_style.json")))
GOLD = "#F6DB66"
ANNOT = "#7FDBFF"                 # annotation colour — deliberately NOT a house colour


def font(size):
    return ImageFont.truetype(_find_font(), size)


def annotate(d, xy, text, size=30, colour=ANNOT):
    d.text(xy, text, font=font(size), fill=colour)


def caption_geometry():
    """One annotated 1080x1920 frame: pill 23%, caption baseline 70%, gold."""
    im = Image.new("RGB", (W, H), (24, 26, 30))
    d = ImageDraw.Draw(im)

    # phone-frame hint: the zones the platform UI eats
    d.rectangle([0, 0, W, 140], fill=(38, 40, 46))
    d.rectangle([0, H - 220, W, H], fill=(38, 40, 46))
    annotate(d, (30, 90), "platform UI zone — captions never live here", 26, "#888888")
    annotate(d, (30, H - 200), "platform UI zone (progress bar, caption box)", 26, "#888888")

    # ── pill at 23% ──────────────────────────────────────────
    pill_pct = HS["pill"]["centre_pct"]
    pill_y = int(pill_pct * H)
    pill_png = os.path.join(OUT_DIR, "_pill_tmp.png")
    render_title_png("金瓜石地質公園", pill_png,
                     pct=pill_pct, font_size=HS["pill"]["font_size"])
    pill = Image.open(pill_png).convert("RGBA")
    im.paste(pill, (0, 0), pill)
    os.remove(pill_png)
    d.line([(0, pill_y), (W, pill_y)], fill=ANNOT, width=2)
    annotate(d, (20, pill_y - 130),
             f"pill centre = {pill_pct:.0%} of H  (PIL capsule, never an ASS box)")
    annotate(d, (20, pill_y + 80),
             "names the thing · width hugs the text · hard cut, no fade", 26)

    # ── caption baseline at 70% ─────────────────────────────
    base_pct = HS["captions"]["baseline_pct"]
    base_y = int(base_pct * H)
    d.line([(0, base_y), (W, base_y)], fill=ANNOT, width=2)
    sp = HS["captions"]["styles"]["Speech"]["size"]
    kw = HS["captions"]["keyword"]["size"]
    # the caption itself: white with one gold keyword span
    left = "配速"
    gold_word = "4:51"
    right = " 整路沒掉"
    f_sp, f_kw = font(sp), font(kw)
    w_all = (d.textlength(left, f_sp) + d.textlength(gold_word, f_kw)
             + d.textlength(right, f_sp))
    x = (W - w_all) / 2
    y = base_y - sp // 2
    shadow = 5
    for txt, fnt, col in ((left, f_sp, "white"), (gold_word, f_kw, GOLD),
                          (right, f_sp, "white")):
        d.text((x + shadow, y + shadow), txt, font=fnt, fill=(0, 0, 0, 160))
        d.text((x, y), txt, font=fnt, fill=col)
        x += d.textlength(txt, fnt)
    annotate(d, (20, base_y - 160),
             f"caption baseline = {base_pct:.0%} of H  ·  \\an5 explicit \\pos")
    annotate(d, (20, base_y + 70),
             f"Speech {sp}px white · keyword {kw}px gold {GOLD} (min 3 spans)", 26)
    annotate(d, (20, base_y + 110),
             "outline 0, shadow ≥5 — a drop shadow, NEVER a black outline", 26)

    # ── hook note at the top ────────────────────────────────
    annotate(d, (30, 190), "Hook (104px, style 'free'): must START before 1.0s", 30)

    im = im.resize((int(W * SCALE), int(H * SCALE)), Image.LANCZOS)
    out = os.path.join(OUT_DIR, "caption-geometry.png")
    im.save(out)
    print(f"  wrote {out}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    caption_geometry()
