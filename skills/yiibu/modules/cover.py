"""Cover / thumbnail — locked recipe.

The cover is not decoration: on IG Reels and Shorts it is the whole click
decision, and it is also frame 1 of the video. Both of those are load-bearing,
so the rules here are constraints, not suggestions:

  * at most TWO lines of title. Three lines forces the type down to a size that
    is unreadable in a 120px profile-grid thumbnail;
  * the title auto-grows to fill the width, so a 4-character line comes out far
    bigger than a 7-character one — write SHORT and it gets BIG for free;
  * product/platform names belong in the subtitle, not the headline. "戴上
    Android XR" reads wrong to a developer audience — Android XR is the
    platform; the thing you wear is the glasses;
  * the subject must be identifiable at thumbnail size — face, and whatever the
    video is actually about, in the upper half;
  * it is burned onto frame 1 as an OVERLAY, never prepended as a segment: a
    prepended frame shifts every caption timestamp by a frame.

`legibility()` measures the rendered title's line height against frame height,
so "too small for a feed" is caught here instead of after publishing.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import OUTPUT_WIDTH as W, OUTPUT_HEIGHT as H

def _house_cover():
    """Cover geometry comes from house_style.json — ONE number, not one here and
    another in gates.py that silently drift apart."""
    import json
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "house_style.json")
    try:
        return json.load(open(p, encoding="utf-8"))["cover"]
    except Exception:                                        # noqa: BLE001
        return {"title_max_w_ratio": 0.72, "max_title_lines": 2}


def _house_gold():
    """The subtitle colour, from house_style.json. Locked #F6DB66 on 2026-08-16."""
    hexv = str(_house_cover().get("subtitle_gold", "#F6DB66")).lstrip("#")
    return tuple(int(hexv[i:i + 2], 16) for i in (0, 2, 4))


TITLE_MAX_W = int(W * _house_cover()["title_max_w_ratio"])
TITLE_MAX_PT = 196
TITLE_MIN_PT = 96          # below this it stops surviving a 120px thumbnail
SUB_RANGE = (40, 120)      # wide, because the subtitle is sized to MATCH the
                           # title block's width, not a fixed maximum
TITLE_BASE_Y = int(H * 0.56)   # bottom of the title block
IG_FEED_W = 360
IG_GRID_W = 120
# A title line must occupy at least this fraction of frame height. 0.055 of
# 1920 = ~106px, which is ~11px in a 120px-wide profile grid thumbnail —
# the point where CJK stops being readable.
MIN_TITLE_LINE_RATIO = 0.055


TITLE_MAX_LINES = _house_cover()["max_title_lines"]


def _font(pt):
    from title import _find_font
    return ImageFont.truetype(_find_font(), pt)


def fit_background(img, zoom=1.0, y_anchor=0.5, x_anchor=0.5):
    """Scale past fill and crop, so the subject can be placed in the upper half."""
    s = max(W / img.width, H / img.height) * zoom
    im = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    return im.crop((int((im.width - W) * x_anchor), int((im.height - H) * y_anchor),
                    int((im.width - W) * x_anchor) + W,
                    int((im.height - H) * y_anchor) + H))


def vignette(im, top=0.15, bottom=0.42, top_a=118, bottom_a=170):
    g = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(g)
    d.rectangle([0, 0, W, int(H * top)], fill=top_a)
    d.rectangle([0, int(H * (1 - bottom)), W, H], fill=bottom_a)
    g = g.filter(ImageFilter.GaussianBlur(150))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, g)


def _title_size(d, lines):
    pt = TITLE_MAX_PT
    while pt > TITLE_MIN_PT:
        f = _font(pt)
        if max(d.textlength(ln, font=f) for ln in lines) <= TITLE_MAX_W:
            return pt, f
        pt -= 2
    return pt, _font(pt)


def draw(im, title, subtitle, gold=None):
    """gold: the subtitle colour. Defaults to the house value in house_style.json
    (#F6DB66, locked 2026-08-16 by the user — every cover subtitle uses it)."""
    if gold is None:
        gold = _house_gold()
    lines = [ln for ln in title.split("\n") if ln.strip()]
    if len(lines) > TITLE_MAX_LINES:
        raise ValueError(
            f"cover title has {len(lines)} lines; max is {TITLE_MAX_LINES}. "
            f"Shorten it — fewer characters is what makes the type big.")
    d = ImageDraw.Draw(im)
    pt, tf = _title_size(d, lines)

    boxes = [d.textbbox((0, 0), ln, font=tf) for ln in lines]
    lh = max(b[3] - b[1] for b in boxes) + int(pt * 0.26)
    y = TITLE_BASE_Y - lh * (len(lines) - 1)
    widest = 0
    for ln, bb in zip(lines, boxes):
        tw = bb[2] - bb[0]
        widest = max(widest, tw)
        x = (W - tw) // 2 - bb[0]
        for ox, oy in ((5, 6), (-4, 5), (4, -4)):
            d.text((x + ox, y + oy - bb[1]), ln, font=tf, fill=(0, 0, 0))
        d.text((x, y - bb[1]), ln, font=tf, fill=(255, 255, 255))
        y += lh

    # The subtitle is sized to the TITLE's rendered width, not to a fixed cap, so
    # the two read as one stacked block. Measuring against `max(widest,
    # TITLE_MAX_W)` instead let a short subtitle sit at an unrelated width under
    # a narrow title, which looks like two unrelated captions.
    size = SUB_RANGE[0]
    for s in range(SUB_RANGE[1], SUB_RANGE[0] - 1, -1):
        if d.textlength(subtitle, font=_font(s)) <= widest:
            size = s
            break
    floor = _house_cover().get("subtitle_min_pt", 0)
    if floor and size < floor:
        raise ValueError(
            f"cover subtitle would render at {size}pt (house floor {floor}pt): "
            f"{subtitle!r} is too long for a {int(widest)}px title. The subtitle "
            f"is width-matched to the title, so a short title plus a long "
            f"subtitle crushes it — shorten the subtitle, do not shrink it. "
            f"Move product and platform names to the post caption.")
    sf = _font(size)
    b = d.textbbox((0, 0), subtitle, font=sf)
    x = (W - (b[2] - b[0])) // 2 - b[0]
    yy = y + int(pt * 0.20)
    d.text((x + 3, yy + 4 - b[1]), subtitle, font=sf, fill=(0, 0, 0))
    d.text((x, yy - b[1]), subtitle, font=sf, fill=gold)
    metrics = {"title_pt": pt, "title_w": int(widest),
               "title_line_px": int(max(b[3] - b[1] for b in boxes)),
               "subtitle_pt": size, "subtitle_w": int(b[2] - b[0]),
               "title_lines": len(lines)}
    return im, pt, size, metrics


def build(src_image, title, subtitle, out_path,
          zoom=1.0, y_anchor=0.5, x_anchor=0.5, allow_landscape=False, **vig):
    """Render the cover and return (path, title_pt, subtitle_pt).

    Raises on a LANDSCAPE source, because on this skill's material that almost
    always means one specific bug rather than a choice.

    Measured 2026-08-23: a build shipped a cover that was a correct 1080x1920
    file with the picture inside it lying on its side — a pylon horizontal, the
    road running down the frame. gate_cover passed it, because it checks the
    geometry and that frame 1 matches, and both were true. The cause is the trap
    AGENTS.md already documents for footage: ffprobe reports CODED dimensions,
    so a clip that DISPLAYS portrait reads 1920x1080, and a frame pulled from it
    without applying the display matrix comes out landscape. Feed that here and
    fit_background dutifully crops a sideways picture to portrait.

    A genuinely landscape photo is legal and rare; it also throws away ~75% of
    the frame, which is worth being deliberate about. Hence the escape hatch
    rather than a silent pass.
    """
    src = Image.open(src_image)
    sw, sh = src.size
    if sw > sh and not allow_landscape:
        raise ValueError(
            f"cover source is landscape ({sw}x{sh}) for a {W}x{H} cover. On "
            f"phone footage that is the rotation trap, not a crop: a clip that "
            f"DISPLAYS portrait reports 1920x1080, and a frame taken from it "
            f"without the display matrix comes out on its side. Extract the "
            f"frame with ffmpeg (which auto-rotates) or via PIL's "
            f"exif_transpose. If the source really is a landscape photo and you "
            f"mean to crop {100 - int(100 * (sh * W / H) / sw)}% of its width "
            f"away, pass allow_landscape=True.")
    im = fit_background(src.convert("RGB"), zoom, y_anchor, x_anchor)
    im, pt, sub_pt, metrics = draw(vignette(im, **vig), title, subtitle)
    metrics.update(source=os.path.basename(str(src_image)),
                   source_w=sw, source_h=sh)
    im.save(out_path, quality=94)
    # Sidecar so the shipping gate can CHECK the subtitle tracks the title width
    # instead of a human eyeballing it. Measuring it back off the JPEG would mean
    # guessing which bright rows are the title.
    import json as _json
    _json.dump(metrics, open(os.path.join(os.path.dirname(os.path.abspath(out_path)),
                                          "cover_meta.json"), "w"))
    return out_path, pt, sub_pt


def legibility(cover_path):
    """Measure the rendered title's LINE HEIGHT as a fraction of frame height.

    Line height is the honest proxy for "can I read this in a feed": it is what
    shrinks when the headline gets wordy, because the auto-sizer trades point size
    for character count.

    Prefer the value cover.draw() MEASURED off the font. The pixel fallback below
    scans for bright rows, which silently latches onto a bright BACKGROUND: on a
    cover whose photo is a lit phone screen it returned the identical 0.0833 for a
    190pt title and a 154pt one — a metric that cannot see the thing it claims to
    measure. It is kept only for covers built before the sidecar existed.
    """
    import numpy as np
    from PIL import Image
    import json as _json
    meta = os.path.join(os.path.dirname(os.path.abspath(cover_path)), "cover_meta.json")
    if os.path.exists(meta):
        m = _json.load(open(meta))
        if "title_line_px" in m:
            ratio = m["title_line_px"] / H
            return {"title_line_px": int(m["title_line_px"]),
                    "title_line_ratio": round(ratio, 4),
                    "min_ratio": MIN_TITLE_LINE_RATIO,
                    "px_at_ig_grid": round(ratio * IG_GRID_W * H / W, 1),
                    "source": "font-metrics",
                    "ok": ratio >= MIN_TITLE_LINE_RATIO}
    a = np.asarray(Image.open(cover_path).convert("L"), dtype=float)
    h, w = a.shape
    band = a[int(h * 0.35):int(h * 0.75)]
    # a title row is bright across a meaningful part of the width
    rows = (band > 205).sum(axis=1) > (w * 0.04)
    runs, cur = [], 0
    for r in rows:
        if r:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    line_px = max(runs) if runs else 0
    ratio = line_px / h
    return {
        "title_line_px": int(line_px),
        "title_line_ratio": round(ratio, 4),
        "min_ratio": MIN_TITLE_LINE_RATIO,
        "px_at_ig_grid": round(ratio * IG_GRID_W * H / W, 1),
        "source": "pixel-scan (no cover_meta.json; unreliable on bright backgrounds)",
        "ok": ratio >= MIN_TITLE_LINE_RATIO,
    }


def overlay_on_first_frame(video_in, cover_path, video_out, fps=30):
    """Burn the cover as frame 1 WITHOUT shifting any timing.

    Prepending a cover segment to the concat list moves every caption by a frame
    and changes the duration; overlaying on frame 1 does not.
    """
    import subprocess
    fc = (f"[1:v]scale={W}:{H},setsar=1[cov];"
          f"[0:v][cov]overlay=0:0:enable='lt(t,{1.0/fps:.4f})'[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-i", video_in, "-i", cover_path,
                    "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-y", video_out],
                   check=True)
    return video_out
