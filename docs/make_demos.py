#!/usr/bin/env python3
"""Rebuild the pictures cut from finished projects — the demo strip, the cover
wall, and the before/after pair.

Until 2026-08-22 those GIFs were cut by hand and their provenance lived nowhere:
which project, which seconds, which encode. Re-cutting one meant guessing, and
"the food vlog is held back until the faces are out" was a sentence in
.gitignore that nobody could act on. This file is that provenance as a command.

    python3 docs/make_demos.py

Sources sit OUTSIDE the repo — finished videos are never committed (NOTICE.md) —
so a clone without them skips each missing entry and says which. Every tile is
240x426, 12.5 fps, 3.84 s, matching the three that shipped first: a strip whose
tiles animate at different rates reads as broken rather than as variety.

`hold` is not a TODO. It is a recorded decision about someone who did not
consent to being in this repo, and it keeps the entry visible instead of the
video quietly disappearing from the list.
"""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo")
DESK = os.path.expanduser("~/Desktop")

W, FPS, DUR = 240, 12.5, 3.84

# Every docs/gallery file this module writes. tests/test_docs.py reads this to
# check the page has no tile that nothing generates — some are written through
# a loop variable, so a regex over the code alone would miss them.
GALLERY_FILES = (
    "covers-real.jpg", "before-after.jpg", "gates-blocked.png", "endcard.png",
    "layout-fullscreen-pip.png", "layout-split.png", "layout-background.png",
    "layout-cutout.png", "layout-cutout-large.png",
)

DEMOS = [
    # name, source, start (s), what the tile is there to show, hold reason
    ("voiceover-broll", f"{DESK}/../talking-head/FINAL.mp4", 0.0,
     "talking-head: auto B-roll + circular PiP + word-timed captions", None),
    ("event-flutter-meetup", f"{DESK}/../flutter-meetup/FINAL.mp4", 0.0,
     "event template: two caption layers, bilingual", None),
    ("running-night", f"{DESK}/running-2026-08-09/夜跑5K-v6.mp4", 0.0,
     "running vlog: word-timed captions, gold keywords", None),
    ("event-devjam-judging", f"{DESK}/dev-jam-2026/dev-jam-2026-judge-crazy-love.mp4", 0.6,
     "hook inside 1s, then the pill names the event — 90s event recap", None),
    ("food-more-joy-young", f"{DESK}/more-joy-young-0820/more-joy-young-hello.mp4", 15.6,
     "food template: AUTHORED bilingual captions, no ASR (room noise)", None),
    ("product-demo-app", f"{DESK}/running-2026-08-16/0816-dasen-run-melody.mp4", 46.5,
     "screen-recording B-roll behind a PiP — a run that turns into a product demo", None),
    ("food-hotpot", f"{DESK}/hotpot-2026-08-10/雅香石頭火鍋-花絮-v10.mp4", None,
     "food template, original room audio",
     "bystander faces incl. a child; needs a span with none, or blurring"),
    ("ioconnect-split", f"{DESK}/io-connect-2026-day1/build/rough.mov", None,
     "split-frame layout carrying official hardware footage",
     # The author cleared this one for release on 2026-08-22; it stays held on a
     # narrower ground. Scanned end to end for a clean 3.84s window and there is
     # none: attendee faces at 3.5-4.5s, a named friend at 6.7s, other attendees
     # at the XREAL booth 42-43s, and 44-47s carries an on-screen credit reading
     # 畫面來源：Google 官方 Android XR 影片. The keynote stretch is official
     # slides throughout. The only clean span, 5-8s, is wall-to-wall Google
     # signage and reads as their ad rather than as this skill's output.
     "no 3.84s window free of third-party footage or other people's faces"),
    ("event-gde-summit", f"{DESK}/gde-summit-0814/2026-apac-gde-summit-shanghai-v2-otis.mp4", None,
     "conference recap",
     "corporate interiors + NDA material in the same folder; excluded by the author"),
]


# ── cover wall ──────────────────────────────────────────────────────────
# Four shipped covers, chosen so the only prominent face is the author's or
# the author's own team. The pair of running covers is deliberate: the titles
# are very different lengths, which is the whole point of the sizer — the
# subtitle is measured to MATCH the title's width, so the block reads as one
# object no matter how many characters the title has.
COVERS = [
    (f"{DESK}/dev-jam-2026/cover.jpg", "活動"),
    (f"{DESK}/more-joy-young-0820/cover.jpg", "美食"),
    (f"{DESK}/running-2026-08-16/cover.jpg", "運動．短標題"),
    (f"{DESK}/running-2026-08-09/封面-IG.jpg", "運動．長標題"),
]

# ── before / after ──────────────────────────────────────────────────────
# One shot, twice: the frame the phone recorded and the frame that shipped.
BEFORE_AFTER = (f"{os.path.expanduser('~/Downloads')}/0820_more_joy_young/IMG_3682.MOV", 1.4,
                f"{DESK}/more-joy-young-0820/more-joy-young-hello.mp4", 0.0)

TILE_W, PAD, BG, INK = 300, 18, (18, 20, 24), (232, 236, 242)


def _font(pt):
    for f in ("/System/Library/Fonts/STHeiti Medium.ttc",
              "/System/Library/Fonts/PingFang.ttc",
              "/Library/Fonts/Arial Unicode.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, pt)
    return ImageFont.load_default()


def _strip(items, out, label_pt=22):
    """items = [(PIL image, label)] laid out in one row on a dark card."""
    tiles = []
    for im, label in items:
        im = im.convert("RGB")
        im = im.resize((TILE_W, int(im.height * TILE_W / im.width)), Image.LANCZOS)
        tiles.append((im, label))
    h = max(im.height for im, _ in tiles)
    card = Image.new("RGB", (len(tiles) * TILE_W + (len(tiles) + 1) * PAD,
                             h + 2 * PAD + label_pt + 14), BG)
    d = ImageDraw.Draw(card)
    f = _font(label_pt)
    for i, (im, label) in enumerate(tiles):
        x = PAD + i * (TILE_W + PAD)
        card.paste(im, (x, PAD))
        w = d.textbbox((0, 0), label, font=f)[2]
        d.text((x + (TILE_W - w) // 2, PAD + h + 8), label, font=f, fill=INK)
    card.save(out, quality=92)
    return out


def _frame(video, t):
    tmp = os.path.join(OUT, ".frame.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", video,
                    "-frames:v", "1", tmp], check=True)
    im = Image.open(tmp).copy()
    os.remove(tmp)
    return im


def covers():
    have = [(c, n) for c, n in COVERS if os.path.exists(c)]
    if not have:
        print("  ·  cover wall     no covers on this machine, kept as is")
        return
    out = _strip([(Image.open(c), n) for c, n in have],
                 os.path.join(HERE, "gallery", "covers-real.jpg"))
    print(f"  ✅ cover wall     {len(have)} shipped covers -> {os.path.basename(out)}")


def before_after():
    raw, t_raw, fin, t_fin = BEFORE_AFTER
    if not (os.path.exists(raw) and os.path.exists(fin)):
        print("  ·  before/after   source clip not on this machine, kept as is")
        return
    out = _strip([(_frame(raw, t_raw), "原始素材 raw clip"),
                  (_frame(fin, t_fin), "成品 shipped frame")],
                 os.path.join(HERE, "gallery", "before-after.jpg"))
    print(f"  ✅ before/after   -> {os.path.basename(out)}")


def cut(name, src, start):
    dst = os.path.join(OUT, name + ".gif")
    pal = os.path.join(OUT, f".{name}.png")
    common = ["-ss", str(start), "-t", str(DUR), "-i", src]
    vf = f"fps={FPS},scale={W}:-1:flags=lanczos"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *common,
                    "-vf", f"{vf},palettegen=max_colors=128:stats_mode=diff",
                    "-frames:v", "1", pal], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *common, "-i", pal,
                    "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
                    "-loop", "0", dst], check=True)
    os.remove(pal)
    return dst


# ── the gate shot ───────────────────────────────────────────────────────
# The repo's entire claim is "a check refuses to let it out", and until now
# that claim had no picture. This renders the REAL stdout of a real blocked
# run (see gates-blocked.txt for how it was produced) — not a mockup, because
# a mockup of a check is exactly the thing this repo argues against.
TERM_BG, TERM_FG, TERM_DIM = (22, 24, 29), (222, 228, 236), (140, 148, 160)
TERM_RED, TERM_GREEN = (233, 106, 96), (126, 198, 138)


def _mono(pt):
    for f in ("/System/Library/Fonts/SFNSMono.ttf",
              "/System/Library/Fonts/Menlo.ttc",
              "/Library/Fonts/DejaVuSansMono.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, pt)
    return ImageFont.load_default()


def gate_shot():
    src = os.path.join(HERE, "gallery", "gates-blocked.txt")
    if not os.path.exists(src):
        print("  ·  gate shot      gates-blocked.txt missing, kept as is")
        return
    lines = [l for l in open(src).read().splitlines() if not l.startswith("#")]
    # The only edit to the captured output: the two status emoji, which no
    # monospace face carries, become ✓ / ✗. Everything else is verbatim.
    lines = [l.replace("✅", "✓").replace("❌", "✗") for l in lines]
    pt, wrap = 15, 96
    f = _mono(pt)
    rows = []
    for line in lines:
        if not line.strip():
            rows.append(""); continue
        indent = " " * (len(line) - len(line.lstrip()))
        body, cur = line.strip(), indent
        for word in body.split(" "):
            if len(cur) + len(word) + 1 > wrap and cur.strip():
                rows.append(cur); cur = indent + "   " + word
            else:
                cur = (cur + " " + word) if cur.strip() else indent + word
        rows.append(cur)
    lh = int(pt * 1.55)
    im = Image.new("RGB", (int(wrap * pt * 0.62) + 56, len(rows) * lh + 44), TERM_BG)
    d = ImageDraw.Draw(im)
    for i, row in enumerate(rows):
        colour = (TERM_RED if ("FAIL" in row or row.strip().startswith("✗")
                               or "BLOCKED" in row)
                  else TERM_GREEN if "PASS" in row
                  else TERM_DIM if ":" in row and not row.strip().startswith("=")
                  else TERM_FG)
        d.text((28, 22 + i * lh), row, font=f, fill=colour)
    out = os.path.join(HERE, "gallery", "gates-blocked.png")
    im.save(out)
    print(f"  ✅ gate shot      {len(rows)} lines -> {os.path.basename(out)}")


# ── end card ────────────────────────────────────────────────────────────
# A real shipped end card, not a render of one. This project's is the only
# one whose closing frame carries no third party's face — the others end on
# a group shot, which is exactly the situation the clearance gate exists for.
ENDCARD = f"{DESK}/more-joy-young-0820/build/endcard.png"


def endcard():
    if not os.path.exists(ENDCARD):
        print("  ·  end card       source not on this machine, kept as is")
        return
    im = Image.open(ENDCARD).convert("RGB")
    im = im.resize((540, int(im.height * 540 / im.width)), Image.LANCZOS)
    out = os.path.join(HERE, "gallery", "endcard.png")
    im.save(out)
    print(f"  ✅ end card       -> {os.path.basename(out)}")


# ── B-roll 版面：真實影片的畫面，不是示意圖 ──────────────────────────────
# 這四種版面原本是 make_gallery.py 畫出來的色塊，因為公開 repo 裡沒有素材可以
# 跑真的合成。作者提供了自己已發布影片的畫面之後就不必再畫了。
#
# 版面的指認方式：先用 modules/compose.py 的真 builder 跑一組已知版面當基準
# （同一段素材、四種 layout），再拿這些畫面去對。split 的素材佔上 55% 且不模糊，
# background 的素材模糊疊在上 35% 且自拍是全幀前景 — 兩者一比就分得出來。
# 這一步是必要的：目測判過一次，判錯了。
DL = os.path.expanduser("~/Downloads")
LAYOUT_SHOTS = [
    ("layout-fullscreen-pip", f"{DL}/IMG_3773.jpg", None,
     "fullscreen：素材鋪滿，人在右上圓框"),
    ("layout-split", f"{DL}/IMG_3775.jpg", None,
     "split：素材佔上半，自拍在下，中間漸層"),
    ("layout-background", f"{DL}/IMG_3777.jpg", None,
     "background：素材模糊疊在上方，自拍是全幀前景"),
    ("layout-cutout", f"{DL}/IMG_3774.jpg", None,
     "cutout-small：去背人像在左下"),
    # 這一張的 B-roll 是別人的 GitHub 頁面。內容本身是公開的，但右欄那排
    # contributor 頭像是具體的人，模糊掉再用。
    ("layout-cutout-large", f"{DL}/IMG_3776.jpg", (0.73, 0.40, 1.0, 0.47),
     "cutout-large：去背人像放大，站在網站截圖前"),
]


def layouts():
    made = 0
    for name, src, blur_box, why in LAYOUT_SHOTS:
        if not os.path.exists(src):
            print(f"  ·  {name:24s} source not on this machine, kept as is")
            continue
        im = Image.open(src).convert("RGB")
        if blur_box:
            from PIL import ImageFilter
            x0, y0, x1, y1 = blur_box
            box = (int(x0 * im.width), int(y0 * im.height),
                   int(x1 * im.width), int(y1 * im.height))
            im.paste(im.crop(box).filter(ImageFilter.GaussianBlur(14)), box)
        im = im.resize((580, int(im.height * 580 / im.width)), Image.LANCZOS)
        out = os.path.join(HERE, "gallery", name + ".png")
        im.save(out)
        print(f"  ✅ {name:24s} — {why}")
        made += 1
    if made:
        print(f"  ({made} layout tile(s) from shipped video frames)")


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found — run python3 doctor.py")
    made = held = missing = 0
    for name, src, start, why, hold in DEMOS:
        if hold:
            print(f"  ⛔ {name:24s} HELD — {hold}")
            held += 1
        elif not os.path.exists(src):
            print(f"  ·  {name:24s} source not on this machine, kept as is")
            missing += 1
        else:
            p = cut(name, src, start)
            print(f"  ✅ {name:24s} {os.path.getsize(p)/1e6:.1f} MB  — {why}")
            made += 1
    covers()
    before_after()
    gate_shot()
    endcard()
    layouts()
    print(f"\n  {made} rebuilt · {missing} left alone · {held} held back\n")


if __name__ == "__main__":
    main()
