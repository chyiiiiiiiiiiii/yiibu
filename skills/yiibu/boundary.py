#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does any cut in the timeline split a sound somebody is in the middle of?

Why this exists, 2026-10-25, a sport reel. The hook shot was shortened to one
beat (0.94s) and its out-point landed at 24.93s — inside a bystander's shout
the shout, which the speech band puts at 24.80-25.20. The next shot two seconds
later cut a mumbled line that ran 1.1-3.3s at 2.20s. Every gate was green:
`asr_scan.json` had both clips as silent, because a full-clip decode reads a
short shout or a mumble under room noise at no_speech_prob 0.56-1.0. The user
heard both on the first watch — 「現在會感覺要聽到內容但是就被切換了」.

So this does not ask Whisper whether anybody is talking. It measures what a
listener hears at the cut itself: speech-band energy (house boundary.band_hz)
on BOTH sides of the cut point, in the source, against that stretch's own
noise floor. A sound that is still going on as the cut arrives — or was already
going on when the shot opens — is loud on both sides; a cut in a gap is quiet
on at least one. That is cheap, deterministic, and needs nothing but ffmpeg
and numpy, which is why `gate_boundary` can run it on every build.

What it cannot do is tell a voice from a dumbbell hitting the floor. On ten
finished projects about one flag in three was loud non-speech — a clank, a
cheer, wind. So a flagged cut has three ways out, and only one of them is a
sentence: move the cut so the line plays whole (or starts after it), set the
shot to MUTE in audio_policy.json, or write it off on the timeline segment as
`"split_ok": {"out": "why"}`. `--asr` is the evidence for that sentence: it
runs Whisper around each flagged cut and prints the words it hears there.

    python3 boundary.py WORK_DIR            # every audible cut, flagged ones marked
    python3 boundary.py WORK_DIR --asr      # + what Whisper hears across each flag
    python3 boundary.py WORK_DIR --json
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)

SR = 16000
FRAME_S = 0.05
DEFAULTS = {"band_hz": [200, 3500], "window_s": 0.15, "floor_pct": 10,
            "floor_window_s": 5.0, "min_straddle_db": 6.0}

_PCM = {}


def config(work_dir=None):
    from gates import house
    return {**DEFAULTS, **house(work_dir).get("boundary", {})}


def _band(path, band):
    """The speech band of a whole source file, mono 16 kHz, decoded once."""
    import numpy as np
    key = (os.path.abspath(path), tuple(band))
    if key not in _PCM:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-vn",
             "-af", f"highpass=f={band[0]},lowpass=f={band[1]}",
             "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
            stdin=subprocess.DEVNULL, capture_output=True).stdout
        _PCM[key] = np.frombuffer(raw, dtype=np.float32)
    return _PCM[key]


def _frames_db(x):
    import numpy as np
    h = int(SR * FRAME_S)
    n = len(x) // h
    if n == 0:
        return np.array([])
    rms = np.sqrt((x[:n * h].reshape(n, h).astype(np.float64) ** 2).mean(1))
    return 20 * np.log10(rms + 1e-9)


def straddle(path, t, cfg):
    """(straddle_db, floor_db) at source time t.

    straddle_db is the QUIETER of the two sides — the mean speech-band level
    of the window_s before t and of the window_s after it — above the floor:
    the floor_pct percentile of the floor_window_s either side. A side that
    falls outside the file (an in-point at 0.0) has nothing to hear and
    returns None.
    """
    import numpy as np
    x = _band(path, cfg["band_hz"])
    i, w = int(round(t * SR)), int(round(cfg["window_s"] * SR))
    if i - w < 0 or i + w > len(x):
        return None, None
    before, after = _frames_db(x[i - w:i]), _frames_db(x[i:i + w])
    fw = int(round(cfg["floor_window_s"] * SR))
    around = _frames_db(x[max(0, i - fw):i + fw])
    floor = float(np.percentile(around, cfg["floor_pct"]))
    return float(min(before.mean(), after.mean()) - floor), floor


def resolve(f, work_dir, timeline=None):
    """A segment's source file as written — absolute, or relative to the work
    dir, its parent (the project folder), or timeline.json's `source_dir`."""
    if os.path.isabs(f):
        return f if os.path.exists(f) else None
    roots = [work_dir or ".", os.path.dirname(os.path.abspath(work_dir or "."))]
    if timeline and timeline.get("source_dir"):
        roots.insert(0, os.path.join(work_dir or ".", timeline["source_dir"]))
    for r in roots:
        p = os.path.join(r, f)
        if os.path.exists(p):
            return p
    return None


def _num(s, *keys):
    for k in keys:
        if isinstance(s.get(k), (int, float)):
            return float(s[k])
    return None


def cuts(work_dir):
    """Every boundary a listener can hear, measured.

    Returns (rows, problems, note). A row is one side of one kept segment:
    {id, side, file, t, straddle_db, floor_db, split, split_ok}. `problems`
    are segments that cannot be checked at all — no source in-point, a source
    file that is not there — which the gate reports as failures, because a
    boundary nobody could measure is the one that shipped.
    """
    p = os.path.join(work_dir or ".", "timeline.json")
    try:
        tl = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None, [], "no readable timeline.json"
    segs = tl.get("segments")
    if not isinstance(segs, list) or not segs:
        return None, [], "timeline.json has no segments"
    if tl.get("kind") == "postprod":
        return [], [], ("postprod: silence_cut places every cut in a measured "
                        "silence of one recording")
    cfg = config(work_dir)
    from gates import audio_policy
    pol = audio_policy(work_dir)
    keep = ({r.get("id"): r.get("keep") for r in pol.get("segments", [])}
            if pol else None)

    norm = []
    for s in segs:
        tin = _num(s, "in", "tin", "source_start")
        tout = _num(s, "out", "tout", "source_end")
        if tin is not None and tout is None:
            dur = _num(s, "dur")
            tout = tin + dur * float(s.get("speed") or 1) if dur else None
        norm.append((s, str(s.get("file") or s.get("path") or ""), tin, tout))

    rows, problems = [], []
    for k, (s, f, tin, tout) in enumerate(norm):
        sid = str(s.get("id") or f"#{k}")
        if keep is not None and sid in keep and not keep[sid]:
            continue                              # MUTE: nothing to hear
        if not f:
            continue                              # gate_timeline reports it
        if tin is None or tout is None:
            problems.append(f"{sid}: no source in/out point (\"in\", \"out\") — "
                            f"where it was cut cannot be checked")
            continue
        path = resolve(f, work_dir, tl)
        if not path:
            problems.append(f"{sid}: source {os.path.basename(f)} is not where "
                            f"timeline.json says — its cuts cannot be heard")
            continue
        ok = s.get("split_ok") if isinstance(s.get("split_ok"), dict) else {}
        for side, t in (("in", tin), ("out", tout)):
            # A join to the very next frame of the same file is not a cut.
            j = k - 1 if side == "in" else k + 1
            if 0 <= j < len(norm):
                _s2, f2, in2, out2 = norm[j]
                other = out2 if side == "in" else in2
                if f2 == f and other is not None and abs(other - t) < FRAME_S:
                    continue
            db, floor = straddle(path, t, cfg)
            if db is None:
                continue
            rows.append({"id": sid, "side": side, "file": os.path.basename(f),
                         "path": path, "t": round(t, 3),
                         "straddle_db": round(db, 1), "floor_db": round(floor, 1),
                         "split": db >= cfg["min_straddle_db"],
                         "split_ok": str(ok.get(side) or "").strip() or None})
    return rows, problems, None


def _asr_near(path, t, model, pad=1.5):
    """Words Whisper hears within pad of t, zh and en. Evidence, not a verdict:
    it stretches a window's first word back to the window start, which is why
    the envelope, not this, is what decides."""
    a = max(0.0, t - pad)
    wav = os.path.join(tempfile.gettempdir(), f"_bnd_{os.getpid()}.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}",
                    "-t", f"{2 * pad:.3f}", "-i", path, "-ac", "1",
                    "-ar", str(SR), wav], check=True)
    out = {}
    for lang in ("zh", "en"):
        segs, _ = model.transcribe(wav, language=lang, word_timestamps=True,
                                   vad_filter=False,
                                   condition_on_previous_text=False)
        out[lang] = [{"w": w.word.strip(), "start": round(a + w.start, 2),
                      "end": round(a + w.end, 2), "p": round(w.probability, 2),
                      "across": a + w.start < t < a + w.end}
                     for sg in segs for w in (sg.words or [])]
    os.remove(wav)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("work_dir")
    ap.add_argument("--asr", action="store_true",
                    help="run Whisper around each flagged cut (needs faster-whisper)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows, problems, note = cuts(a.work_dir)
    if rows is None:
        print(note)
        return 1
    cfg = config(a.work_dir)
    flagged = [r for r in rows if r["split"]]
    if a.asr and flagged:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            print("--asr: faster-whisper is not installed; envelope only")
        else:
            model = WhisperModel("large-v3", device="cpu", compute_type="int8")
            for r in flagged:
                r["asr"] = _asr_near(r["path"], r["t"], model)
    if a.json:
        print(json.dumps({"rows": rows, "problems": problems, "note": note,
                          "min_straddle_db": cfg["min_straddle_db"]},
                         ensure_ascii=False, indent=1))
        return 0
    if note:
        print(note)
    for p in problems:
        print(f"  !! {p}")
    for r in rows:
        mark = ("SPLIT" if r["split"] and not r["split_ok"]
                else "split_ok" if r["split"] else "")
        print(f"  {r['id']:<10} {r['side']:<3} {r['file']:<18} {r['t']:8.2f}s  "
              f"{r['straddle_db']:5.1f} dB  {mark}"
              + (f"  — {r['split_ok']}" if r["split_ok"] and r["split"] else ""))
        for lang, ws in (r.get("asr") or {}).items():
            near = [w for w in ws if abs((w["start"] + w["end"]) / 2 - r["t"]) < 1.0]
            print(f"      {lang}: " + (" ".join(
                f"{'[' if w['across'] else ''}{w['w']}@{w['start']:.2f}"
                f"{']' if w['across'] else ''}" for w in near) or "—"))
    print(f"\n{len(flagged)} of {len(rows)} audible cut(s) at or above "
          f"{cfg['min_straddle_db']} dB on both sides")
    return 0


if __name__ == "__main__":
    sys.exit(main())
