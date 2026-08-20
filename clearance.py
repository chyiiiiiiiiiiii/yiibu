#!/usr/bin/env python3
"""Is any of this footage somebody else's to release?

Written after a 93.6s conference recap was cut, captioned, gated green and
handed over — and then the event organiser pointed out that 41 of those seconds
were under NDA. Reviewing the frames confirmed it was not a judgement call: one
slide carried "GA: September (Tentative)" next to a full pricing table, another
was an unreleased model's spec sheet, and a third segment was named Google staff
answering a roadmap question on stage. Fourteen gates were green throughout,
because not one of them is about who owns the content.

**This does not decide anything.** It cannot: "is this embargoed" depends on
facts that exist nowhere in the pixels — what was announced that morning, what
the organiser told the room, which slide had a footer nobody filmed. What it
does is notice when footage *looks like* session material and put the question in
front of the person who can answer it, before the cutting starts rather than
after the upload.

Two stages:

  1. **Filenames** — free, always runs. `IMG_3353_devrel_sharing`,
     `..._gde_lighting_talk`, `..._ask_question` were all sitting there in the
     folder that shipped the NDA cut. Measured against that folder it found every
     session-named clip. It is weak evidence and it misses anything the camera
     named `IMG_3370.MOV`, which is why it is not the whole answer.
  2. **Reading a frame** — one small vision call per clip. Deliberately NOT a
     keyword list: real decks do not agree on wording, they are multilingual, and
     a fixed list only catches the phrasing whoever wrote the list had already
     seen. The model is asked what it can see and whether a reasonable organiser
     would mind it being public, and it returns the evidence so a person can
     overrule it. `--no-deep` skips this and costs nothing.

There was a third stage between them — a local pixel heuristic meant to spot a
projection screen for free and keep the vision calls down. It is not here because
it did not work. Measured against 23 clips whose contents are known, the first
version scored an empty sky 1.00 and the AlloyDB slide 0.01; tightening it until
the sky went away also dropped ten of the thirteen real slides. Bright and
desaturated describes a window as well as a screen. A detector measured to be
wrong is worse than no detector, because the zero it returns looks like an
answer.

`clearance_scan.json` is written every time, including when nothing is found.
That file is the always-present artifact: `gate_clearance` reads it, so "we never
ran the scan" and "the scan found nothing" cannot look the same.

    python3 clearance.py FOOTAGE_DIR --work-dir WORK_DIR
    python3 clearance.py FOOTAGE_DIR --work-dir WORK_DIR --json
"""
import argparse
import json
import os
import re
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [SKILL_DIR, os.path.join(SKILL_DIR, "modules")]
# The .venv (which holds google-genai) may live with an installed copy of the
# skill rather than next to a clone. Same override the rest of the code honours.
VENV_ROOT = os.environ.get("YIIBU_SKILL_DIR", SKILL_DIR)

VIDEO_EXT = (".mov", ".mp4", ".m4v", ".avi")

# ── stage 1 ─────────────────────────────────────────────────────────────
# Words that suggest a clip points at a stage rather than at the day around it.
# Weak evidence on purpose: a hit nominates a clip for a closer look, it does not
# accuse it of anything. Every one of these appeared in the folder that shipped
# the NDA cut.
SESSION_WORDS = [
    "session", "talk", "keynote", "roundtable", "panel", "sharing",
    "presentation", "demo_day", "pitch", "briefing", "update", "q&a", "qa",
    "ask_question", "lighting_talk", "lightning", "workshop", "slide",
    "開場", "演講", "分享", "簡報", "座談", "提問", "議程",
]
_SESSION_RE = re.compile("|".join(re.escape(w) for w in SESSION_WORDS), re.I)


def triage_filename(name):
    """Stage 1. Returns the matched words — empty means 'nothing in the name'."""
    stem = os.path.splitext(os.path.basename(name))[0]
    return sorted({m.group(0).lower() for m in _SESSION_RE.finditer(stem)})


def triage_names(names):
    """Stage 1 over a list of filenames -> {name: [words]} for the hits only."""
    return {n: w for n in names if (w := triage_filename(n))}


# ── frame helpers ───────────────────────────────────────────────────────

def _frames(path, count=3):
    """A few evenly spaced frames as raw RGB, small — this is a statistic, not a
    picture, so decoding at full resolution would be wasted work."""
    import numpy as np
    dur = _duration(path)
    if not dur:
        return []
    out = []
    for i in range(count):
        t = dur * (i + 1) / (count + 1)
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
             "-frames:v", "1", "-vf", "scale=160:-1", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-"],
            capture_output=True, stdin=subprocess.DEVNULL)
        buf = r.stdout
        if not buf:
            continue
        h = len(buf) // (160 * 3)
        if h:
            out.append(np.frombuffer(buf[:160 * h * 3],
                                     dtype=np.uint8).reshape(h, 160, 3))
    return out


def _duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0




# ── stage 2 — the model reads a frame ───────────────────────────────────

_PROMPT = """You are reviewing one frame from footage shot by an attendee at a \
private industry event, to help them decide what is safe to post publicly.

Look at what is actually visible. Do not speculate about what might be off-frame.

Answer as JSON, no other text:
{"visible": "<what is on any screen, sign or slide — quote text verbatim>",
 "concern": "none" | "possible" | "likely",
 "why": "<one sentence, citing only what you can see>"}

Use "likely" only when the frame shows something an organiser would plausibly \
not want public — an unreleased product or feature, a roadmap or release date, \
internal metrics, an explicit confidentiality marking, or named staff answering \
questions on stage. Use "none" for the venue, food, crowds, signage, swag, \
people socialising, or a talk whose slide carries nothing but a title. \
An ordinary conference talk is not automatically a concern."""


def read_frame(path, t, model=None):
    """Stage 2. Ask what is on screen and whether it looks releasable.

    Returns a dict, or a ``{"error": reason}`` — never None-meaning-fine. The
    caller records the reason verbatim, because "no key configured", "quota
    exhausted" and "the model looked and saw nothing" are three different
    situations and only one of them means the footage is clear.
    """
    from llm import resolve_gemini_key
    key = resolve_gemini_key()
    if not key:
        return {"error": "no Gemini key configured"}
    venv = os.path.join(VENV_ROOT, ".venv", "bin", "python3")
    if not os.path.exists(venv):
        return {"error": f"no .venv at {VENV_ROOT} (google-genai lives there)"}

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        jpg = os.path.join(td, "f.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
                        "-frames:v", "1", "-vf", "scale=768:-1", "-y", jpg],
                       capture_output=True, stdin=subprocess.DEVNULL)
        if not os.path.exists(jpg):
            return {"error": "could not extract a frame"}
        script = os.path.join(td, "ask.py")
        model = model or os.environ.get("YIIBU_CLEARANCE_MODEL",
                                        "gemini-2.5-flash")
        with open(script, "w") as f:
            f.write(
                "import json,sys\n"
                "from google import genai\n"
                "c = genai.Client()\n"
                f"img = open({json.dumps(jpg)}, 'rb').read()\n"
                "from google.genai import types\n"
                "r = c.models.generate_content(\n"
                f"    model={json.dumps(model)},\n"
                "    contents=[types.Part.from_bytes(data=img, mime_type='image/jpeg'),\n"
                f"              {json.dumps(_PROMPT)}])\n"
                "print(r.text)\n")
        env = {**os.environ, "GEMINI_API_KEY": key}
        r = subprocess.run([venv, script], capture_output=True, text=True,
                           timeout=90, env=env)
        raw = (r.stdout or "").strip()
        if not raw:
            err = (r.stderr or "").strip().splitlines()
            tail = err[-1] if err else "no output"
            # The most common one by far, and it is NOT "nothing to see here".
            if "RESOURCE_EXHAUSTED" in (r.stderr or ""):
                tail = "Gemini quota/spend cap exhausted"
            return {"error": tail[:200]}
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {"error": "model did not return JSON"}
        try:
            return json.loads(m.group(0))
        except ValueError:
            return {"error": "model returned malformed JSON"}


# ── the scan ────────────────────────────────────────────────────────────

def scan(footage_dir, work_dir=None, deep=True):
    """Run the stages and return the record. Always writes clearance_scan.json."""
    clips = sorted(f for f in os.listdir(footage_dir)
                   if f.lower().endswith(VIDEO_EXT))
    named = triage_names(clips)

    reads, findings, errors = {}, [], []
    if deep:
        for c in clips:
            path = os.path.join(footage_dir, c)
            dur = _duration(path)
            v = read_frame(path, dur / 2 if dur else 1.0)
            if "error" in v:
                errors.append(v["error"])
                break            # the same error will repeat for every clip
            reads[c] = v
            if v.get("concern") in ("possible", "likely"):
                findings.append({"file": c, "concern": v["concern"],
                                 "visible": v.get("visible", ""),
                                 "why": v.get("why", "")})

    if not deep:
        stage2 = "not run (--no-deep)"
    elif errors:
        stage2 = f"could not run — {errors[0]}"
    else:
        stage2 = f"read {len(reads)} clip(s)"

    # flagged = "a person has to answer a question", never "this is NDA".
    # An unanswerable stage 2 plus session-shaped names still raises the question:
    # not knowing is not the same as being clear.
    flagged = bool(findings) or (bool(named) and stage2.startswith(
        ("not run", "could not run")))

    record = {
        "footage_dir": os.path.abspath(footage_dir),
        "clips": len(clips),
        "stage1_filename_hits": named,
        "stage2": stage2,
        "reads": reads,
        "findings": findings,
        "flagged": flagged,
    }
    if work_dir:
        os.makedirs(work_dir, exist_ok=True)
        with open(os.path.join(work_dir, "clearance_scan.json"), "w",
                  encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
    return record


def report(rec):
    print(f"  {rec['clips']} clip(s) scanned  ·  stage 2: {rec['stage2']}")
    named = rec["stage1_filename_hits"]
    if named:
        print(f"\n  {len(named)} clip(s) named like session footage:")
        for n, words in named.items():
            print(f"    · {n:44s} {', '.join(words)}")
    for f in rec["findings"]:
        print(f"\n  ⚠️  {f['file']} — {f['concern']}")
        if f.get("visible"):
            print(f"      sees: {f['visible'][:160]}")
        if f.get("why"):
            print(f"      why : {f['why'][:160]}")
    if not rec["flagged"]:
        if rec["stage2"].startswith(("not run", "could not run")):
            # Filenames alone are a weak signal and this is where saying so
            # matters: a hackathon folder of team1_IMG_3582.mov trips nothing,
            # and it is wall-to-wall session footage.
            print("\n  nothing in the FILENAMES — but that is the weak signal, "
                  "and\n  stage 2 did not run. Re-run without --no-deep to have "
                  "a model look\n  at a frame from each clip.")
        else:
            print("\n  nothing to ask about.")
        return 0
    print("\n  ASK BEFORE CUTTING — then record the answer in decisions.json:")
    print('    "clearance": {"value": "public" | "internal" | "mixed",')
    print('                  "why": "who cleared it, and when",')
    print('                  "excluded": ["FILE.MOV", ...]}')
    print("  gate_clearance then verifies no excluded source reached the cut.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("footage_dir")
    ap.add_argument("--work-dir", help="where clearance_scan.json is written")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-deep", action="store_true",
                    help="stages 1-2 only; never calls a model")
    a = ap.parse_args()
    rec = scan(a.footage_dir, a.work_dir, deep=not a.no_deep)
    if a.json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    return report(rec)


if __name__ == "__main__":
    sys.exit(main())
