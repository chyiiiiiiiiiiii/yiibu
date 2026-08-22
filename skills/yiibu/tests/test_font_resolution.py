"""The font ladder, which decides whether the video is in the house typeface.

This file exists because the ladder had no test at all, and the one failure it
can produce is invisible from the output side:

`gate_typography` compares the Fontname DECLARED in the .ass against
`house_style.json`. libass, meanwhile, does not fail on a font it cannot find —
it substitutes one and exits 0. Measured on 2026-08-22: an .ass naming
`ThisFontDoesNotExist12345` rendered legible CJK text, ffmpeg returned 0, and
the declared name still matched the house style. A machine without the font
installed therefore ships a video in the wrong typeface with every gate green.

The only thing standing between a fresh clone and that is `ensure_fonts()`,
which was called from `postprod.py` alone — leaving template mode, the
folder-of-clips path a new user runs first, unprovisioned. So the rule under
test is not "the font resolves" but "provisioning happens on the path that
burns captions", which is a wiring fact a test can hold and a gate cannot.
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "modules")]

import buildkit as bk  # noqa: E402
import title  # noqa: E402

SYSTEM_CJK = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def _have_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-version"],
                       capture_output=True, check=False)
        return True
    except (FileNotFoundError, OSError):
        return False


# ── the wiring that was missing ─────────────────────────────────────────

def test_burning_captions_provisions_the_house_font_first(monkeypatch, tmp_path):
    """The defect: only postprod.py called ensure_fonts, so template-mode
    builds burned captions against whatever libass happened to have."""
    calls = []
    monkeypatch.setattr(title, "ensure_fonts", lambda: calls.append("ensure"))
    monkeypatch.setattr(bk, "run", lambda *a, **k: calls.append("ffmpeg"))

    out = bk.burn_subtitles(str(tmp_path / "in.mp4"), str(tmp_path / "s.ass"),
                            str(tmp_path / "out.mp4"))

    assert out == str(tmp_path / "out.mp4")
    assert calls == ["ensure", "ffmpeg"], (
        "the font must be provisioned BEFORE ffmpeg runs, not after and not "
        f"at all — got {calls}")


def test_ensure_fonts_installs_the_bundled_file_and_is_idempotent(monkeypatch,
                                                                  tmp_path):
    """It runs on every burn now, so a second call must cost nothing."""
    dest = tmp_path / "fonts"
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(dest) if "Fonts" in p or "fonts" in p else p)
    copied = []
    import shutil
    real_copy = shutil.copy2
    monkeypatch.setattr(shutil, "copy2",
                        lambda s, d: (copied.append(d), real_copy(s, d))[1])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)

    title.ensure_fonts()
    assert copied, "the bundled font was never installed"
    first = list(copied)

    title.ensure_fonts()
    assert copied == first, "a second call re-copied; ensure_fonts is not idempotent"


# ── the ladder, rung by rung ────────────────────────────────────────────

def test_an_explicit_font_file_beats_every_other_rung(monkeypatch, tmp_path):
    f = tmp_path / "mine.otf"
    f.write_bytes(b"not really a font, but it exists")
    monkeypatch.setenv("YIIBU_FONT_FILE", str(f))
    assert title._find_font() == str(f)


def test_the_bundled_asset_is_the_last_resort_when_nothing_else_answers(
        monkeypatch):
    """Rung 4 is what a fresh Linux clone with no CJK font actually gets.
    Nothing exercised it before, so nobody would have noticed it breaking."""
    def _no_fc_match(*_a, **_k):
        raise FileNotFoundError("fc-match is not installed on this machine")

    monkeypatch.delenv("YIIBU_FONT_FILE", raising=False)
    monkeypatch.setattr(title.subprocess, "run", _no_fc_match)
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists",
                        lambda p: False if p in SYSTEM_CJK else real_exists(p))

    got = title._find_font()
    assert got.startswith(title.BUNDLED_FONTS_DIR), (
        f"expected the bundled font, got {got}")
    assert real_exists(got), "the bundled font the ladder points at is not there"


def test_the_bundled_font_is_present_and_openable():
    """NOTICE.md and doctor.py both promise 'bundled — no install needed'."""
    from PIL import ImageFont
    files = [f for f in os.listdir(title.BUNDLED_FONTS_DIR)
             if f.lower().endswith((".otf", ".ttf", ".ttc"))]
    assert files, "assets/fonts ships no font, but the docs promise one"
    for f in files:
        ImageFont.truetype(os.path.join(title.BUNDLED_FONTS_DIR, f), 48)


# ── the measurement the fix is built on ─────────────────────────────────

@pytest.mark.skipif(not _have_ffmpeg(), reason="needs ffmpeg")
def test_libass_substitutes_a_missing_font_instead_of_failing(tmp_path):
    """Reconstructs the defect: this is WHY provisioning has to be wired in
    rather than checked for. If this ever starts failing loudly, the fix above
    can be reconsidered — until then, silence is the whole problem."""
    ass = tmp_path / "s.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 540\nPlayResY: 960\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: D,ThisFontDoesNotExist12345,60,&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,10,10,10,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,D,,0,0,0,,一步剪片測試\n",
        encoding="utf-8")
    png = tmp_path / "f.png"
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=540x960:d=1",
         "-vf", f"ass={ass}", "-frames:v", "1", str(png)],
        capture_output=True, text=True)

    assert r.returncode == 0, "ffmpeg errored — the premise of the fix changed"
    from PIL import Image
    lit = sum(1 for p in Image.open(png).convert("L").getdata() if p > 20)
    assert lit > 500, (
        "a nonexistent font produced no glyphs; if libass now renders nothing "
        "instead of substituting, gate_typography's blind spot is closed and "
        "this test should be rewritten around the new behaviour")
