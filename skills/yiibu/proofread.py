#!/usr/bin/env python3
"""Proof-read an ASR transcript — as a COMMAND, not as an agent.

SKILL.md marks proof-reading REQUIRED before captions are written, and until
now the only way to do it was a Claude-Code sub-agent. That makes a required
step unavailable to every other driver (Codex, Antigravity, a plain script),
and a required step that half the world cannot run is not a standard, it is a
suggestion. Everything mechanical about proof-reading is here instead:

    python3 proofread.py WORK_DIR/words.json --media CLIP.mp4
    python3 proofread.py WORK_DIR/words.json --media CLIP.mp4 --json

Exit 1 when the transcript is unusable (prompt echo / decoder loop) or when
any suspect span disagrees with a re-run. The `transcript-proofer` agent is an
optional accelerator on top of this, not a dependency: it adds judgement about
DOMAIN nouns and cross-checks on-screen text, which no script can do.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [SKILL_DIR, os.path.join(SKILL_DIR, "modules")]

LOW_CONF = 0.60
# Whisper is confidently wrong on exactly these: domain nouns, product names,
# digits and units. They get re-run even when the probability looks fine.
RISKY = re.compile(r"[A-Za-z]{2,}|\d")


def _words(path):
    raw = json.load(open(path, encoding="utf-8"))
    out = []
    for w in raw:
        out.append({"text": w.get("text") or w.get("word") or "",
                    "start": float(w["start"]), "end": float(w["end"]),
                    "probability": float(w.get("probability",
                                               w.get("confidence", 1.0)))})
    return out


def spans(words, pad=0.35, gap=0.45):
    """Group suspect words into contiguous spans worth re-running."""
    flags = [w for w in words
             if w["probability"] < LOW_CONF or RISKY.search(w["text"])]
    out = []
    for w in flags:
        a, b = max(w["start"] - pad, 0.0), w["end"] + pad
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
            out[-1][2].append(w)
        else:
            out.append([a, b, [w]])
    return out


def _rerun(media, a, b, model_name):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    global _MODEL
    if "_MODEL" not in globals() or _MODEL is None:
        _MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}",
                    "-to", f"{b:.3f}", "-i", media, "-ac", "1", "-ar", "16000",
                    "-vn", wav], capture_output=True)
    try:
        segs, _ = _MODEL.transcribe(
            wav, language="zh", word_timestamps=True, beam_size=5,
            condition_on_previous_text=False, no_speech_threshold=0.6,
            compression_ratio_threshold=2.4)          # never an initial_prompt
        ws = [(x.word, round(x.probability, 2))
              for s in segs for x in (s.words or [])]
    finally:
        os.unlink(wav)
    return ws


def _norm(s):
    return re.sub(r"[\s，。、！？,.!?]", "", s or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("--media", help="source media, enables re-running spans")
    ap.add_argument("--model", default=None, help="ASR model for the re-run")
    ap.add_argument("--prompt", default=None,
                    help="the initial_prompt used, to detect it echoed back")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-spans", type=int, default=25)
    args = ap.parse_args()

    words = _words(args.words)
    from transcribe import asr_sanity                       # noqa: E402
    try:
        from config import WHISPER_INITIAL_PROMPT, WHISPER_MODEL
    except Exception:                                        # noqa: BLE001
        WHISPER_INITIAL_PROMPT, WHISPER_MODEL = "", "large-v3"
    prompt = args.prompt if args.prompt is not None else WHISPER_INITIAL_PROMPT
    model_name = args.model or WHISPER_MODEL

    report = {"words": len(words), "unusable": asr_sanity(words, prompt),
              "checked_spans": 0, "verdicts": [], "rerun": False}

    if report["unusable"]:
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=1))
        else:
            print(f"\n  ❌ TRANSCRIPT UNUSABLE — {report['unusable']}")
            print("     Do not caption from this. Re-run ASR without an "
                  "initial_prompt.\n")
        return 1

    sus = spans(words)[:args.max_spans]
    report["checked_spans"] = len(sus)
    disagreements = 0
    for a, b, ws in sus:
        heard = "".join(w["text"] for w in ws)
        entry = {"span": [round(a, 2), round(b, 2)], "heard": heard,
                 "min_probability": round(min(w["probability"] for w in ws), 2)}
        if args.media and os.path.exists(args.media):
            got = _rerun(args.media, a, b, model_name)
            if got is not None:
                report["rerun"] = True
                again = "".join(t for t, _ in got)
                entry["rerun_heard"] = again
                entry["rerun_probs"] = [pv for _, pv in got]
                same = _norm(heard) in _norm(again) or _norm(again) in _norm(heard)
                entry["verdict"] = "keep" if same else "uncertain"
                if not same:
                    disagreements += 1
            else:
                entry["verdict"] = "uncertain"
                entry["note"] = "faster-whisper unavailable — not re-run"
        else:
            entry["verdict"] = "uncertain"
            entry["note"] = "no --media given — not re-run"
        report["verdicts"].append(entry)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"\n  proof-read: {report['words']} words, "
              f"{report['checked_spans']} suspect span(s)"
              + ("" if report["rerun"] else "  (NOT re-run — pass --media)"))
        for v in report["verdicts"]:
            mark = "✅" if v["verdict"] == "keep" else "⚠️ "
            print(f"    {mark} [{v['span'][0]:6.2f}-{v['span'][1]:6.2f}] "
                  f"p{v['min_probability']:.2f}  {v['heard'][:34]}")
            if v.get("rerun_heard") and v["verdict"] != "keep":
                print(f"        re-run heard: {v['rerun_heard'][:34]}")
            if v.get("note"):
                print(f"        {v['note']}")
        if disagreements:
            print(f"\n  ⚠️  {disagreements} span(s) disagree with the re-run — "
                  f"decide each one before writing captions.")
        print("\n  A caption that QUOTES speech must match the audio under it. "
              "Anything\n  you cannot confirm belongs in an authored style "
              "(Note), not a verbatim one.\n")
    return 1 if disagreements else 0


if __name__ == "__main__":
    sys.exit(main())
