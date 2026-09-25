"""Silence removal and clap-based mistake detection."""
import subprocess
import sys
import json
import os
import wave
import struct
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Optional

from config import (
    SILENCE_THRESHOLD, SILENCE_MIN_DURATION,
    CLAP_DB_THRESHOLD, WORK_DIR_PREFIX,
    SILENCE_CUT_CROSSFADE_MS,
)
from modules.compose import _get_video_codec_args


def _probe_duration(video: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def _probe_fps(video: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", video],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    num, _, den = out.partition("/")
    den = den or "1"
    return float(num) / float(den)


def find_clap_markers(
    rms_values: List[float],
    threshold: float = 0.7,
    frame_ms: int = 10,
) -> List[float]:
    """Find clap markers (volume spikes) in RMS data.

    Returns list of timestamps (seconds) where claps are detected.
    """
    markers = []
    i = 0
    while i < len(rms_values):
        if rms_values[i] >= threshold:
            # Found spike -- record timestamp
            markers.append(i * frame_ms / 1000.0)
            # Skip forward past the spike (claps last ~50-100ms)
            i += int(100 / frame_ms)
        else:
            i += 1
    return markers


def extract_rms_values(audio_path: str, frame_ms: int = 10) -> List[float]:
    """Extract per-frame RMS values from a WAV file (mono, 16-bit)."""
    with wave.open(audio_path, 'r') as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Convert to samples
    fmt = f"<{n_frames * n_channels}h"
    samples = list(struct.unpack(fmt, raw))

    # Mono-ize if stereo
    if n_channels == 2:
        samples = [(samples[i] + samples[i + 1]) / 2 for i in range(0, len(samples), 2)]

    # Calculate RMS per frame
    frame_size = int(framerate * frame_ms / 1000)
    rms_values = []
    max_val = 32768.0
    for start in range(0, len(samples), frame_size):
        chunk = samples[start:start + frame_size]
        if len(chunk) == 0:
            break
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) / max_val
        rms_values.append(rms)
    return rms_values


def remove_clap_segments(
    input_video: str,
    output_video: str,
    clap_times: List[float],
    lookback: float = 3.0,
) -> str:
    """Remove segments between each clap marker and `lookback` seconds before it.

    Uses FFmpeg select filter to keep only non-clap segments.
    Returns path to output video.
    """
    if not clap_times:
        # No claps -- just copy
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_video, "-c", "copy", output_video],
            check=True, capture_output=True,
        )
        return output_video

    # Clap zones (mistake segments) → invert to keep-ranges → render with
    # faded edges so the splices don't pop (was a hard `aselect`).
    total = _probe_duration(input_video)
    clap_zones = [(max(0.0, t - lookback), t + 0.2) for t in clap_times]
    keep_ranges = invert_ranges(clap_zones, total)
    render_faded_cut(input_video, keep_ranges, output_video)
    return output_video


def invert_ranges(
    cut_ranges: List[Tuple[float, float]],
    total_duration: float,
) -> List[Tuple[float, float]]:
    """Return the keep-ranges = complement of `cut_ranges` within [0, total].

    Overlapping/adjacent cut zones are merged first. Zero-length keeps
    (e.g. a cut that touches an edge) are dropped.
    """
    if not cut_ranges:
        return [(0.0, total_duration)]

    merged: List[Tuple[float, float]] = []
    for s, e in sorted(cut_ranges):
        s = max(0.0, s)
        e = min(total_duration, e)
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    keeps: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in merged:
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < total_duration:
        keeps.append((cursor, total_duration))
    return keeps


def keep_ranges_to_boundaries(
    keep_ranges: List[Tuple[float, float]],
) -> List[float]:
    """Positions (seconds, OUTPUT timeline) of the interior joins produced by
    concatenating `keep_ranges` = cumulative kept durations, excluding the
    final trailing edge. These are exactly the points render_faded_cut fades.
    """
    boundaries: List[float] = []
    if not keep_ranges:          # uncut pass-through (e.g. no auto-editor)
        return boundaries
    cursor = 0.0
    for start, end in keep_ranges[:-1]:
        cursor += end - start
        boundaries.append(round(cursor, 3))
    return boundaries


def _compose_keep_ranges(
    source_ranges: List[Tuple[float, float]],
    keep_ranges: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    composed: List[Tuple[float, float]] = []
    for keep_start, keep_end in keep_ranges:
        cursor = 0.0
        for source_start, source_end in source_ranges:
            duration = source_end - source_start
            overlap_start = max(keep_start, cursor)
            overlap_end = min(keep_end, cursor + duration)
            if overlap_end > overlap_start:
                mapped_start = source_start + overlap_start - cursor
                mapped_end = source_start + overlap_end - cursor
                if composed and abs(mapped_start - composed[-1][1]) < 1e-6:
                    composed[-1] = (composed[-1][0], mapped_end)
                else:
                    composed.append((mapped_start, mapped_end))
            cursor += duration
    return composed


def _write_json_atomic(path: str, value: dict) -> None:
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(
        "w", dir=directory, prefix=f".{os.path.basename(path)}.", delete=False,
    ) as fh:
        json.dump(value, fh)
        temp_path = fh.name
    try:
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _back_up_existing(path: str) -> None:
    if not os.path.exists(path):
        return
    stem, extension = os.path.splitext(path)
    backup = f"{stem}.previous{extension}"
    index = 1
    while os.path.exists(backup):
        backup = f"{stem}.previous-{index:03d}{extension}"
        index += 1
    os.replace(path, backup)


def _timeline_for_ranges(
    input_video: str,
    source_ranges: List[Tuple[float, float]],
) -> dict:
    segments = []
    cursor = 0.0
    source_file = os.path.abspath(input_video)
    for index, (source_start, source_end) in enumerate(source_ranges):
        duration = round(source_end - source_start, 6)
        segments.append({
            "id": f"take-{index:03d}",
            "file": source_file,
            "start": round(cursor, 6),
            "dur": duration,
            "source_start": round(source_start, 6),
            "source_end": round(source_end, 6),
        })
        cursor += duration
    return {"kind": "postprod", "total": round(cursor, 6), "segments": segments}


# auto-editor marks removed chunks with this sentinel "speed" in v1 export.
_AUTO_EDITOR_CUT_SPEED = 99999.0


def chunks_to_keep_ranges(
    chunks: List[list],
    fps: float,
) -> List[Tuple[float, float]]:
    """Convert auto-editor v1 `chunks` (`[start_frame, end_frame, speed]`)
    into kept (start_s, end_s) ranges. A chunk is kept when its speed is
    finite/normal (not the 99999 cut sentinel)."""
    keeps: List[Tuple[float, float]] = []
    for start_f, end_f, speed in chunks:
        if speed >= _AUTO_EDITOR_CUT_SPEED or speed <= 0:
            continue
        keeps.append((start_f / fps, end_f / fps))
    return keeps


def render_faded_cut(
    input_video: str,
    keep_ranges: List[Tuple[float, float]],
    output_video: str,
    fade_ms: Optional[int] = None,
) -> str:
    """Render `keep_ranges` of `input_video` into `output_video`, applying a
    short audio fade in/out at every segment edge so splices don't pop.

    Each kept range is extracted and re-encoded with `afade` on both edges,
    then the segments are losslessly concatenated (`-c copy`). This is the
    only way to smooth *interior* cut boundaries — a single whole-file
    `afade=t=in` (the old approach) never touches them.

    `keep_ranges` are (start_s, end_s) on the INPUT timeline. `fade_ms`
    defaults to SILENCE_CUT_CROSSFADE_MS.
    """
    if fade_ms is None:
        fade_ms = SILENCE_CUT_CROSSFADE_MS
    fade_s = fade_ms / 1000.0

    work = os.path.dirname(os.path.abspath(output_video))

    # One job per kept range. PCM audio (not AAC) so the concat is sample-exact
    # — AAC segments each carry encoder priming/padding that accumulates ~1ms of
    # A/V drift per segment under `-c copy`. .mkv holds h264 + PCM.
    jobs: List[Tuple[str, float, float]] = []
    for i, (start, end) in enumerate(keep_ranges):
        dur = end - start
        if dur <= 0:
            continue
        seg = os.path.join(work, f"_fadeseg_{i:04d}.mkv")
        jobs.append((seg, start, dur))

    if not jobs:
        raise ValueError("render_faded_cut: no non-empty keep_ranges")

    def _encode(job: Tuple[str, float, float]) -> None:
        seg, start, dur = job
        # Clamp fade so the two fades can't exceed the segment length.
        f = min(fade_s, dur / 2.0)
        afade = (
            f"afade=t=in:st=0:d={f:.3f},"
            f"afade=t=out:st={max(0.0, dur - f):.3f}:d={f:.3f}"
        )
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}", "-i", input_video, "-t", f"{dur:.3f}",
                "-af", afade,
            ] + _get_video_codec_args() + [
                "-c:a", "pcm_s16le",
                seg,
            ],
            check=True, capture_output=True,
        )

    # Segments are independent — encode in parallel (ffmpeg releases the GIL).
    # Order comes from `jobs` (enumerate order), never completion order.
    workers = min(len(jobs), max(2, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(_encode, jobs):
            pass

    seg_paths: List[str] = [job[0] for job in jobs]

    list_file = os.path.join(work, "_fadeconcat.txt")
    with open(list_file, "w") as fh:
        for p in seg_paths:
            fh.write(f"file '{p}'\n")
    # Video copied through losslessly; the continuous PCM audio is encoded to
    # AAC exactly once here → a single priming at t=0, no per-segment drift.
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:v", "copy", "-c:a", "aac", output_video,
        ],
        check=True, capture_output=True,
    )

    for p in seg_paths:
        os.remove(p)
    os.remove(list_file)
    return output_video


def run_silence_cut(
    input_video: str,
    work_dir: str,
    manual_cuts: Optional[List[Tuple[float, float]]] = None,
) -> str:
    """Full clap removal + silence removal pipeline.

    1. Convert to clean MP4
    2. Detect claps in original audio
    3. Remove clap-marked mistake segments (faded splices)
    4. auto-editor detects silence; render kept ranges with faded boundaries
    5. Apply manual cuts if provided (faded splices)

    Clap detection runs before silence removal. Each later stage is mapped
    through the ranges retained by the earlier stages so persisted timestamps
    continue to refer to the original input. Every cut boundary is smoothed by
    render_faded_cut (per-segment afade in/out).

    Returns path to trimmed video.
    """
    os.makedirs(work_dir, exist_ok=True)
    _back_up_existing(os.path.join(work_dir, "timeline.json"))
    clean_input = os.path.join(work_dir, "input_clean.mp4")
    clap_cleaned = os.path.join(work_dir, "clap_cleaned.mp4")
    trimmed = os.path.join(work_dir, "trimmed.mp4")
    audio_wav = os.path.join(work_dir, "audio_raw.wav")

    # Step 0: Convert to clean MP4 (strips iPhone metadata tracks that break auto-editor)
    print("  Converting to clean MP4...")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_video,
            "-map", "0:v:0", "-map", "0:a:0",
            "-c:v", "copy", "-c:a", "copy",
            clean_input,
        ],
        check=True, capture_output=True,
    )
    source_ranges = [(0.0, _probe_duration(clean_input))]

    # Step 1: Extract audio for clap detection (from original)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", clean_input,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_wav,
        ],
        check=True, capture_output=True,
    )

    # Step 2: Detect claps in ORIGINAL audio (before any editing)
    rms = extract_rms_values(audio_wav, frame_ms=10)
    clap_times = find_clap_markers(rms, threshold=0.7)

    if clap_times:
        print(f"  Detected {len(clap_times)} clap marker(s): "
              f"{[f'{t:.1f}s' for t in clap_times]}")
        print(f"  Removing {len(clap_times)} mistake segment(s) "
              f"(3s before each clap)...")
        remove_clap_segments(clean_input, clap_cleaned, clap_times)
        clap_zones = [(max(0.0, t - 3.0), t + 0.2) for t in clap_times]
        source_ranges = _compose_keep_ranges(
            source_ranges,
            invert_ranges(clap_zones, source_ranges[0][1]),
        )
    else:
        print("  No clap markers detected")
        clap_cleaned = clean_input

    # Step 3: auto-editor DETECTS silence (v1 export = kept/cut chunks, no
    # render). We render the kept ranges ourselves via render_faded_cut so
    # every silence boundary gets a fade — auto-editor's own render hard-cuts
    # them, and the old whole-file `afade=t=in` never touched interior joins.
    chunks_json = os.path.join(work_dir, "ae_chunks.json")
    import importlib.util
    if importlib.util.find_spec("auto_editor") is None:
        # Silence trimming is a feature, not a prerequisite: without
        # auto-editor the take passes through uncut instead of crashing step 1.
        print("  auto-editor not installed — skipping silence removal "
              "(pip install auto-editor to enable).")
        import shutil
        shutil.copyfile(clap_cleaned, trimmed)
    else:
        subprocess.run(
            [
                sys.executable, "-m", "auto_editor", clap_cleaned,
                "--margin", "0.2s",
                "--export", "v1",
                "--output", chunks_json,
            ],
            check=True,
        )
        with open(chunks_json) as fh:
            chunks = json.load(fh)["chunks"]
        keep_ranges = chunks_to_keep_ranges(chunks, _probe_fps(clap_cleaned))
        render_faded_cut(clap_cleaned, keep_ranges, trimmed)
        source_ranges = _compose_keep_ranges(source_ranges, keep_ranges)

    # Step 4: Manual cuts (if provided) — invert to keep-ranges, faded render.
    if manual_cuts:
        manual_out = os.path.join(work_dir, "manual_cut.mp4")
        keep_ranges = invert_ranges(list(manual_cuts), _probe_duration(trimmed))
        render_faded_cut(trimmed, keep_ranges, manual_out)
        os.rename(manual_out, trimmed)
        source_ranges = _compose_keep_ranges(source_ranges, keep_ranges)

    # Persist every final discontinuity on the output timeline so verify.py can
    # confirm each was faded (no un-faded pop).
    boundaries = keep_ranges_to_boundaries(source_ranges)
    _write_json_atomic(
        os.path.join(work_dir, "boundaries.json"), {"boundaries": boundaries},
    )
    _write_json_atomic(
        os.path.join(work_dir, "timeline.json"),
        _timeline_for_ranges(input_video, source_ranges),
    )

    # NOTE: the old "Step 5 micro-crossfade" (a single whole-file
    # `afade=t=in`) was a no-op for interior boundaries and has been removed.
    # Boundary fades now happen per-segment inside render_faded_cut.

    return trimmed
