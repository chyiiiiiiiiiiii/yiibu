#!/usr/bin/env python3
"""Event 花絮 — the video spine: cut every segment, concat, write the timeline.

Distilled from the `dev-jam-2026` build, which is the project docs/WALKTHROUGH.md
follows: a student hackathon demo day, 43 clips of 996s cut to a 90.15s bilingual
short over 29 segments. The shape is real; the paths are parameterised.

This is the half the other files in this directory assume already ran.
`captions.py` reads `timeline.json`, `render.py` reads `concat.txt`, and neither
can tell you where those come from. This file is the answer.

Two things it demonstrates that matter more than the segment list:

**Compose buildkit primitives, do not hand-write ffmpeg.** `prep_segment` and
`concat` carry the traps — hardware encoding, PCM intermediates, CFR, the
rotation check. A hand-rolled graph re-derives them, badly, and the 2026-08-17
build lost about 45 minutes doing exactly that. Importing buildkit also self-lints
THIS file: a build script carrying a known slow/hang antipattern refuses to start
rather than stalling twenty minutes in.

**The edit decision list is data, and the reasoning lives with it.** Every row is
`(id, file, tin, tout, gain, note)`. The `note` is not decoration — it is how
anyone (including you, next week) reads the story order without opening the
video. Keep the story rationale in this file's docstring, not in your head.

    python3 vp_build.py            # writes segments/, spine.mov, timeline.json
"""
import json
import os
import pathlib
import sys

# The skill can live anywhere; YIIBU_SKILL_DIR wins, then a sensible default.
SKILL = os.environ.get(
    "YIIBU_SKILL_DIR",
    os.path.expanduser("~/.claude/skills/video-postprod"))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

from modules import buildkit as bk           # noqa: E402  (self-lints this file)

WORK = pathlib.Path(os.environ.get("WORK_DIR", os.path.dirname(
    os.path.abspath(__file__))))
SRC = pathlib.Path(os.environ.get("SRC_DIR",
                                  os.path.expanduser("~/Downloads/your_footage")))
SEGD = WORK / "segments"

# (id, file, tin, tout, gain, note)
#
# Gains are MEASURED, never guessed: read each clip's peak, target about
# -4 dBFS stereo, then re-measure the render — the delivery gate downmixes to
# mono and correlated stereo gains ~3 dB there. 1.00 means the clip was already
# where it needed to be, which is the common case for anything recorded at
# conversational distance.
#
# In the source build every segment kept its ORIGINAL level, and decisions.json
# records why: the event template gates ambience down because an expo hall is
# noise under a music bed, but this was a quiet auditorium where the room IS the
# content. Attenuating it put 11.25s of the no-music version — the honest record
# of the day — under the silence floor. Only one presenter, far louder than the
# rest of the room, needed pulling down.
SEGMENTS = [
    # ── ACT 1 — arrival ──────────────────────────────────────────────
    ("s01", "hook.MP4",        15.30, 18.50, 1.00, "HOOK — the strangest image in the folder"),
    ("s02", "pass_on_desk.MOV", 0.15,  1.65, 1.00, "the detail that says where you are"),
    ("s03", "walking_in.mov",   0.25,  2.25, 1.00, "walking in"),
    ("s04", "wide_room.MOV",    0.60,  3.30, 1.00, "the room, wide"),

    # ── ACT 2 — one block per subject: thing → detail → a voice ──────
    # Every block ends on someone talking. Blocks that ended on a still read as
    # skipped over, and evening them out at three shots each fixed it.
    ("s05", "team_a_title.mov", 0.05,  0.95, 1.00, "A — title card"),
    ("s06", "team_a_demo.MOV",  1.40,  5.00, 1.00, "A — the thing working"),
    ("s07", "team_a_q.MOV",     1.20,  4.60, 1.00, "A — a question worth hearing"),

    ("s08", "team_b_title.MOV", 0.10,  1.10, 1.00, "B — title card"),
    ("s09", "team_b_demo.MOV",  2.00,  5.20, 1.00, "B — the thing working"),
    ("s10", "team_b_q.MOV",     0.80,  4.30, 0.85, "B — presenter is louder than the room"),

    # ── ACT 3 — close ────────────────────────────────────────────────
    ("s11", "closing.MOV",      1.00,  4.00, 1.00, "the beat the day actually ended on"),
]


def build_timeline():
    rows, t = [], 0.0
    for sid, fname, tin, tout, gain, note in SEGMENTS:
        dur = round(tout - tin, 3)
        rows.append({"id": sid, "file": fname, "tin": tin, "tout": tout,
                     "gain": gain, "dur": dur, "start": round(t, 3),
                     "note": note})
        t += dur
    return rows, round(t, 3)


def main():
    SEGD.mkdir(parents=True, exist_ok=True)
    segs, total = build_timeline()
    print(f"{len(segs)} segments, {total:.2f}s")

    parts = []
    for s in segs:
        dst = str(SEGD / f"{s['id']}.mov")
        if not os.path.exists(dst):          # re-runnable: only cut what is missing
            bk.prep_segment(str(SRC / s["file"]), s["tin"], s["tout"], dst,
                            gain=s["gain"])
            print(f"  {s['id']} {s['dur']:5.2f}s gain {s['gain']:.2f}  {s['note']}",
                  flush=True)
        parts.append(dst)

    spine = str(WORK / "spine.mov")
    bk.concat(parts, spine)

    # captions.py reads this; render.py reads concat.txt. Writing both here is
    # what lets the rest of the pipeline stay ignorant of how the cut was made.
    json.dump({"total": total, "segments": segs},
              open(WORK / "timeline.json", "w"), ensure_ascii=False, indent=1)
    with open(WORK / "concat.txt", "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    # Assert, do not hope: a concat that silently drops a segment is invisible
    # until someone watches the whole thing.
    got = bk.dur(spine)
    print(f"\nspine: {got:.2f}s  (timeline says {total:.2f}s)")
    if abs(got - total) > 0.15:
        raise SystemExit(f"spine is {got:.2f}s but the timeline says {total:.2f}s")


if __name__ == "__main__":
    main()
