#!/usr/bin/env bash
# Get this machine from "cloned" to "can produce a gated video".
#
# The plugin system puts the files here; it cannot install ffmpeg, build a venv,
# or fetch a 3 GB ASR model. That is what this does. Everything it sets up is
# OPTIONAL except the first tier — the skill runs on ffmpeg, Pillow and numpy,
# and every missing extra skips cleanly rather than erroring.
#
#   ./install.sh            core only  (ffmpeg + Pillow + numpy)
#   ./install.sh --full     also the venv: word-timed captions, 简→繁, LLM steps
#
# doctor.py is the authority on what is missing. This script only acts on it.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$HERE/skills/yiibu"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

say() { printf '  %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

printf '\nyiibu — install\n%s\n' "----------------------------------------"

# ── ffmpeg ──────────────────────────────────────────────────────────────
if have ffmpeg; then
  say "✅ ffmpeg  $(command -v ffmpeg)"
else
  say "❌ ffmpeg missing — every cut, mix and encode needs it"
  if have brew; then
    say "   installing with brew..."; brew install ffmpeg || say "   brew install failed; install ffmpeg by hand"
  elif have apt-get; then
    say "   installing with apt..."; sudo apt-get update && sudo apt-get install -y ffmpeg || say "   apt install failed; install ffmpeg by hand"
  else
    say "   no brew or apt found. Install ffmpeg, then run this again."
    exit 1
  fi
fi

# ── the two Python packages the whole pipeline rests on ─────────────────
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { say "❌ python3 not found — need 3.9 or newer"; exit 1; }
say "✅ python3 $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
say "   installing pillow and numpy..."
"$PY" -m pip install --quiet --upgrade pillow numpy || {
  say "   pip failed. If this is a managed python, try: python3 -m pip install --user pillow numpy"
  exit 1
}

# ── optional venv ───────────────────────────────────────────────────────
if [ "$FULL" = "1" ]; then
  say ""
  say "--full: building the venv for speech captions"
  say "   (first transcription downloads ~3 GB; drop WHISPER_MODEL to 'medium' in config.py if RAM is tight)"
  "$PY" -m venv "$SKILL/.venv" || { say "   venv creation failed"; exit 1; }
  "$SKILL/.venv/bin/pip" install --quiet --upgrade pip
  "$SKILL/.venv/bin/pip" install --quiet faster-whisper opencc google-genai requests auto-editor || {
    say "   some venv packages failed — the features they unlock will skip cleanly"
  }
  say "✅ venv at skills/yiibu/.venv"
else
  say ""
  say "Skipped the venv. Word-timed speech captions need it:  ./install.sh --full"
fi

# ── API keys are per-user and this script will not invent them ──────────
say ""
say "API keys (each unlocks one feature, none required) go at the skill root:"
say "   echo YOUR_PEXELS_KEY  > $SKILL/.env.pexels     # stock B-roll, free"
say "   echo YOUR_PIXABAY_KEY > $SKILL/.env.pixabay    # stock B-roll fallback"
say "   Gemini/OpenAI are read from your shell env — see skills/yiibu/SETUP.md"

# ── the real verdict ────────────────────────────────────────────────────
printf '\n%s\n' "----------------------------------------"
say "Handing over to doctor.py, which is the authority:"
printf '\n'
cd "$SKILL" && exec "$PY" doctor.py
