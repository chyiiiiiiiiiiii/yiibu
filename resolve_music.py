#!/usr/bin/env python3
"""Resolve a music bed WITHOUT ever stalling the pipeline.

The music step used to be the one place a build could stop and wait for a human:
the user says "音樂：<artist> — <title>" and the agent has a name, not a file. It
would then either ask and halt, or silently ship no music at all.

This resolves a name or a path to an actual audio file through a ladder that
ALWAYS terminates, and reports which rung answered so the caller can label the
deliverable honestly.

    from resolve_music import resolve
    r = resolve("MELODY M.Sasuke", project_dir=PROJ)
    r.path      -> an audio file that exists, or None only for mode="none"
    r.exact     -> True if this is the track the user actually named
    r.tag       -> filename tag for the deliverable, e.g. "melody" / "standin-chill"
    r.note      -> one line to repeat back to the user

Rungs, in order:

 1. an explicit path the user gave (or a URL to a file they own)
 2. any audio file sitting in <project_dir>/music/  — the drop-in slot
 3. a filename match for the requested name inside bgm-library/
 4. a mood pick from bgm-library/  — the stand-in

Rung 4 is a STAND-IN, not the requested track, and says so. A commercially
released song named by artist/title is not something this pipeline can obtain:
streaming rips are off the table, so the only way that exact track lands in the
video is the user dropping the file into <project_dir>/music/. Ship the stand-in,
name it `-standin-`, tell the user the one move that swaps it, and keep going —
a build that stops is worse than a build with a placeholder bed.
"""
import os
import re
import sys
import glob
from dataclasses import dataclass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(SKILL_DIR, "bgm-library")
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".aif", ".aiff")

# Which library mood to reach for when all we have is a vibe word.
MOOD_HINTS = {
    "chill": ("chill", "lofi", "lo-fi", "calm", "relax", "輕鬆", "放鬆", "慢"),
    "energetic": ("energetic", "hype", "upbeat", "fast", "快", "熱血", "動感"),
    "inspiring": ("inspiring", "uplifting", "epic", "勵志", "激勵", "感動"),
    "dramatic": ("dramatic", "tense", "dark", "緊張", "戲劇"),
}
DEFAULT_MOOD = "chill"


@dataclass
class Music:
    path: str | None
    exact: bool
    tag: str
    note: str
    rung: str


def _audio_in(d):
    if not d or not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if f.lower().endswith(AUDIO_EXT) and not f.startswith("."):
            out.append(os.path.join(d, f))
    return out


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _mood_for(request):
    r = (request or "").lower()
    for mood, words in MOOD_HINTS.items():
        if any(w in r for w in words):
            return mood
    return DEFAULT_MOOD


def resolve(request=None, project_dir=None, mood=None):
    """request: a path, a track name, a vibe word, or None."""
    # ── rung 1: an explicit file the user pointed at ──────────────
    if request and os.path.isfile(os.path.expanduser(request)):
        p = os.path.expanduser(request)
        return Music(p, True, _slug(os.path.splitext(os.path.basename(p))[0])[:24],
                     f"用你指定的檔案 {os.path.basename(p)}", "explicit-path")

    # ── rung 2: the drop-in slot ──────────────────────────────────
    drop = os.path.join(project_dir or ".", "music")
    found = _audio_in(drop)
    if found:
        p = found[0]
        return Music(p, True, _slug(os.path.splitext(os.path.basename(p))[0])[:24],
                     f"用 music/ 裡的 {os.path.basename(p)}", "project-music-dir")

    # ── rung 3: the named track already in the library ────────────
    want = _slug(request)
    if want:
        for p in glob.glob(os.path.join(LIB, "**", "*"), recursive=True):
            if p.lower().endswith(AUDIO_EXT) and want and want in _slug(os.path.basename(p)):
                return Music(p, True, _slug(os.path.splitext(os.path.basename(p))[0])[:24],
                             f"曲庫裡就有 {os.path.basename(p)}", "library-name-match")

    # ── rung 4: a stand-in, clearly labelled ──────────────────────
    m = mood or _mood_for(request)
    pool = _audio_in(os.path.join(LIB, m)) or _audio_in(os.path.join(LIB, DEFAULT_MOOD))
    if not pool:
        pool = [p for p in glob.glob(os.path.join(LIB, "**", "*"), recursive=True)
                if p.lower().endswith(AUDIO_EXT)]
    if not pool:
        return Music(None, False, "nomusic",
                     "曲庫是空的，這支只出無配樂版", "empty-library")
    p = sorted(pool)[0]
    asked = f"「{request}」" if request else "指定曲"
    return Music(p, False, f"standin-{m}",
                 f"{asked} 這條管線拿不到（商業發行曲不會去串流平台抓），"
                 f"先用曲庫的 {os.path.basename(p)} 當暫用床。"
                 f"把檔案丟進 {os.path.join(project_dir or 'PROJECT_DIR', 'music')}/ 就會換掉，"
                 f"其他都不用重做", "library-standin")


if __name__ == "__main__":
    r = resolve(sys.argv[1] if len(sys.argv) > 1 else None,
                project_dir=sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"rung   : {r.rung}")
    print(f"path   : {r.path}")
    print(f"exact  : {r.exact}")
    print(f"tag    : {r.tag}")
    print(f"note   : {r.note}")
