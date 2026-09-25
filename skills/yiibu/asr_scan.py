#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask EVERY clip in the folder whether anybody is talking in it, and write the
answer down where a gate can read it.

Why this exists, measured on 2026-08-29. A folder of 13 running clips was cut
twice — two full builds, both shipped, both with every gate green — and only the
long selfie recording had ever been through ASR. Two of the running clips turned
out to carry the split calls:

    IMG_4014_1k   「1K 4 分 28 秒 / 狀況不錯，繼續」
    IMG_4021_4k   「4K 4 分 43 秒」

They shipped as silent B-roll, twice, with hand-written distance pills invented
over the top of them. The user's question was the whole review: 「跑步的時候有
講話，為什麼那些都沒有字幕？辨識不出來嗎？」 It was not a recognition failure.
`SKILL.md` step 2 and the running template both say to transcribe each clip
separately; nobody did, and nothing looked.

Reading the result needs the guard this script bakes in. On outdoor clips with
no speech, large-v3 with the VAD off does not return nothing — it returns
YouTube end-plate boilerplate at an ordinary-looking `avg_logprob`:

    IMG_4015.MOV   '中文字幕志愿者 杨栋梁'    avg_logprob -0.51  no_speech_prob 0.71
    IMG_4016.mov   '谢谢观看 欢迎订阅我的频道' avg_logprob -0.50  no_speech_prob 0.84

`no_speech_prob` is the discriminator, not the logprob: on that folder ten
silent clips scored 0.59-0.84 while the two real ones produced per-word timings
that held across three decode temperatures. So this script records
`no_speech_prob` per clip and flags the known boilerplate outright.

    python3 asr_scan.py SOURCE_DIR --work-dir WORK_DIR
    python3 asr_scan.py SOURCE_DIR --work-dir WORK_DIR --skip IMG_0001.MOV

Writes `WORK_DIR/asr_scan.json`, which `gate_transcription` reads. It never
passes an `initial_prompt` — see AGENTS.md §4 for what that does to noisy audio.
"""
import argparse
import hashlib
import json
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import uuid

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

MEDIA = (".mov", ".mp4", ".m4v", ".mkv", ".avi", ".wav", ".m4a", ".mp3")

# Whisper's end-plate hallucinations. Not a blocklist for the transcript — a
# reason to look at no_speech_prob rather than at the words.
BOILERPLATE = re.compile(
    r"中文字幕|字幕志.?者|字幕由|感谢观看|谢谢观看|谢谢大家|请不吝|点赞|訂閱|订阅|"
    r"歡迎訂閱|欢迎订阅|明鏡與點點欄目|by index")

# A clip declared silent must ALSO look silent to the model. Provenance:
# measured 2026-08-29 on the 0826 大安夜跑 folder, the run that prompted this
# script — ten genuinely silent outdoor clips scored 0.59-0.84 and the two with
# speech produced word timings. 0.5 is a probability's own midpoint and sits
# below every silent clip measured, so it separates without being tuned to fit.
NO_SPEECH_FLOOR = 0.5
DEFAULT_CLIP_TIMEOUT = 900.0
CACHE_VERSION = 1

ASR_SETTINGS = {
    "language": "zh",
    "word_timestamps": True,
    "vad_filter": True,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "compression_ratio_threshold": 2.4,
}


def _venv_python():
    p = os.path.join(SKILL_DIR, ".venv", "bin", "python3")
    return p if os.path.exists(p) else sys.executable


def _max_volume_db(path, timeout=DEFAULT_CLIP_TIMEOUT):
    """Cheap pre-filter. A clip this quiet has no usable speech and large-v3
    can loop on it for minutes (SKILL.md, the folder-ASR budget)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                        "-af", "volumedetect", "-f", "null", os.devnull],
                       capture_output=True, text=True, timeout=timeout)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


_WORKER = r'''
import json, sys
from faster_whisper import WhisperModel
paths = json.load(open(sys.argv[1]))
model = WhisperModel(sys.argv[2], device="cpu", compute_type="int8")
for p in paths:
    rows = []
    # NO initial_prompt: on noisy audio Whisper returns the prompt itself as the
    # transcript at ordinary word probabilities (AGENTS.md §4).
    segs, _info = model.transcribe(
        p, language="zh", word_timestamps=True, vad_filter=True,
        condition_on_previous_text=False, no_speech_threshold=0.6,
        compression_ratio_threshold=2.4)
    for s in segs:
        rows.append({
            "start": round(s.start, 2), "end": round(s.end, 2),
            "text": s.text.strip(),
            "avg_logprob": round(s.avg_logprob, 3),
            "no_speech_prob": round(s.no_speech_prob, 3),
            "words": [{"text": w.word.strip(), "start": round(w.start, 2),
                       "end": round(w.end, 2),
                       "probability": round(w.probability, 2)}
                      for w in (s.words or [])],
        })
    print(json.dumps({"path": p, "rows": rows}, ensure_ascii=False), flush=True)
'''


def _atomic_json(path, value, indent=None):
    fd, tmp = tempfile.mkstemp(prefix=".asr-", suffix=".json",
                               dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _fingerprint(path, model, quiet_db):
    source = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            source.update(chunk)
    payload = {
        "version": CACHE_VERSION,
        "source_sha256": source.hexdigest(),
        "model": model,
        "settings": {**ASR_SETTINGS, "quiet_db": quiet_db},
    }
    packed = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode()).hexdigest()


def _cache_path(cache_dir, filename):
    key = hashlib.sha256(filename.encode()).hexdigest()
    return os.path.join(cache_dir, f"{key}.json")


def _valid_result(result):
    if not isinstance(result, dict):
        return False
    speech = result.get("speech")
    no_speech_prob = result.get("no_speech_prob")
    words = result.get("words")
    if (not isinstance(speech, bool) or
            isinstance(no_speech_prob, bool) or
            not isinstance(no_speech_prob, (int, float)) or
            not math.isfinite(no_speech_prob) or
            isinstance(words, bool) or not isinstance(words, int) or words < 0):
        return False
    if speech and not isinstance(result.get("segments"), list):
        return False
    if "captioned" in result and not isinstance(result["captioned"], bool):
        return False
    if "why" in result and not isinstance(result["why"], str):
        return False
    return True


def _cached_result(cache_dir, filename, fingerprint):
    path = _cache_path(cache_dir, filename)
    try:
        cached = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(cached, dict) or
            cached.get("version") != CACHE_VERSION or
            cached.get("file") != filename or
            cached.get("fingerprint") != fingerprint or
            not _valid_result(cached.get("result"))):
        return None
    return cached["result"]


def _save_cache(cache_dir, filename, fingerprint, result):
    _atomic_json(_cache_path(cache_dir, filename), {
        "version": CACHE_VERSION,
        "file": filename,
        "fingerprint": fingerprint,
        "result": result,
    })


def _matching_review(previous, result):
    if (not isinstance(previous, dict) or
            not isinstance(previous.get("captioned"), bool)):
        return None
    omitted = {"captioned", "why"}
    old_evidence = {k: v for k, v in previous.items() if k not in omitted}
    cached_evidence = {k: v for k, v in result.items() if k not in omitted}
    if old_evidence != cached_evidence:
        return None
    review = {"captioned": previous["captioned"]}
    if isinstance(previous.get("why"), str):
        review["why"] = previous["why"]
    return review


def _worker_results(paths, work_dir, model, timeout):
    fd, listp = tempfile.mkstemp(prefix="_asr_list-", suffix=".json",
                                 dir=work_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(paths, f)
    proc = None
    try:
        proc = subprocess.Popen(
            [_venv_python(), "-c", _WORKER, listp, model],
            stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        lines = queue.Queue()

        def read_stdout():
            try:
                for line in proc.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=read_stdout, daemon=True).start()
        seen = set()
        while len(seen) < len(paths):
            try:
                line = lines.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError(
                    f"ASR worker timed out after {timeout:g}s while loading "
                    "the model or scanning one clip")
            if line is None:
                break
            try:
                event = json.loads(line)
                path = event["path"]
                rows = event["rows"]
            except (ValueError, KeyError, TypeError) as e:
                raise RuntimeError(f"ASR worker returned invalid output: {e}")
            if path not in paths or path in seen or not isinstance(rows, list):
                raise RuntimeError("ASR worker returned an unexpected clip result")
            seen.add(path)
            yield path, rows
        returncode = proc.wait(timeout=timeout)
        if returncode:
            raise RuntimeError(f"ASR worker failed with exit code {returncode}")
        if len(seen) != len(paths):
            raise RuntimeError(
                f"ASR worker returned {len(seen)}/{len(paths)} clip results")
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"ASR worker did not exit within {timeout:g}s after returning "
            "its results")
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        if os.path.exists(listp):
            os.remove(listp)


def _result_from_rows(rows):
    words = [w for s in rows for w in s["words"]]
    nsp = min((s["no_speech_prob"] for s in rows), default=1.0)
    text = " ".join(s["text"] for s in rows)
    boiler = bool(BOILERPLATE.search(text))
    speech = bool(words) and not boiler and nsp < NO_SPEECH_FLOOR
    row = {"speech": speech, "no_speech_prob": nsp,
           "words": len(words) if speech else 0}
    if speech:
        row["segments"] = rows
    else:
        row["why"] = ("Whisper end-plate boilerplate — no one is talking"
                      if boiler else
                      f"no_speech_prob {nsp:.2f}, nothing usable")
        row["heard"] = text[:120]
    return row, words, text


def scan(src_dir, work_dir, model="large-v3", skip=(), quiet_db=-25.0,
         timeout=DEFAULT_CLIP_TIMEOUT):
    if not math.isfinite(timeout) or timeout <= 0:
        raise SystemExit("ASR timeout must be a finite number greater than zero")
    os.makedirs(work_dir, exist_ok=True)
    dst = os.path.join(work_dir, "asr_scan.json")
    previous = {}
    try:
        previous = json.load(open(dst, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if os.path.exists(dst):
        has_decisions = (
            isinstance(previous, dict) and
            any(isinstance(row, dict) and "captioned" in row
                for row in previous.values())
        )
        if has_decisions:
            backup = os.path.join(
                work_dir, f"asr_scan.previous-{uuid.uuid4().hex}.json",
            )
            os.replace(dst, backup)
            print(f"  Existing reviewed scan preserved at: {backup}")
        else:
            os.remove(dst)

    files = sorted(f for f in os.listdir(src_dir)
                   if f.lower().endswith(MEDIA) and f not in skip
                   and not f.startswith("."))
    if not files:
        raise SystemExit(f"no media in {src_dir}")

    cache_dir = os.path.join(work_dir, "_asr_scan_cache")
    os.makedirs(cache_dir, exist_ok=True)
    loud, out, fingerprints = [], {}, {}
    for f in files:
        source_path = os.path.join(src_dir, f)
        fingerprint = _fingerprint(source_path, model, quiet_db)
        fingerprints[f] = fingerprint
        cached = _cached_result(cache_dir, f, fingerprint)
        if cached is not None:
            old = previous.get(f) if isinstance(previous, dict) else None
            review = _matching_review(old, cached)
            if review is not None:
                cached = {**cached, **review}
                _save_cache(cache_dir, f, fingerprint, cached)
            out[f] = cached
            print(f"  {f:44s} cached")
            continue
        try:
            db = _max_volume_db(source_path, timeout)
        except subprocess.TimeoutExpired:
            raise SystemExit(
                f"ASR volume probe timed out after {timeout:g}s for {f}")
        if db is not None and db < quiet_db:
            out[f] = {"speech": False, "no_speech_prob": 1.0, "words": 0,
                      "why": f"max_volume {db:.1f} dB is below the {quiet_db} dB "
                             f"floor — no usable speech, not transcribed"}
            _save_cache(cache_dir, f, fingerprint, out[f])
            print(f"  {f:44s} skipped ({db:.1f} dB)")
        else:
            loud.append(f)

    if loud:
        paths = [os.path.join(src_dir, f) for f in loud]
        try:
            results = _worker_results(paths, work_dir, model, timeout)
            for path, rows in results:
                f = os.path.basename(path)
                row, words, text = _result_from_rows(rows)
                out[f] = row
                _save_cache(cache_dir, f, fingerprints[f], row)
                mark = "SPEECH" if row["speech"] else "  --  "
                print(f"  {f:44s} {mark}  nsp {row['no_speech_prob']:.2f}"
                      + (f"  {len(words)} words" if row["speech"]
                         else f"  ({text[:36]})"))
        except RuntimeError as e:
            raise SystemExit(f"{e} — is faster-whisper installed in .venv? "
                             "(python3 doctor.py)")

    _atomic_json(dst, out, indent=1)
    voiced = [f for f, r in out.items() if r["speech"]]
    print(f"\n  {len(out)} clip(s) scanned, {len(voiced)} with speech -> {dst}")
    if voiced:
        print("  Re-run any line you intend to caption ON ITS OWN before "
              "writing it:\n    a full-clip pass read 「1KM」 with M at p0.06; "
              "three isolated re-runs all said 「1K」.")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source_dir")
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--skip", action="append", default=[],
                    help="filename to leave out (repeatable)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_CLIP_TIMEOUT,
                    help="maximum seconds for model startup or one clip "
                         f"(default: {DEFAULT_CLIP_TIMEOUT:g})")
    ap.add_argument("--json", action="store_true", help="print the scan as JSON")
    a = ap.parse_args()
    out = scan(a.source_dir, a.work_dir, a.model, set(a.skip), timeout=a.timeout)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
