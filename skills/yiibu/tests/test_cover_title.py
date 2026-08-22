"""Invariants of the two renderers nothing was testing.

`modules/cover.py` and `modules/title.py` had no test file. Their rules were
stated in SKILL.md and enforced only by the shipping gates — which measure the
finished JPEG and PNG, so a break shows up as a confusing gate failure three
steps downstream instead of here.

Both are also the modules a fork is most likely to edit, because they ARE the
house look. That is exactly when you want the invariants written down as
assertions rather than as sentences in a document.
"""
import json
import os
import pathlib
import sys

import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "modules")]

import cover  # noqa: E402
import title  # noqa: E402

HOUSE = json.loads((ROOT / "house_style.json").read_text())
W, H = 1080, 1920


def _bg():
    return Image.new("RGB", (W, H), (40, 44, 52))


# ── cover.py ────────────────────────────────────────────────────────────

def test_two_title_lines_are_allowed():
    im, pt, sub_pt, metrics = cover.draw(_bg(), "潛入 Google\n上海辦公室", "亞太年會一日記")
    assert im.size == (W, H)
    assert pt > 0 and sub_pt > 0
    assert metrics["title_lines"] == 2


def test_three_title_lines_are_rejected():
    """Fewer characters is what makes the type big; the sizer trades point size
    for character count, so a third line silently shrinks the cover to nothing.
    """
    with pytest.raises(ValueError):
        cover.draw(_bg(), "一行\n兩行\n三行", "副標")


def test_title_stays_inside_the_house_width_ratio():
    """The cap carries an ink-overhang tolerance, and gate_cover applies it too.

    The italic face overshoots its advance width, so measured ink is a few px
    wider than the layout box. Asserting the bare ratio would fail a cover the
    shipping gate accepts — the two must agree or one of them is wrong.
    """
    hs = HOUSE["cover"]
    cap = W * hs["title_max_w_ratio"] + hs["title_ink_overhang_tol_px"]
    _, _, _, metrics = cover.draw(_bg(), "潛入 Google\n上海辦公室", "亞太年會一日記")
    assert metrics["title_w"] <= cap, (
        f"title is {metrics['title_w']}px, gate cap is {cap:.0f}px")


def test_subtitle_width_tracks_the_title():
    """The subtitle is sized to MATCH the title's width, not to a fixed point
    size — that is what makes the block read as one object in a feed."""
    tol = HOUSE["cover"]["subtitle_width_match_tol_px"]
    _, _, _, m = cover.draw(_bg(), "潛入 Google\n上海辦公室", "亞太 GDE 年會一日記")
    assert abs(m["title_w"] - m["subtitle_w"]) <= tol, (
        f"title {m['title_w']}px vs subtitle {m['subtitle_w']}px, tol {tol}px")


def test_build_writes_the_cover_meta_sidecar(tmp_path):
    """gates.py CHECKS the width match from this sidecar rather than guessing
    which bright rows in the JPEG were the title."""
    src = tmp_path / "src.png"
    _bg().save(src)
    out = tmp_path / "cover.jpg"
    path, pt, sub_pt = cover.build(str(src), "潛入 Google\n上海辦公室",
                                   "亞太年會一日記", str(out))
    assert os.path.exists(path)
    meta = json.loads((tmp_path / "cover_meta.json").read_text())
    assert meta["title_pt"] == pt and meta["subtitle_pt"] == sub_pt
    assert {"title_w", "subtitle_w", "title_lines"} <= set(meta)


def test_fit_background_always_fills_the_frame():
    """Letterboxing a cover is worse than cropping it."""
    for size in ((800, 600), (1200, 1200), (400, 2000)):
        out = cover.fit_background(Image.new("RGB", size, (10, 10, 10)))
        assert out.size == (W, H), f"{size} produced {out.size}"


# ── title.py (the pill) ─────────────────────────────────────────────────

def test_pill_is_a_capsule_not_a_box(tmp_path):
    """An ASS opaque box has square corners. The corner_alpha_max gate exists
    because a rebuild shipped exactly that while every position check passed.
    """
    import numpy as np
    png = tmp_path / "pill.png"
    title.render_title_png("報到入場", str(png), pct=HOUSE["pill"]["centre_pct"],
                           font_size=HOUSE["pill"]["font_size"])
    alpha = np.asarray(Image.open(png).convert("RGBA"))[:, :, 3]
    ys, xs = np.where(alpha > 0)
    assert len(xs), "pill rendered nothing"
    top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    cap = HOUSE["pill"]["corner_alpha_max"]
    corners = [alpha[top, left], alpha[top, right],
               alpha[bottom, left], alpha[bottom, right]]
    assert max(corners) <= cap, (
        f"corner alpha {corners} exceeds {cap} — this is a box, not a capsule")


def test_pill_sits_at_the_house_height(tmp_path):
    import numpy as np
    png = tmp_path / "pill.png"
    pct = HOUSE["pill"]["centre_pct"]
    title.render_title_png("報到入場", str(png), pct=pct,
                           font_size=HOUSE["pill"]["font_size"])
    alpha = np.asarray(Image.open(png).convert("RGBA"))[:, :, 3]
    ys = np.where(alpha.sum(axis=1) > 0)[0]
    centre = (ys.min() + ys.max()) / 2 / alpha.shape[0]
    assert abs(centre - pct) < 0.02, f"pill centre at {centre:.3f}, house says {pct}"


def test_pill_never_runs_edge_to_edge(tmp_path):
    """A pill that touches both margins reads as a banner, not a label."""
    import numpy as np
    png = tmp_path / "pill.png"
    title.render_title_png("這是一個相當長的段落名稱用來測試寬度上限", str(png),
                           pct=HOUSE["pill"]["centre_pct"], font_size=44)
    alpha = np.asarray(Image.open(png).convert("RGBA"))[:, :, 3]
    xs = np.where(alpha.sum(axis=0) > 0)[0]
    width_ratio = (xs.max() - xs.min() + 1) / alpha.shape[1]
    assert width_ratio <= HOUSE["pill"]["max_w_ratio"], (
        f"pill spans {width_ratio:.2f} of the frame, house cap is "
        f"{HOUSE['pill']['max_w_ratio']}")


def test_a_long_subtitle_under_a_short_title_is_rejected():
    """The width match is a trap when the title is short.

    「莫宰羊」is three characters — 600px — so a 15-character subtitle got
    width-matched down to 42pt and shipped. Invisible in an IG grid, and nothing
    warned: the cover looked fine at full resolution, which is not where anyone
    sees it. The answer is always fewer characters, never a smaller size.
    """
    floor = HOUSE["cover"]["subtitle_min_pt"]
    with pytest.raises(ValueError, match="shorten the subtitle"):
        cover.draw(_bg(), "莫宰羊", "台北羊肉爐・More Joy Young")
    _, _, pt, _ = cover.draw(_bg(), "莫宰羊", "台北羊肉爐")
    assert pt >= floor, f"a short subtitle should clear the floor, got {pt}pt"


def test_the_floor_does_not_fire_on_a_normal_cover():
    """A two-line title gives the subtitle room; the guard must stay quiet."""
    _, _, pt, _ = cover.draw(_bg(), "潛入 Google\n上海辦公室", "亞太 GDE 年會一日記")
    assert pt >= HOUSE["cover"]["subtitle_min_pt"]
