#!/usr/bin/env python3
"""Check this machine can run the skill, and say exactly what to install.

Run this first on a new machine. Everything REQUIRED here is needed to produce
and gate a video; everything OPTIONAL unlocks one extra feature and is skipped
cleanly when absent — the skill is designed so a fresh clone works with ffmpeg
and two Python packages, not a configuration session.

    python3 doctor.py
"""
import importlib
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

OK, WARN, BAD = "✅", "⚠️ ", "❌"
problems = []


def say(mark, what, detail=""):
    print(f"  {mark} {what}" + (f"  {detail}" if detail else ""))


def need_bin(name, why, install):
    p = shutil.which(name)
    if p:
        say(OK, name, p)
    else:
        say(BAD, name, f"— {why}. install: {install}")
        problems.append(name)


def opt_bin(name, why, install):
    p = shutil.which(name)
    say(OK if p else WARN, name, p if p else f"— optional: {why}. install: {install}")


def need_mod(name, install):
    try:
        m = importlib.import_module(name)
        say(OK, name, getattr(m, "__version__", ""))
    except ImportError:
        say(BAD, name, f"— install: {install}")
        problems.append(name)


def opt_mod(name, why, install):
    try:
        m = importlib.import_module(name)
        say(OK, name, getattr(m, "__version__", ""))
    except ImportError:
        say(WARN, name, f"— optional: {why}. install: {install}")


def main():
    print("\nyiibu — environment check\n" + "-" * 52)

    ff = ("brew install ffmpeg" if sys.platform == "darwin"
          else "apt install ffmpeg (or your distro's equivalent)")
    print("\n REQUIRED")
    need_bin("ffmpeg", "every render and every gate", ff)
    need_bin("ffprobe", "duration/stream probing", ff)
    need_mod("PIL", "pip install pillow")
    need_mod("numpy", "pip install numpy")

    print("\n FONT (bundled — no install needed)")
    try:
        from title import _find_font
        f = _find_font()
        say(OK if os.path.exists(f) else BAD, "caption font", f)
        if not os.path.exists(f):
            problems.append("font")
    except Exception as e:                                    # noqa: BLE001
        say(BAD, "caption font", str(e))
        problems.append("font")

    print("\n OPTIONAL — each unlocks one feature, skipped cleanly if missing")
    opt_mod("requests", "stock B-roll (Pexels/Pixabay)", "pip install requests")
    opt_mod("cv2", "face-aware caption placement", "pip install opencv-python")
    opt_mod("auto_editor", "silence removal / clap-to-delete",
            "pip install auto-editor")
    opt_mod("playwright", "website-screenshot B-roll",
            "pip install playwright && playwright install chromium")
    opt_bin("yt-dlp", "official B-roll and music sourcing",
            "brew install yt-dlp" if sys.platform == "darwin" else "pip install yt-dlp")
    opt_bin("gemini", "URL resolution + BGM mood analysis",
            "npm install -g @google/gemini-cli")
    venv = os.path.join(SKILL, ".venv", "bin", "python3")
    if os.path.exists(venv):
        say(OK, "ASR venv", venv)
    else:
        say(WARN, "ASR venv",
            "— optional: speech captions + SDK steps. "
            f"python3 -m venv {SKILL}/.venv && {SKILL}/.venv/bin/pip install "
            f"faster-whisper opencc google-genai requests auto-editor")

    lib = os.path.join(SKILL, "bgm-library")
    tracks = [f for _, _, fs in os.walk(lib) for f in fs
              if f.lower().endswith((".mp3", ".m4a", ".wav"))]
    say(OK if tracks else WARN, "bgm-library",
        f"{len(tracks)} track(s)" if tracks else
        "— empty: music bed will resolve to 'no music'. See bgm-library/README.md")

    print("\n SELF-TEST")
    for label, script in (("shipping gates", "test_gates.py"),
                          ("house style", "test_house_style.py")):
        r = subprocess.run([sys.executable, os.path.join(SKILL, "tests", script)],
                           capture_output=True, text=True)
        last = [l for l in r.stdout.splitlines() if "passed" in l]
        say(OK if r.returncode == 0 else BAD, label,
            last[-1].strip() if last else "did not run")
        if r.returncode != 0:
            problems.append(label)

    print("\n" + "-" * 52)
    if problems:
        print(f"  {BAD} not ready — fix: {', '.join(problems)}\n")
        return 1
    print(f"  {OK} ready. Next:  python3 plan.py YOUR_FOOTAGE_DIR\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
