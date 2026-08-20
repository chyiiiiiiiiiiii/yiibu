# EXAMPLE — companion to captions.py in this folder; see its header.
#!/usr/bin/env python3
"""concat -> burn captions + PIL pills -> single AAC encode -> delivery gate.

The pills come from the skill's own modules/title.py renderer, so they match
雅香石頭火鍋-花絮-v10 exactly: PIL-antialiased rounded capsule, width hugging the
text, 69%-opaque black, centred at 18% of frame height.

Each pill is baked into a short finite alpha clip (qtrle) BEFORE it reaches the
overlay — `-loop 1 -i pill.png` feeding an overlay never EOFs and hangs ffmpeg
forever (references/delivery-traps.md #6).

Captions and pills are composited in ONE pass so the picture is encoded once and
the AAC encode happens exactly once (delivery-traps #3).
"""
import json
import os
import subprocess
import sys

# Skill root: env override, else walk up from this file (it ships inside the
# skill at references/examples/event-vlog/), else the historical install path.
def _skill_root():
    env = os.environ.get("YIIBU_SKILL_DIR")
    if env and os.path.exists(os.path.join(env, "house_style.json")):
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(d, "house_style.json")):
            return d
        d = os.path.dirname(d)
    return os.path.expanduser("~/.claude/skills/video-postprod")


SKILL = _skill_root()
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]
from title import render_title_png  # noqa: E402

B = os.path.dirname(os.path.abspath(__file__))
PILL_DIR = f"{B}/pills"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Desktop/2026-google-io-connect-shanghai-day1-v3.mp4")
FADE = 0.22

# --- optional music bed (BGM_PATH env var) ---------------------------------
# The original recording is the payload, so it stays on top; the music sits under
# it and ducks further whenever speech is present. Levels follow the food-vlog
# recipe (references/food-vlog-template.md #7): attenuate the original just enough
# that原聲 + music cannot sum past full scale. Verified on the DECODED file after.
BGM_PATH = os.environ.get("BGM_PATH")
# Cover is burned onto frame 1 only (not prepended as a segment) so no caption
# timing shifts. The standalone JPG ships alongside the video.
COVER = os.environ.get("COVER", f"{B}/cover_c.jpg")
# levels, ducking and the chorus offset all live in mix_bgm.py
PILL_SIZE = 56        # house starting point; render_title_png only comes DOWN
PILL_PCT = json.load(open(os.path.join(SKILL, "house_style.json")))["pill"]["centre_pct"]

os.makedirs(PILL_DIR, exist_ok=True)


def pill_width(png):
    """Rendered width of the capsule inside the full-frame transparent PNG."""
    from PIL import Image
    import numpy as np
    al = np.asarray(Image.open(png).convert("RGBA"))[:, :, 3]
    xs = np.where(al.sum(axis=0) > 0)[0]
    return int(xs[-1] - xs[0] + 1) if len(xs) else 0


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(cmd[:12]), "...")
        print(r.stderr[-3000:])
        sys.exit(1)


print("[1/4] concat segments")
run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{B}/concat.txt",
     "-c:v", "libx264", "-preset", "medium", "-crf", "18",
     "-fps_mode", "cfr", "-r", "30", "-c:a", "pcm_s16le", "-y", f"{B}/rough.mov"])

AUDIO_MAP = "0:a"
if BGM_PATH:
    print("[1b/4] music mix (mix_bgm.py: original only where someone talks)")
    subprocess.run([sys.executable, f"{B}/mix_bgm.py"], check=True)
    AUDIO_MAP = f"{1 + (1 if (COVER and os.path.exists(COVER)) else 0)}:a"

pills = json.load(open(f"{B}/pills.json"))
print(f"[2/4] render {len(pills)} pills via modules/title.py")
clips = []
for i, p in enumerate(pills):
    png = f"{PILL_DIR}/p{i:02d}.png"
    # No shrink loop here any more: render_title_png reads pill.max_w_ratio from
    # house_style.json and steps the font down itself. Every build script used to
    # carry its own copy of that loop, and one that forgot shipped a banner-wide
    # pill that only gate_pill caught, at hand-over.
    render_title_png(p["text"], png, pct=PILL_PCT, font_size=PILL_SIZE)
    dur = round(p["end"] - p["start"], 3)
    clip = f"{PILL_DIR}/p{i:02d}.mov"
    # finite alpha clip: -loop 1 is safe here because -t bounds it and the result
    # is a real file, not a live input into overlay
    run(["ffmpeg", "-v", "error", "-loop", "1", "-i", png, "-t", str(dur),
         "-vf", (f"fps=30,format=rgba,"
                 f"fade=t=in:st=0:d={FADE}:alpha=1,"
                 f"fade=t=out:st={max(0, dur - FADE):.3f}:d={FADE}:alpha=1"),
         "-c:v", "qtrle", "-y", clip])
    clips.append((clip, p["start"], p["end"]))

print("[3/4] burn captions + overlay pills (one video encode)")
inputs = ["-i", f"{B}/rough.mov"]
if COVER and os.path.exists(COVER):
    inputs += ["-i", COVER]
if BGM_PATH:
    inputs += ["-i", f"{B}/mixed.wav"]
for c, _, _ in clips:
    inputs += ["-i", c]
chain = [f"[0:v]ass={B}/captions.ass[base]"]
cur = "base"
first_pill_input = 1 + (1 if (COVER and os.path.exists(COVER)) else 0) + (1 if BGM_PATH else 0)
for i, (_, st, en) in enumerate(clips):
    chain.append(f"[{i+first_pill_input}:v]setpts=PTS-STARTPTS+{st}/TB[q{i}]")
    nxt = f"v{i}"
    chain.append(f"[{cur}][q{i}]overlay=0:0:enable='between(t,{st},{en})':"
                 f"eof_action=pass:format=auto[{nxt}]")
    cur = nxt
if COVER and os.path.exists(COVER):
    chain.append(f"[1:v]scale=1080:1920,setsar=1[cov]")
    chain.append(f"[{cur}][cov]overlay=0:0:enable='lt(t,0.034)'[vc]")
    cur = "vc"
run(["ffmpeg", "-v", "error", *inputs, "-filter_complex", ";".join(chain),
     "-map", f"[{cur}]", "-map", AUDIO_MAP,
     "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
     "-fps_mode", "cfr", "-r", "30",
     "-c:a", "aac", "-b:a", "256k" if BGM_PATH else "192k", "-movflags", "+faststart", "-y", OUT])

print("[4/4] delivery gate + mix gate")
subprocess.run(["cp", f"{B}/captions.ass", f"{B}/subtitles.ass"])
subprocess.run(["python3", os.path.join(SKILL, "verify.py"), B, "--output", OUT])
rc = subprocess.run([sys.executable, f"{B}/check_mix.py", OUT]).returncode
if rc:
    print("\n  render produced a bad mix — NOT shippable")
    sys.exit(rc)
print(OUT)
