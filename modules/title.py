"""Rounded-corner top title overlay (persistent or opening-only).

Renders a semi-transparent rounded pill with centred title text at a configurable
vertical position (as a fraction of frame height), then overlays it on the composed
video — either for the whole duration ("persistent") or only the opening ("start").
"""
import os
import shutil
import subprocess
import sys

from config import OUTPUT_WIDTH, OUTPUT_HEIGHT, FONT_NAME

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED_FONTS_DIR = os.path.join(SKILL_DIR, "assets", "fonts")


def ensure_fonts() -> None:
    """Install any skill-bundled fonts into ~/Library/Fonts so libass/fontconfig
    can resolve them by family name. Makes the skill self-contained — the video
    renders correctly even if the font is only bundled here (no external copy)."""
    if not os.path.isdir(BUNDLED_FONTS_DIR):
        return
    if sys.platform == "darwin":
        dest_dir = os.path.expanduser("~/Library/Fonts")
    else:
        dest_dir = os.path.expanduser("~/.local/share/fonts")   # fontconfig's user dir
    os.makedirs(dest_dir, exist_ok=True)
    installed = False
    for fn in os.listdir(BUNDLED_FONTS_DIR):
        if fn.lower().endswith((".otf", ".ttf", ".ttc")):
            dest = os.path.join(dest_dir, fn)
            if not os.path.exists(dest):
                shutil.copy2(os.path.join(BUNDLED_FONTS_DIR, fn), dest)
                installed = True
    if installed:
        try:
            subprocess.run(["fc-cache", "-f", dest_dir], capture_output=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass


def _find_font() -> str:
    """Resolve the caption/title font.

    Order matters and is deliberate — the user's own choice wins, the system
    provides the default, and the bundled file is only a last resort:

      1. explicit config: $VIDEO_POSTPROD_FONT, or FONT_FILE in config.py
      2. a font matching FONT_NAME that the user has installed (fc-match)
      3. a system CJK font
      4. the bundled asset

    Bundling used to come first, which made the repo carry a 9MB font that every
    clone was forced to use. Defaulting to the system font keeps a fresh install
    working with zero setup and zero redistribution question, while anyone who
    installs FONT_NAME (or points VIDEO_POSTPROD_FONT at a file) still gets
    exactly the house look.
    """
    explicit = os.environ.get("VIDEO_POSTPROD_FONT")
    if not explicit:
        try:
            from config import FONT_FILE as explicit    # optional in config.py
        except ImportError:
            explicit = None
    if explicit and os.path.exists(os.path.expanduser(explicit)):
        return os.path.expanduser(explicit)

    try:
        out = subprocess.run(
            ["fc-match", f"{FONT_NAME}", "--format=%{file}"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        # fc-match always answers; only trust it if it actually found FONT_NAME
        if out and os.path.exists(out) and FONT_NAME in out:
            return out
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    for p in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ):
        if os.path.exists(p):
            return p

    if os.path.isdir(BUNDLED_FONTS_DIR):
        for fn in sorted(os.listdir(BUNDLED_FONTS_DIR)):
            if fn.lower().endswith((".otf", ".ttf", ".ttc")):
                return os.path.join(BUNDLED_FONTS_DIR, fn)
    raise FileNotFoundError("No CJK font found; set VIDEO_POSTPROD_FONT")


def render_title_png(text: str, out_path: str, pct: float = 0.18, font_size: int = 56) -> str:
    """Render a transparent full-frame PNG with a rounded title pill centred at `pct` height."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
    font = ImageFont.truetype(_find_font(), font_size)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    padx, pady = 40, 24
    pw, ph = tw + padx * 2, th + pady * 2
    yc = int(pct * H)
    x0 = (W - pw) // 2
    y0 = yc - ph // 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph // 2, fill=(0, 0, 0, 175))
    d.text((x0 + padx - bb[0], y0 + pady - bb[1]), text, font=font, fill=(255, 255, 255, 255))
    img.save(out_path)
    return out_path


def overlay_title(
    video_in: str,
    video_out: str,
    text: str,
    work_dir: str,
    pct: float = 0.18,
    mode: str = "persistent",
    start_dur: float = 7.5,
    font_size: int = 56,
) -> str:
    """Overlay the rounded title onto a composed video.

    mode="persistent" → title stays the whole video.
    mode="start"       → title only for the first `start_dur` seconds (fade in/out).
    """
    png = os.path.join(work_dir, "top_title.png")
    render_title_png(text, png, pct=pct, font_size=font_size)

    if mode == "start":
        # HARD CUT, no alpha fade — house default. The pill is a label, and a
        # label that dissolves reads as a rendering glitch on a fast feed cut;
        # captions switch the same way (SUBTITLE_FADE_IN_MS = 0).
        filt = (
            f"[0:v][1:v]overlay=0:0:enable='between(t,0,{start_dur:.2f})':"
            f"format=auto[v]"
        )
        inputs = ["-i", video_in, "-loop", "1", "-t", f"{start_dur + 1:.2f}", "-i", png]
    else:
        filt = "[0:v][1:v]overlay=0:0:format=auto[v]"
        inputs = ["-i", video_in, "-i", png]

    cmd = (
        ["ffmpeg", "-nostdin", "-y"] + inputs
        + ["-filter_complex", filt, "-map", "[v]", "-map", "0:a",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-c:a", "copy", video_out]
    )
    subprocess.run(cmd, check=True, capture_output=True)
    return video_out
