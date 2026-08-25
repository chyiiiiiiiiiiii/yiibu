#!/usr/bin/env python3
"""Video post-production quality verification.

Runs all quality checks locally (zero API cost) and outputs a structured report.

Usage:
    python3 verify.py WORK_DIR [--output VIDEO_PATH] [--fix]

Options:
    --output PATH   Final video path (auto-detected from work_dir if omitted)
    --fix           Auto-fix lip-sync issues in subtitles.ass
    --json          Output results as JSON (for pipeline integration)
"""
import argparse
import json
import os
import re
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)

from config import (
    OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS,
    BROLL_COVERAGE_TARGET_MIN, BROLL_COVERAGE_TARGET_MAX,
    SUBTITLE_GAP,
)


# ── Helpers ──────────────────────────────────────────────────


def _find_ass(work_dir):
    """gates.py accepts either name; verify.py only ever looked for
    subtitles.ass, so a build that wrote captions.ass got two false
    "not found" warnings while the blocking gates were perfectly happy."""
    for n in ("subtitles.ass", "captions.ass"):
        p = os.path.join(work_dir, n)
        if os.path.exists(p):
            return p
    return os.path.join(work_dir, "subtitles.ass")

def ffprobe_json(path: str, entries: str) -> dict:
    """Run ffprobe and return parsed JSON."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_entries", entries, path],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout) if r.returncode == 0 else {}


def parse_ass_time(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def load_words_json(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ass_events(path: str) -> list:
    """Parse ASS dialogue events, skipping title/counter styles."""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            style = parts[3].strip()
            if style in ("Title", "TitleSub", "Counter"):
                continue
            text_raw = parts[9].strip()
            clean = re.sub(r'\{[^}]*\}', '', text_raw).strip()
            if not clean:
                continue
            events.append({
                "start": parse_ass_time(parts[1].strip()),
                "end": parse_ass_time(parts[2].strip()),
                "text": clean,
                "style": style,
            })
    return events


# ── Check: Format ────────────────────────────────────────────

def check_format(video_path: str) -> dict:
    """Verify video format: resolution, fps, codec, duration, size."""
    info = ffprobe_json(video_path, "stream=width,height,r_frame_rate,codec_name,codec_type:format=duration,size")
    streams = info.get("streams", [])
    fmt = info.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    w = video_stream.get("width", 0)
    h = video_stream.get("height", 0)
    codec = video_stream.get("codec_name", "unknown")
    fps_str = video_stream.get("r_frame_rate", "0/1")
    num, den = fps_str.split("/") if "/" in fps_str else (fps_str, "1")
    fps = float(num) / float(den) if float(den) else 0
    duration = float(fmt.get("duration", 0))
    size_mb = int(fmt.get("size", 0)) / (1024 * 1024)

    issues = []
    if w != OUTPUT_WIDTH or h != OUTPUT_HEIGHT:
        issues.append(f"Resolution {w}x{h} != expected {OUTPUT_WIDTH}x{OUTPUT_HEIGHT}")
    if codec != "h264":
        issues.append(f"Codec {codec} != expected h264")
    if abs(fps - OUTPUT_FPS) > 1.0:
        issues.append(f"FPS {fps:.2f} != expected {OUTPUT_FPS}")
    if not audio_stream:
        issues.append("No audio stream found")

    return {
        "name": "Format",
        "pass": len(issues) == 0,
        "details": {
            "resolution": f"{w}x{h}",
            "fps": round(fps, 2),
            "codec": codec,
            "duration_s": round(duration, 1),
            "size_mb": round(size_mb, 1),
            "has_audio": bool(audio_stream),
        },
        "issues": issues,
    }


# ── Check: Audio ─────────────────────────────────────────────

def check_audio(work_dir: str) -> dict:
    """Check audio quality: clipping, peak levels, volume consistency."""
    issues = []
    details = {}

    # Prefer SFX-mixed audio, fall back to BGM, then voice_only
    for name in ("bgm_mixed_sfx.wav", "bgm_mixed.wav", "voice_only.wav"):
        wav_path = os.path.join(work_dir, name)
        if os.path.exists(wav_path):
            details["audio_file"] = name
            break
    else:
        return {"name": "Audio", "pass": False, "details": {}, "issues": ["No audio file found"]}

    try:
        # Use ffmpeg astats (handles WAVE_FORMAT_EXTENSIBLE from loudnorm)
        result = subprocess.run(
            ["ffmpeg", "-i", wav_path, "-af", "astats=metadata=1:reset=0",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        stderr = result.stderr
        import math

        # Parse overall stats
        for line in stderr.split("\n"):
            if "RMS level" in line and "Overall" not in line:
                try:
                    details["rms_db"] = round(float(line.strip().split()[-1]), 1)
                except (ValueError, IndexError):
                    pass
            if "Peak level" in line and "Overall" not in line:
                try:
                    details["peak_db"] = round(float(line.strip().split()[-1]), 1)
                except (ValueError, IndexError):
                    pass
            if "Number of samples" in line and "samples" not in details:
                try:
                    details["samples"] = int(line.strip().split()[-1])
                except (ValueError, IndexError):
                    pass

        # Volume consistency check: measure RMS at 4 evenly-spaced windows
        duration_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", wav_path],
            capture_output=True, text=True, timeout=10,
        )
        total_dur = float(duration_result.stdout.strip())
        rms_values = []
        check_points = [total_dur * f for f in [0.1, 0.35, 0.6, 0.85]]
        for t in check_points:
            r = subprocess.run(
                ["ffmpeg", "-ss", f"{t:.1f}", "-t", "3", "-i", wav_path,
                 "-af", "astats=metadata=1:reset=0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stderr.split("\n"):
                if "RMS level" in line and "Overall" not in line:
                    try:
                        rms_values.append(float(line.strip().split()[-1]))
                    except (ValueError, IndexError):
                        pass
                    break

        if len(rms_values) >= 2:
            rms_range = max(rms_values) - min(rms_values)
            details["volume_range_db"] = round(rms_range, 1)
            details["volume_points"] = [f"{v:.1f}dB" for v in rms_values]
            if rms_range > 6.0:
                issues.append(f"Volume inconsistency {rms_range:.1f}dB across sections (>6dB)")
            elif rms_range > 4.0:
                details["volume_note"] = f"Moderate variation {rms_range:.1f}dB (acceptable <6dB)"

        # Check peak/clipping from overall stats
        peak_db = details.get("peak_db", -99)
        if peak_db >= 0:
            details["clipping_note"] = "Peak at 0dB — check for clipping artifacts"

    except Exception as e:
        issues.append(f"Audio analysis failed: {e}")

    return {"name": "Audio", "pass": len(issues) == 0, "details": details, "issues": issues}


# ── Check: Lip-Sync ──────────────────────────────────────────

def check_lipsync(work_dir: str, do_fix: bool = False) -> dict:
    """Compare subtitle timing against word timestamps."""
    words_path = os.path.join(work_dir, "words.json")
    ass_path = _find_ass(work_dir)

    if not os.path.exists(words_path) or not os.path.exists(ass_path):
        return {"name": "Lip-Sync", "pass": False, "details": {}, "issues": ["Missing words.json or the .ass caption file"]}

    words = load_words_json(words_path)
    events = load_ass_events(ass_path)

    # Only VERBATIM styles claim to be speech. gates.gate_sync has always known
    # this; verify.py measured every caption, so a deck of authored Note lines —
    # which are meant to explain, not to quote — reported as "off-sync" and
    # trained the reader to ignore the whole section.
    verbatim = set()
    try:
        import gates as _g
        verbatim = set(_g.house(work_dir)["sync"]["verbatim_styles"])
    except Exception:                                          # noqa: BLE001
        verbatim = {"Speech"}

    # Match each subtitle to its first spoken word (skip events at t=0 — title overlays)
    matches = []
    for evt in events:
        if evt["start"] < 0.5:
            continue  # Title card overlays, not lip-sync
        if verbatim and evt.get("style") and evt["style"] not in verbatim:
            continue  # authored line, not a verbatim claim
        first_char = evt["text"][0]
        best = None
        for w in words:
            if abs(w["start"] - evt["start"]) > 5.0:
                continue
            if w["text"].startswith(first_char):
                if best is None or abs(w["start"] - evt["start"]) < abs(best["start"] - evt["start"]):
                    best = w
        if best:
            diff = abs(evt["start"] - best["start"])
            matches.append({"sub_start": evt["start"], "word_start": best["start"],
                            "diff_s": diff, "text": evt["text"]})

    total = len(matches)
    if total == 0:
        return {"name": "Lip-Sync", "pass": False, "details": {}, "issues": ["No matches found"]}

    within_100 = sum(1 for m in matches if m["diff_s"] <= 0.1)
    within_300 = sum(1 for m in matches if m["diff_s"] <= 0.3)
    over_300 = [m for m in matches if m["diff_s"] > 0.3]

    details = {
        "total_events": total,
        "within_100ms": within_100,
        "within_100ms_pct": round(100 * within_100 / total),
        "within_300ms_pct": round(100 * within_300 / total),
        "over_300ms_count": len(over_300),
    }

    if over_300:
        details["worst_offenders"] = [
            {"time": f"{m['sub_start']:.2f}s", "diff_ms": int(m["diff_s"] * 1000), "text": m["text"][:30]}
            for m in sorted(over_300, key=lambda x: -x["diff_s"])[:5]
        ]

    issues = []
    if len(over_300) > 2:
        issues.append(f"{len(over_300)} events >300ms off-sync")

    # Auto-fix if requested
    fixed_count = 0
    if do_fix and over_300:
        fixed_count = _fix_lipsync(ass_path, words, events, matches)
        if fixed_count:
            details["fixes_applied"] = fixed_count
            # Re-verify after fix
            events_post = load_ass_events(ass_path)
            post_matches = []
            for evt in events_post:
                first_char = evt["text"][0]
                best = None
                for w in words:
                    if abs(w["start"] - evt["start"]) > 5.0:
                        continue
                    if w["text"].startswith(first_char):
                        if best is None or abs(w["start"] - evt["start"]) < abs(best["start"] - evt["start"]):
                            best = w
                if best:
                    post_matches.append(abs(evt["start"] - best["start"]))
            post_100 = sum(1 for d in post_matches if d <= 0.1)
            details["post_fix_within_100ms_pct"] = round(100 * post_100 / len(post_matches)) if post_matches else 0
            issues = []  # Clear issues after fix

    return {"name": "Lip-Sync", "pass": len(issues) == 0, "details": details, "issues": issues}


def _fix_lipsync(ass_path: str, words: list, events: list, matches: list) -> int:
    """Fix subtitle timing by aligning to word timestamps. Returns fix count."""
    GAP = SUBTITLE_GAP

    with open(ass_path, "r") as f:
        lines = f.readlines()

    # Build index: map event text+start to line index
    dialogue_info = []
    for i, line in enumerate(lines):
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        style = parts[3].strip()
        if style in ("Title", "TitleSub", "Counter"):
            continue
        text_raw = parts[9].strip() if len(parts) > 9 else ""
        clean = re.sub(r'\{[^}]*\}', '', text_raw).strip()
        if not clean:
            continue
        start = parse_ass_time(parts[1].strip())
        end = parse_ass_time(parts[2].strip())
        dialogue_info.append({"line_idx": i, "start": start, "end": end, "text": clean})

    # Find best word match per event
    fixes = 0
    for j, evt in enumerate(dialogue_info):
        first_char = evt["text"][0]
        best = None
        for w in words:
            if abs(w["start"] - evt["start"]) > 5.0:
                continue
            if w["text"].startswith(first_char):
                if best is None or abs(w["start"] - evt["start"]) < abs(best["start"] - evt["start"]):
                    best = w
        if not best:
            continue

        diff = evt["start"] - best["start"]
        if diff <= 0.3:
            continue

        new_start = best["start"]

        # Don't overlap with previous subtitle
        if j > 0:
            prev = dialogue_info[j - 1]
            if prev["end"] > new_start - GAP:
                # Shorten previous subtitle
                new_prev_end = new_start - GAP
                parts = lines[prev["line_idx"]].split(",", 9)
                parts[2] = format_ass_time(new_prev_end)
                lines[prev["line_idx"]] = ",".join(parts)
                prev["end"] = new_prev_end
                fixes += 1

        # Fix this subtitle's start
        parts = lines[evt["line_idx"]].split(",", 9)
        parts[1] = format_ass_time(new_start)
        lines[evt["line_idx"]] = ",".join(parts)
        evt["start"] = new_start
        fixes += 1

    if fixes:
        with open(ass_path, "w") as f:
            f.writelines(lines)

    return fixes


# ── Check: Subtitles ─────────────────────────────────────────

def check_subtitles(work_dir: str) -> dict:
    """Check subtitle quality: split numbers, long phrases, keyword highlights."""
    words_path = os.path.join(work_dir, "words.json")
    ass_path = _find_ass(work_dir)
    issues = []
    details = {}

    if not os.path.exists(ass_path):
        return {"name": "Subtitles", "pass": False, "details": {}, "issues": ["no .ass caption file (looked for subtitles.ass and captions.ass)"]}

    events = load_ass_events(ass_path)
    details["total_events"] = len(events)

    # Check split numbers in words.json
    if os.path.exists(words_path):
        words = load_words_json(words_path)
        split_numbers = []
        for i in range(len(words) - 1):
            if words[i]["text"].isdigit() and words[i + 1]["text"].isdigit():
                gap = words[i + 1]["start"] - words[i]["end"]
                if gap < 0.3:
                    split_numbers.append(f"{words[i]['text']}+{words[i+1]['text']} @{words[i]['start']:.1f}s")
        details["split_numbers"] = len(split_numbers)
        if split_numbers:
            issues.append(f"Split numbers: {', '.join(split_numbers[:3])}")

    # Check long phrases (>12 chars can be hard to read)
    long_phrases = [e for e in events if len(e["text"]) > 14]
    details["long_phrases"] = len(long_phrases)
    if len(long_phrases) > 15:
        issues.append(f"{len(long_phrases)} phrases >14 chars (readability concern)")

    # Check for keyword highlights (gold color in ASS)
    with open(ass_path, "r", encoding="utf-8") as f:
        ass_raw = f.read()
    # Keywords use \1c&H0000D7FF (gold color) + \fscx scale for emphasis
    kfx_count = len(re.findall(r'\\1c&H0000D7FF', ass_raw))
    keyword_scale_count = ass_raw.count("\\fscx")
    details["keyword_highlights"] = kfx_count
    if kfx_count == 0:
        issues.append("No keyword highlights found (expected \\1c&H0000D7FF gold markers)")

    # Check for overlapping events
    overlaps = 0
    sorted_events = sorted(events, key=lambda e: e["start"])
    for i in range(len(sorted_events) - 1):
        if sorted_events[i]["end"] > sorted_events[i + 1]["start"] + 0.01:
            overlaps += 1
    details["overlapping_events"] = overlaps
    # Was `> 3`. The correct number of captions rendering on top of each other
    # is zero, and a threshold of three meant this check MEASURED the 2026-08-21
    # collision correctly — overlapping_events: 1 — and then said nothing about
    # it. A tolerance on a defect that has no acceptable amount is a way of not
    # looking. gate_captions blocks on it now; this agrees rather than
    # disagreeing quietly.
    if overlaps:
        issues.append(f"{overlaps} overlapping subtitle event(s) — two captions "
                      f"on screen at once in the same place")

    return {"name": "Subtitles", "pass": len(issues) == 0, "details": details, "issues": issues}


# ── Check: B-roll ────────────────────────────────────────────

def check_broll(work_dir: str, video_duration: float = 0) -> dict:
    """Check B-roll: assets acquired, coverage, overlaps."""
    plan_path = os.path.join(work_dir, "broll_plan.json")
    issues = []
    details = {}

    if not os.path.exists(plan_path):
        return {"name": "B-roll", "pass": True, "details": {"note": "No B-roll plan"}, "issues": []}

    with open(plan_path, "r") as f:
        segments = json.load(f)

    total = len(segments)
    acquired = sum(1 for s in segments if s.get("asset_path") and os.path.exists(s.get("asset_path", "")))
    missing = [s.get("title", "?") for s in segments if not s.get("asset_path") or not os.path.exists(s.get("asset_path", ""))]

    details["total_segments"] = total
    details["acquired"] = acquired

    if missing:
        issues.append(f"Missing assets: {', '.join(missing[:3])}")

    # Coverage
    if video_duration > 0:
        broll_time = sum(s.get("duration", 0) for s in segments if s.get("asset_path"))
        coverage = broll_time / video_duration
        details["coverage_pct"] = round(100 * coverage)
        if coverage < BROLL_COVERAGE_TARGET_MIN:
            issues.append(f"Coverage {coverage:.0%} < target {BROLL_COVERAGE_TARGET_MIN:.0%}")

    # Overlap check
    sorted_segs = sorted(segments, key=lambda s: s.get("start_hint", 0))
    overlaps = 0
    for i in range(len(sorted_segs) - 1):
        end_i = sorted_segs[i].get("start_hint", 0) + sorted_segs[i].get("duration", 0)
        start_next = sorted_segs[i + 1].get("start_hint", 0)
        if end_i > start_next + 0.1:
            overlaps += 1
    details["overlaps"] = overlaps
    if overlaps:
        issues.append(f"{overlaps} overlapping B-roll segments")

    return {"name": "B-roll", "pass": len(issues) == 0, "details": details, "issues": issues}


# ── Check: Cut Boundaries ────────────────────────────────────

def check_cut_boundaries(work_dir: str) -> dict:
    """Verify every silence/manual cut boundary was faded (no audible pop).

    Reads `boundaries.json` (output-timeline join positions written by
    run_silence_cut) and the voice track (`trimmed.mp4`). At each boundary a
    real fade collapses the amplitude toward zero; a hard cut leaves it near
    the surrounding level. Boundaries sitting in silence carry no pop risk and
    are skipped.
    """
    b_path = os.path.join(work_dir, "boundaries.json")
    voice = os.path.join(work_dir, "trimmed.mp4")
    if not os.path.exists(b_path):
        return {"name": "Cut Boundaries", "pass": True,
                "details": {"note": "no boundaries.json"}, "issues": []}

    with open(b_path) as f:
        boundaries = json.load(f).get("boundaries", [])
    if not boundaries or not os.path.exists(voice):
        return {"name": "Cut Boundaries", "pass": True,
                "details": {"boundaries": len(boundaries)}, "issues": []}

    from modules.silence_cut import extract_rms_values
    wav = os.path.join(work_dir, "_boundary_probe.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", voice, "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", wav],
        check=True, capture_output=True,
    )
    rms = extract_rms_values(wav, frame_ms=10)  # 100 frames / sec
    os.remove(wav)

    def _median(xs):
        s = sorted(xs)
        return s[len(s) // 2] if s else 0.0

    unfaded = []
    for t in boundaries:
        idx = int(t * 100)
        if idx <= 5 or idx >= len(rms) - 5:
            continue
        center = min(rms[idx - 2:idx + 3])           # dip at the join
        neigh = rms[idx - 15:idx - 5] + rms[idx + 5:idx + 15]  # +/-50-150ms
        ref = _median(neigh)
        if ref < 0.01:
            continue  # silence-adjacent join — no pop possible
        if center > 0.4 * ref:                        # no clear fade dip
            unfaded.append(round(t, 2))

    issues = []
    if unfaded:
        issues.append(
            f"{len(unfaded)} un-faded cut boundaries (pop risk) @ "
            f"{unfaded[:5]}s"
        )
    return {
        "name": "Cut Boundaries",
        "pass": len(unfaded) == 0,
        "details": {"boundaries_checked": len(boundaries),
                    "unfaded": len(unfaded)},
        "issues": issues,
    }


# ── Check: Delivery ──────────────────────────────────────────

def check_delivery(video_path: str) -> dict:
    """Inspect the DELIVERED file — the one the viewer actually plays.

    Every check here exists because it shipped broken at least once. The rule
    they share: verify the decoded output, never the filter graph's output.
    An `ebur128` reading taken inside the filter chain said -1.0 dBFS on a file
    that decoded at +1.57 dBFS with 315 clipped samples.
    """
    issues = []
    details = {}

    # 1. Decoded peak. AAC reconstructs a heavily-limited waveform above the
    #    limiter ceiling (+3 dB overshoot measured), and that clips on playback.
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video_path, "-ac", "1", "-ar", "48000",
         "-f", "f32le", "-"],
        stdin=subprocess.DEVNULL, capture_output=True)
    peak = over = 0
    if r.stdout:
        import array
        a = array.array("f")
        a.frombytes(r.stdout[:len(r.stdout) // 4 * 4])
        peak = max((abs(x) for x in a), default=0.0)
        over = sum(1 for x in a if abs(x) > 1.0)
    details["decoded_peak"] = round(peak, 4)
    details["samples_over_full_scale"] = over
    if over:
        issues.append(f"Audio clips on playback: {over} samples over full scale "
                      f"(decoded peak {peak:.3f}). Compress before make-up gain, "
                      f"or lower the limiter ceiling, then re-check DECODED peak.")

    # 2. Video must start at PTS 0, or players show black where there is no
    #    picture yet (concat leaves video at +0.033s while audio starts at 0).
    info = ffprobe_json(video_path,
                        "stream=codec_type,start_pts,start_time,duration,nb_frames")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    aud = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    vstart = int(v.get("start_pts", 0) or 0)
    details["video_start_pts"] = vstart
    if vstart != 0:
        issues.append(f"Video starts at PTS {vstart} (audio at 0) — first frame "
                      f"renders black. Re-encode with -fps_mode cfr "
                      f"(NOT setpts=PTS-STARTPTS, which drops frames at concat "
                      f"boundaries).")

    # 3. Audio must cover the whole picture. loudnorm silently eats ~3s off the
    #    tail, leaving the closing card with no sound.
    vdur = float(v.get("duration", 0) or 0)
    adur = float(aud.get("duration", 0) or 0)
    details["video_dur"] = round(vdur, 3)
    details["audio_dur"] = round(adur, 3)
    if vdur and adur and adur < vdur - 0.15:
        issues.append(f"Audio ends {vdur - adur:.2f}s before the video "
                      f"(loudnorm lookahead drops the tail — measure loudness, "
                      f"then apply a constant gain instead).")

    # 4. Frame count must match the duration, or a whole section was dropped.
    nbf = int(v.get("nb_frames", 0) or 0)
    if nbf and vdur:
        expected = vdur * OUTPUT_FPS
        details["frames"] = nbf
        if abs(nbf - expected) > 3:
            issues.append(f"{nbf} frames but duration implies {expected:.0f} — "
                          f"a segment was dropped.")

    # 5. First and last frame must not be black (baked cover / closing card).
    for label, seek in (("first", ["-ss", "0"]), ("last", ["-sseof", "-0.5"])):
        p = subprocess.run(
            ["ffmpeg", "-v", "error", *seek, "-i", video_path, "-frames:v", "1",
             "-vf", "scale=64:64,format=gray", "-f", "rawvideo", "-"],
            stdin=subprocess.DEVNULL, capture_output=True)
        if p.stdout:
            mx = max(p.stdout)
            details[f"{label}_frame_max_luma"] = mx
            if mx < 16:
                issues.append(f"{label} frame is black.")

    return {"name": "Delivery", "pass": not issues, "details": details,
            "issues": issues}


# ── Check: Visual Frames ─────────────────────────────────────

def extract_frames(video_path: str, work_dir: str, count: int = 8) -> dict:
    """Extract evenly-spaced frames for manual visual review."""
    frames_dir = os.path.join(work_dir, "verify_frames")
    os.makedirs(frames_dir, exist_ok=True)

    info = ffprobe_json(video_path, "format=duration")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        return {"name": "Visual", "pass": False, "details": {}, "issues": ["Cannot get video duration"]}

    timestamps = [round(duration * i / (count + 1), 1) for i in range(1, count + 1)]
    extracted = []

    for ts in timestamps:
        out = os.path.join(frames_dir, f"frame_{int(ts)}s.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(ts), "-i", video_path,
             "-vframes", "1", "-q:v", "2", out],
            capture_output=True, timeout=10,
        )
        if os.path.exists(out):
            extracted.append(out)

    return {
        "name": "Visual",
        "pass": len(extracted) >= count - 1,
        "details": {
            "frames_extracted": len(extracted),
            "frames_dir": frames_dir,
            "timestamps": timestamps,
        },
        "issues": [] if len(extracted) >= count - 1 else [f"Only extracted {len(extracted)}/{count} frames"],
    }


# ── Main ─────────────────────────────────────────────────────

def find_output_video(work_dir: str) -> str:
    """Try to find the output video from the work directory's source."""
    trimmed = os.path.join(work_dir, "trimmed.mp4")
    if os.path.exists(trimmed):
        # Guess output path from trimmed video's original source
        # Convention: input_final.mp4
        pass
    return ""


def run_all_checks(work_dir: str, video_path: str = None, do_fix: bool = False) -> list:
    """Run all quality checks and return results."""
    results = []

    # Determine video duration
    duration = 0
    trimmed = os.path.join(work_dir, "trimmed.mp4")
    dur_source = video_path or trimmed
    if dur_source and os.path.exists(dur_source):
        info = ffprobe_json(dur_source, "format=duration")
        duration = float(info.get("format", {}).get("duration", 0))

    # 1. Format check (only if output video provided)
    if video_path and os.path.exists(video_path):
        results.append(check_format(video_path))

    # 2. Audio check
    results.append(check_audio(work_dir))

    # 3. Lip-sync check (with optional auto-fix)
    results.append(check_lipsync(work_dir, do_fix=do_fix))

    # 4. Subtitle quality check
    results.append(check_subtitles(work_dir))

    # 5. B-roll check
    results.append(check_broll(work_dir, duration))

    # 6. Cut-boundary fade check (audio pop at silence/manual cuts)
    results.append(check_cut_boundaries(work_dir))

    # 7. Delivery check on the final file (decoded, as the viewer hears/sees it)
    if video_path and os.path.exists(video_path):
        results.append(check_delivery(video_path))

    # 8. Extract frames for visual review
    if video_path and os.path.exists(video_path):
        results.append(extract_frames(video_path, work_dir))

    return results


def print_report(results: list):
    """Print human-readable quality report.

    This report used to end with "VERDICT: ✅ PUBLISH READY". It was the most
    dangerous line in the repo: verify.py is ADVISORY — it cannot fail a
    hand-over, it does not read house_style.json, and it runs eight checks
    against the nineteen in gates.py. An agent reading "PUBLISH READY" and
    handing the file over is not hallucinating; it is believing what it was
    told. A non-blocking checker is not entitled to a shipping verdict, so it
    no longer gives one and names the command that is.
    """
    all_pass = all(r["pass"] for r in results)
    total_issues = sum(len(r["issues"]) for r in results)

    print("\n" + "=" * 60)
    print("  VIDEO QUALITY REPORT")
    print("=" * 60)

    for r in results:
        status = "✅ PASS" if r["pass"] else "⚠️  WARN"
        print(f"\n  [{status}] {r['name']}")

        for key, val in r["details"].items():
            if isinstance(val, list) and len(val) > 5:
                print(f"    {key}: [{len(val)} items]")
            else:
                print(f"    {key}: {val}")

        for issue in r["issues"]:
            print(f"    ❗ {issue}")

    print(f"\n{'=' * 60}")
    verdict = ("✅ ADVISORY CHECKS CLEAN — NOT a shipping verdict" if all_pass
               else f"⚠️  {total_issues} ISSUE(S) FOUND")
    print(f"  VERDICT: {verdict}")
    print("  verify.py cannot pass or fail a hand-over. The blocking check is:")
    print("    python3 gates.py FINAL.mp4 --work-dir WORK_DIR")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Video quality verification")
    parser.add_argument("work_dir", help="Working directory with intermediate files")
    parser.add_argument("--output", help="Final output video path")
    parser.add_argument("--fix", action="store_true", help="Auto-fix lip-sync issues")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not os.path.isdir(args.work_dir):
        print(f"Error: {args.work_dir} is not a directory")
        sys.exit(1)

    results = run_all_checks(args.work_dir, args.output, do_fix=args.fix)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_report(results)

    # Exit code: 0 if all pass, 1 if issues found
    sys.exit(0 if all(r["pass"] for r in results) else 1)


if __name__ == "__main__":
    main()
