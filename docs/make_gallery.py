#!/usr/bin/env python3
"""Render docs/gallery/*.png — one tile per row of SKILL.md's capability map.

SKILL.md says an undocumented capability does not exist, and lists twenty-odd
effects in prose. Prose is the right form for the agent, which reads SKILL.md as
text and cannot see a picture. It is the wrong form for the person, who cannot
ask for "cutout-large" without knowing what that looks like. This is the same
argument the capability map already makes about code, one level up.

Two kinds of tile, and the difference is labelled on the page:

  **render** — produced by the REAL renderer at the REAL house values, so it
  cannot drift from what the gates enforce. The pill comes from
  modules/title.py, the cover from modules/cover.py, the caption geometry from
  house_style.json.

  **schematic** — the B-roll compositions are ffmpeg filter graphs over real
  footage; there is no footage in a public repo to run them on. These are drawn,
  but the GEOMETRY is read from config.py (PIP_SIZE, SPLIT_RATIO,
  BG_BROLL_RATIO…), so the proportions are the ones the code uses even though
  the imagery is a placeholder. A tile that invented its own numbers would be a
  drawing of a different product.

    python3 docs/make_gallery.py
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

import config as cfg                                    # noqa: E402
from title import render_title_png, _find_font          # noqa: E402
import cover as cover_mod                               # noqa: E402

OUT = os.path.join(SKILL, "docs", "gallery")
W, H = 1080, 1920
TILE = 0.28                                   # published at ~300x538

HS = json.load(open(os.path.join(SKILL, "house_style.json")))
GOLD_HEX = HS.get("cover", {}).get("subtitle_gold", "#F6DB66")
INK = (250, 250, 250)
LABEL = "#7FDBFF"


def font(pt):
    return ImageFont.truetype(_find_font(), pt)


def backdrop(tint=(46, 50, 58), band=(70, 78, 92)):
    """A neutral stand-in for footage. Deliberately not a photo: the tile is
    about WHERE things sit, and a photograph would argue about taste instead."""
    im = Image.new("RGB", (W, H), tint)
    d = ImageDraw.Draw(im)
    for i in range(0, H, 160):                # soft horizontal banding
        d.rectangle([0, i, W, i + 80], fill=band)
    return im.filter(ImageFilter.GaussianBlur(48))


def broll_block(w, h, tint=(30, 96, 132)):
    im = Image.new("RGB", (w, h), tint)
    d = ImageDraw.Draw(im)
    for i in range(0, max(w, h), 120):
        d.line([(i - h, h), (i, 0)], fill=(46, 126, 168), width=34)
    d.text((28, 24), "B-ROLL", font=font(46), fill=(210, 235, 250))
    return im


def note(d, text, y, size=30):
    d.text((30, y), text, font=font(size), fill=LABEL)


def save(im, name):
    im = im.resize((int(W * TILE), int(H * TILE)), Image.LANCZOS)
    p = os.path.join(OUT, f"{name}.png")
    im.save(p)
    print(f"  {name}")
    return p


# ── real renders ────────────────────────────────────────────────────────

def tile_captions():
    """Two caption layers + gold keyword + the bilingual line, at house values."""
    im = backdrop()
    d = ImageDraw.Draw(im)

    pill_pct = HS["pill"]["centre_pct"]
    tmp = os.path.join(OUT, "_p.png")
    render_title_png("GDE Lightning Talks", tmp, pct=pill_pct,
                     font_size=HS["pill"]["font_size"])
    pill = Image.open(tmp).convert("RGBA")
    im.paste(pill, (0, 0), pill)
    os.remove(tmp)
    note(d, f"pill — NAMES it, {pill_pct:.0%} of H", int(pill_pct * H) + 90)

    base = int(HS["captions"]["baseline_pct"] * H)
    sp = HS["captions"]["styles"]["Note"]["size"]
    kws = HS["captions"]["keyword"]["size"]
    en = HS["bilingual"]["english_font_size"]
    # Two lines, because one would overflow — the same safe area gate_captions
    # enforces (960px). A gallery tile that overruns the frame is teaching the
    # defect the width check exists to stop.
    lines = [[("接上 ", sp, "white"), ("Gemini", kws, GOLD_HEX)],
             [("畫面直接翻譯", sp, "white")]]
    y = base - sp * len(lines)
    for parts in lines:
        total = sum(d.textlength(t, font(s)) for t, s, _ in parts)
        assert total <= 960, f"gallery caption overflows: {total:.0f}px"
        x = (W - total) / 2
        for t, s, c in parts:
            d.text((x + 5, y + 5), t, font=font(s), fill=(0, 0, 0))
            d.text((x, y), t, font=font(s), fill=c)
            x += d.textlength(t, font(s))
        y += sp * 1.15
    y -= sp * 0.15
    sub = "One tap — Gemini translates the screen"
    ws = d.textlength(sub, font(en))
    d.text(((W - ws) / 2 + 4, y + 22), sub, font=font(en), fill=(0, 0, 0))
    d.text(((W - ws) / 2, y + 18), sub, font=font(en), fill=(234, 234, 234))
    note(d, f"caption — EXPLAINS it, {HS['captions']['baseline_pct']:.0%} baseline",
         base - sp * 2 - 70)
    note(d, f"gold keyword {kws}px {GOLD_HEX} · EN line {en}px", y + 90, 26)
    return save(im, "captions-two-layer")


def tile_emphasis():
    """The hero caption: stacked, staggered, face-aware."""
    im = backdrop((38, 34, 44), (62, 54, 74))
    d = ImageDraw.Draw(im)
    size = getattr(cfg, "FONT_SIZE_EMPHASIS", 132)
    en = getattr(cfg, "FONT_SIZE_EMPHASIS_ENGLISH", 60)
    stagger = getattr(cfg, "EMPHASIS_STAGGER_X", 60)
    for i, chunk in enumerate(["這週還不能用的", "下週再試一次"]):
        x = 90 + i * stagger
        y = int(H * 0.46) + i * int(size * 1.25)
        d.text((x + 6, y + 6), chunk, font=font(size), fill=(0, 0, 0))
        d.text((x, y), chunk, font=font(size), fill=INK)
    d.text((90, int(H * 0.46) + 2 * int(size * 1.25) + 20),
           "Try it again next week", font=font(en), fill=(228, 228, 228))
    note(d, f"emphasis — {size}px, stacked, staggered {stagger}px",
         int(H * 0.46) - 80)
    note(d, "placed inside the face-free band, never over a face",
         int(H * 0.46) - 40, 26)
    return save(im, "emphasis-captions")


def tile_cover():
    src = os.path.join(OUT, "_cov.png")
    backdrop((52, 44, 40), (86, 72, 62)).save(src)
    out = os.path.join(OUT, "_cover.jpg")
    cover_mod.build(src, "潛入 Google\n上海辦公室", "亞太 GDE 年會一日記", out)
    im = Image.open(out).convert("RGB")
    d = ImageDraw.Draw(im)
    note(d, f"≤{HS['cover']['max_title_lines']} title lines · subtitle width-matched "
            f"· burned on frame 1", H - 150, 28)
    p = save(im, "cover")
    for f in (src, out, os.path.join(OUT, "cover_meta.json")):
        if os.path.exists(f):
            os.remove(f)
    return p


# ── schematics: geometry from config.py, imagery is placeholder ─────────

def tile_fullscreen_pip():
    im = backdrop()
    im.paste(broll_block(W, H), (0, 0))
    d = ImageDraw.Draw(im)
    s, mt, mr = cfg.PIP_SIZE, cfg.PIP_MARGIN_TOP, cfg.PIP_MARGIN
    x, y = W - mr - s, mt
    d.ellipse([x - cfg.PIP_BORDER_WIDTH, y - cfg.PIP_BORDER_WIDTH,
               x + s + cfg.PIP_BORDER_WIDTH, y + s + cfg.PIP_BORDER_WIDTH],
              fill="white")
    d.ellipse([x, y, x + s, y + s], fill=(96, 104, 118))
    d.text((x + 52, y + s // 2 - 26), "SELFIE", font=font(40), fill=INK)
    note(d, f"PIP_SIZE {s} · PIP_MARGIN_TOP {mt} · border {cfg.PIP_BORDER_WIDTH}",
         y + s + 60, 28)
    return save(im, "layout-fullscreen-pip")


def tile_split():
    im = backdrop()
    top = int(H * cfg.SPLIT_RATIO)
    im.paste(broll_block(W, top), (0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, top, W, H], fill=(64, 70, 82))
    d.text((W // 2 - 110, top + (H - top) // 2), "SELFIE", font=font(56), fill=INK)
    d.rectangle([0, top - cfg.SPLIT_BLUR_HEIGHT // 2, W,
                 top + cfg.SPLIT_BLUR_HEIGHT // 2], fill=(56, 84, 100))
    note(d, f"SPLIT_RATIO {cfg.SPLIT_RATIO:.0%} · gradient "
            f"{cfg.SPLIT_BLUR_HEIGHT}px", top + 70, 28)
    return save(im, "layout-split")


def tile_background():
    im = backdrop()
    im.paste(broll_block(W, H, (36, 60, 88)), (0, 0))
    d = ImageDraw.Draw(im)
    bw = int(W * (1 - cfg.BG_BROLL_RATIO))
    bh = int(bw * H / W)
    bx, by = (W - bw) // 2, (H - bh) // 2
    d.rectangle([bx, by, bx + bw, by + bh], fill=(74, 80, 94))
    d.text((bx + bw // 2 - 110, by + bh // 2), "SELFIE", font=font(56), fill=INK)
    note(d, f"BG_BROLL_RATIO {cfg.BG_BROLL_RATIO} — asset behind, selfie centred",
         by - 70, 28)
    return save(im, "layout-background")


def tile_cutout():
    im = backdrop()
    im.paste(broll_block(W, H, (28, 78, 70)), (0, 0))
    d = ImageDraw.Draw(im)
    cx, base_y, hw = W // 2, int(H * 0.92), 210
    d.ellipse([cx - 120, base_y - 760, cx + 120, base_y - 520], fill=(96, 104, 118))
    d.polygon([(cx - hw, base_y), (cx + hw, base_y),
               (cx + hw - 40, base_y - 520), (cx - hw + 40, base_y - 520)],
              fill=(96, 104, 118))
    note(d, "cutout — MediaPipe segmentation, speaker IN FRONT of the asset",
         int(H * 0.16), 28)
    note(d, "geometry via BLS_* · sizes: cutout-large / cutout-small",
         int(H * 0.16) + 44, 26)
    return save(im, "layout-cutout")


TILES = [
    ("captions-two-layer", tile_captions, "render"),
    ("emphasis-captions", tile_emphasis, "render"),
    ("cover", tile_cover, "render"),
    ("layout-fullscreen-pip", tile_fullscreen_pip, "schematic"),
    ("layout-split", tile_split, "schematic"),
    ("layout-background", tile_background, "schematic"),
    ("layout-cutout", tile_cutout, "schematic"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for _, fn, _kind in TILES:
        fn()
    print(f"\n  {len(TILES)} tiles -> {OUT}")


if __name__ == "__main__":
    main()
