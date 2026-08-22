"""BGM module — background music with auto-ducking for speech clarity."""
import glob
import json
import os
import random
import subprocess
from dataclasses import dataclass, asdict
from typing import List, Optional

from config import (
    BGM_LIBRARY_DIR,
    BGM_VOLUME,
    VOICE_VOLUME,
    BGM_CROSSFADE,
    BGM_MOODS,
    BGM_DEFAULT_MOOD,
    BGM_DEFAULT_TRACK,
    BGM_DUCK_THRESHOLD,
    BGM_DUCK_RATIO,
    BGM_DUCK_ATTACK,
    BGM_DUCK_RELEASE,
    BGM_SYNTH_FREQUENCIES,
    BGM_SYNTH_PAD_DURATION,
    SFX_TRANSITION_VOLUME,
    SFX_TRANSITION_MIN_GAP,
    SFX_DUCK_GAIN,
    SFX_DUCK_WINDOW,
)


@dataclass
class BgmSegment:
    """A single BGM segment with mood, source path, and timing."""
    mood: str
    source_path: str
    start: float    # seconds into the timeline
    duration: float # seconds


def extract_speech_audio(trimmed_video: str, work_dir: str) -> str:
    """Extract WAV audio from the trimmed video for use as sidechain input."""
    output_path = os.path.join(work_dir, "speech.wav")
    # aresample=async=1:first_pts=0 preserves the FULL duration and timeline anchor.
    # Plain extraction drops AAC decoder priming (~260ms), which shifts speech out of
    # sync with the video/subtitles (progressively "late" toward the end).
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", trimmed_video,
            "-vn", "-af", "aresample=44100:async=1:first_pts=0",
            "-acodec", "pcm_s16le", "-ac", "1",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file in seconds."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def analyze_mood(transcript_text: str) -> List[str]:
    """Use Gemini CLI to classify transcript into mood tags.

    Returns a list of mood strings (e.g. ["chill", "inspiring"]).
    Falls back to [BGM_DEFAULT_MOOD] on any error.
    """
    if not transcript_text or not transcript_text.strip():
        return [BGM_DEFAULT_MOOD]

    prompt = (
        f"Classify the mood of this video transcript into one or more of these "
        f"categories: {', '.join(BGM_MOODS)}. "
        f"Return ONLY a JSON array of strings, e.g. [\"chill\", \"inspiring\"]. "
        f"No explanation.\n\n"
        f"Transcript:\n{transcript_text[:2000]}"
    )
    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return [BGM_DEFAULT_MOOD]

        # Extract JSON array from response
        output = result.stdout.strip()
        # Find the JSON array in the output
        start = output.find("[")
        end = output.rfind("]") + 1
        if start == -1 or end == 0:
            return [BGM_DEFAULT_MOOD]

        moods = json.loads(output[start:end])
        # Validate moods
        valid = [m for m in moods if m in BGM_MOODS]
        return valid if valid else [BGM_DEFAULT_MOOD]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return [BGM_DEFAULT_MOOD]


def select_music(mood: str) -> Optional[str]:
    """Pick a BGM track. Uses BGM_DEFAULT_TRACK if set, otherwise random from library.

    Returns the file path, or None if no library exists for this mood.
    """
    # Use default track if configured and exists
    if BGM_DEFAULT_TRACK and os.path.exists(BGM_DEFAULT_TRACK):
        return BGM_DEFAULT_TRACK

    mood_dir = os.path.join(BGM_LIBRARY_DIR, mood)
    if not os.path.isdir(mood_dir):
        return None

    tracks = glob.glob(os.path.join(mood_dir, "*.wav")) + \
             glob.glob(os.path.join(mood_dir, "*.mp3"))
    if not tracks:
        return None

    return random.choice(tracks)


def generate_synth_pad(mood: str, duration: float, work_dir: str) -> str:
    """Generate an ambient synth pad as BGM fallback using FFmpeg.

    Creates a rich ambient pad with:
    - Root chord across 2 octaves (low + mid)
    - Slightly detuned pairs for chorus/width effect
    - Slow tremolo (LFO) for movement
    - Warm lowpass filtering
    """
    freqs = BGM_SYNTH_FREQUENCIES.get(mood, BGM_SYNTH_FREQUENCIES[BGM_DEFAULT_MOOD])
    output_path = os.path.join(work_dir, f"synth_{mood}.wav")

    # Build a richer frequency set: sub octave + root + detuned pairs
    all_freqs = []
    for f in freqs:
        all_freqs.append(f * 0.5)       # sub octave
        all_freqs.append(f)             # root
        all_freqs.append(f * 1.003)     # slightly sharp (chorus effect)

    inputs = []
    filter_parts = []
    for i, freq in enumerate(all_freqs):
        inputs.extend([
            "-f", "lavfi", "-i",
            f"sine=frequency={freq:.2f}:duration={duration}:sample_rate=44100",
        ])
        # Higher volume per oscillator, sub octave slightly louder
        vol = 0.35 if freq < 200 else 0.25
        filter_parts.append(f"[{i}:a]volume={vol}[s{i}]")

    labels = "".join(f"[s{i}]" for i in range(len(all_freqs)))
    filter_parts.append(
        f"{labels}amix=inputs={len(all_freqs)}:normalize=0[raw]"
    )
    # Warm lowpass + slow tremolo + fade in/out
    fade_out_start = max(duration - 1, 0)
    filter_parts.append(
        f"[raw]lowpass=f=2000:p=2,"
        f"tremolo=f=0.3:d=0.4,"
        f"afade=t=in:d=1,"
        f"afade=t=out:st={fade_out_start}:d=1[out]"
    )

    filter_complex = ";\n".join(filter_parts)

    subprocess.run(
        ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "pcm_s16le",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def plan_bgm_segments(
    manual_bgm: Optional[str],
    moods: List[str],
    total_duration: float,
) -> List[BgmSegment]:
    """Plan BGM segments for the video.

    If manual_bgm is provided, use it as a single segment for the entire duration.
    Otherwise, distribute moods evenly across the timeline.
    """
    if manual_bgm:
        return [BgmSegment(
            mood="manual",
            source_path=manual_bgm,
            start=0.0,
            duration=total_duration,
        )]

    if not moods:
        moods = [BGM_DEFAULT_MOOD]

    segment_duration = total_duration / len(moods)
    segments = []
    for i, mood in enumerate(moods):
        segments.append(BgmSegment(
            mood=mood,
            source_path="",  # filled later by select_music or synth
            start=i * segment_duration,
            duration=segment_duration,
        ))
    return segments


def assemble_bgm_track(
    segments: List[BgmSegment],
    total_duration: float,
    work_dir: str,
) -> str:
    """Assemble multiple BGM segments into a single continuous WAV track.

    Handles trimming/looping each segment to its duration and crossfading between them.
    """
    if len(segments) == 1:
        seg = segments[0]
        output_path = os.path.join(work_dir, "bgm_assembled.wav")
        # Trim or loop to match total duration
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-stream_loop", "-1",  # loop indefinitely
                "-i", seg.source_path,
                "-t", str(total_duration),
                "-af", f"afade=t=in:d=1,afade=t=out:st={total_duration - 1}:d=1",
                "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        return output_path

    # Multi-segment: trim/loop each, then concat with crossfade
    seg_files = []
    for i, seg in enumerate(segments):
        seg_path = os.path.join(work_dir, f"bgm_seg_{i}.wav")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", seg.source_path,
                "-t", str(seg.duration),
                "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
                seg_path,
            ],
            check=True,
            capture_output=True,
        )
        seg_files.append(seg_path)

    # Crossfade segments together iteratively
    current = seg_files[0]
    for i in range(1, len(seg_files)):
        crossfaded = os.path.join(work_dir, f"bgm_xfade_{i}.wav")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", current,
                "-i", seg_files[i],
                "-filter_complex",
                f"[0:a][1:a]acrossfade=d={BGM_CROSSFADE}:c1=tri:c2=tri[out]",
                "-map", "[out]",
                "-c:a", "pcm_s16le",
                crossfaded,
            ],
            check=True,
            capture_output=True,
        )
        current = crossfaded

    # Final trim + fade out
    output_path = os.path.join(work_dir, "bgm_assembled.wav")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", current,
            "-t", str(total_duration),
            "-af", f"afade=t=out:st={total_duration - 1}:d=1",
            "-c:a", "pcm_s16le",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


DUCK_SR = 48000


def _decode_f32(path: str, sr: int = DUCK_SR, channels: int = 2):
    """Decode any audio file to a float32 [n, channels] array."""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
         "-ac", str(channels), "-ar", str(sr), "-"],
        stdin=subprocess.DEVNULL, capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    return a[: len(a) // channels * channels].reshape(-1, channels).copy()


def duck_gain(key, sr: int = DUCK_SR, threshold: float = None,
              ratio: float = None, attack_ms: float = None,
              release_ms: float = None):
    """Per-sample gain for a bed ducked under `key`, as a compressor would.

    Replaces `sidechaincompress`, which shipped a real defect: it silently
    stopped passing the bed ~1.6s before the end of a video while the bed file
    itself still measured -23.6 dBFS, and the mixed output was bit-identical to
    the no-music version there. Three filter-graph fixes moved the number
    without explaining it (references/delivery-traps.md #4b).

    Standard downward compression on the key, so the config values keep the
    meaning they always had. Gain reduction is bounded by construction, so the
    bed is attenuated — it can never drop out or fail to return.
    """
    import numpy as np
    threshold = BGM_DUCK_THRESHOLD if threshold is None else threshold
    ratio = BGM_DUCK_RATIO if ratio is None else ratio
    attack_ms = BGM_DUCK_ATTACK if attack_ms is None else attack_ms
    release_ms = BGM_DUCK_RELEASE if release_ms is None else release_ms

    n = len(key)
    mono = np.abs(key).max(axis=1) if key.ndim > 1 else np.abs(key)
    hop = max(1, sr // 100)                                   # 10ms
    pad = (-n) % hop
    env = np.abs(np.concatenate([mono, np.zeros(pad)])).reshape(-1, hop).max(axis=1)

    thr_db = 20 * np.log10(max(threshold, 1e-9))
    lvl_db = 20 * np.log10(np.maximum(env, 1e-9))
    over = np.maximum(lvl_db - thr_db, 0.0)
    target_gr = over * (1.0 - 1.0 / max(ratio, 1.000001))     # dB, >= 0

    # one-pole smoothing at the hop rate; attack when clamping down harder
    hops_per_s = sr / hop
    a_atk = 1 - np.exp(-1.0 / max(attack_ms / 1000 * hops_per_s, 1e-6))
    a_rel = 1 - np.exp(-1.0 / max(release_ms / 1000 * hops_per_s, 1e-6))
    gr = np.empty_like(target_gr)
    cur = 0.0
    for i, t in enumerate(target_gr):
        cur += (t - cur) * (a_atk if t > cur else a_rel)
        gr[i] = cur

    g = 10 ** (-gr / 20.0)
    return np.interp(np.arange(n), np.arange(len(g)) * hop, g)


def apply_ducking(bgm_path: str, speech_path: str, work_dir: str) -> str:
    """Duck the BGM under the speech, and return a bed the length of the speech.

    The length is ASSERTED rather than assumed: a bed shorter than the speech is
    exactly how the music ends up missing from the last seconds of a delivery,
    and it is invisible in every intermediate file.
    """
    import numpy as np
    output_path = os.path.join(work_dir, "bgm_ducked.wav")

    normed = os.path.join(work_dir, "bgm_norm.wav")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", bgm_path,
         "-af", "loudnorm=I=-10:TP=-1:LRA=11",
         "-ar", str(DUCK_SR), "-ac", "2", "-c:a", "pcm_s16le", normed],
        check=True, capture_output=True)

    bed = _decode_f32(normed)
    speech = _decode_f32(speech_path)
    n = len(speech)
    if len(bed) < n:                                   # loop, never run short
        reps = int(np.ceil(n / max(len(bed), 1)))
        bed = np.tile(bed, (reps, 1))
    bed = bed[:n]

    ducked = bed * duck_gain(speech)[:, None]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(DUCK_SR),
         "-ac", "2", "-i", "-", "-c:a", "pcm_s16le", output_path],
        input=ducked.astype(np.float32).tobytes(), check=True, capture_output=True)

    got = _decode_f32(output_path)
    if abs(len(got) - n) > DUCK_SR // 20:              # 50ms
        raise RuntimeError(
            f"ducked bed is {len(got) / DUCK_SR:.2f}s but the speech is "
            f"{n / DUCK_SR:.2f}s — the music would be missing from the end")
    return output_path


def mix_speech_and_bgm(speech_path: str, bgm_ducked_path: str, work_dir: str) -> str:
    """Mix speech and ducked BGM into a single WAV.

    Speech is loudness-normalized (loudnorm) first so volume stays consistent
    across the entire recording, then VOICE_VOLUME gain is applied.
    BGM_VOLUME controls how loud BGM sits underneath.
    """
    output_path = os.path.join(work_dir, "bgm_mixed.wav")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", speech_path,
            "-i", bgm_ducked_path,
            "-filter_complex",
            f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,volume={VOICE_VOLUME}[speech_vol];"
            f"[1:a]volume={BGM_VOLUME}[bgm_vol];"
            f"[speech_vol][bgm_vol]amix=inputs=2:duration=first:normalize=0[aout]",
            "-map", "[aout]",
            "-c:a", "pcm_s16le",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def detect_topic_transitions(
    broll_plan_path: str,
    words_path: str = None,
    script_path: str = None,
) -> List[float]:
    """Detect topic transition timestamps.

    Strategy (in priority order):
    1. Transcript markers: scan words.json for spoken transition phrases like
       "換個畫面", "最後講一個", "接下來" — the most reliable signal because
       they are explicit topic-switch cues spoken by the presenter.
    2. Script JSON timing hints: use timing_hint from tech-digest script items
       to identify topic boundaries (useful fallback for scripted content).
       Note: script items include sub-topic B-roll (not just topic boundaries),
       so this produces more transitions than strategy 1.
    3. B-roll gap analysis: find the largest gaps between consecutive
       B-roll segments (last resort).

    Returns list of transition timestamps (seconds).
    """
    # --- Strategy 1: transcript transition markers ---
    transition_phrases = [
        "換個畫面", "最後講一個", "最後講",
        "第二個", "第二,", "最後,", "最後", "接下來", "第三個", "第三,",
    ]
    # Multi-word phrases to detect across adjacent words
    multi_word_markers = [
        ["換", "個", "畫面"],
        ["最後", "講", "一個"],
        ["最後", "講一個"],
        ["換個", "畫面"],
    ]
    marker_times = []
    if words_path and os.path.exists(words_path):
        with open(words_path, "r", encoding="utf-8") as f:
            words = json.load(f)
        # Single-word match
        for w in words:
            text = w.get("text", "").strip().rstrip(",，。")
            if text in [p.rstrip(",，。") for p in transition_phrases]:
                marker_times.append(w["start"])
        # Multi-word sequence match (Whisper may split phrases)
        texts = [w.get("text", "").strip().rstrip(",，。") for w in words]
        for pattern in multi_word_markers:
            plen = len(pattern)
            for i in range(len(texts) - plen + 1):
                if texts[i:i + plen] == pattern:
                    marker_times.append(words[i]["start"])

    # Deduplicate and sort
    if marker_times:
        marker_times = sorted(set(marker_times))
        # Filter by min gap
        filtered = [marker_times[0]]
        for t in marker_times[1:]:
            if (t - filtered[-1]) >= SFX_TRANSITION_MIN_GAP:
                filtered.append(t)
        print(f"  Detected {len(filtered)} topic transition(s) from transcript: "
              f"{[f'{t:.1f}s' for t in filtered]}")
        return filtered

    # --- Strategy 2: script JSON timing hints ---
    if script_path and os.path.exists(script_path):
        from modules.broll import parse_timing_hint
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        items = script.get("items", [])
        if len(items) >= 2:
            transitions = []
            for i in range(1, len(items)):
                hint = items[i].get("timing_hint", "")
                ts = parse_timing_hint(hint)
                if ts > 0:
                    transitions.append(ts)
            # Filter to keep only significant gaps (skip items at similar timestamps)
            filtered = []
            for ts in transitions:
                if not filtered or (ts - filtered[-1]) >= SFX_TRANSITION_MIN_GAP:
                    filtered.append(ts)
            if filtered:
                print(f"  Detected {len(filtered)} topic transition(s) from script timing hints: "
                      f"{[f'{t:.1f}s' for t in filtered]}")
                return filtered

    # --- Strategy 3: B-roll gap analysis ---
    if not broll_plan_path or not os.path.exists(broll_plan_path):
        return []

    with open(broll_plan_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    # Use all segments as anchors (not just from_script)
    anchors = sorted(
        [s for s in segments if s.get("start_hint") is not None],
        key=lambda s: float(s.get("start_hint", 0)),
    )
    if len(anchors) < 2:
        return []

    gaps = []
    for i in range(len(anchors) - 1):
        end_of_prev = float(anchors[i]["start_hint"]) + float(anchors[i].get("duration", 4))
        start_of_next = float(anchors[i + 1]["start_hint"])
        gap = start_of_next - end_of_prev
        if gap >= SFX_TRANSITION_MIN_GAP:
            gaps.append((gap, end_of_prev))

    if not gaps:
        return []

    gaps.sort(reverse=True)
    return [t for _, t in gaps]


def mix_transition_sfx(
    mixed_path: str,
    sfx_path: str,
    timestamps: List[float],
    work_dir: str,
) -> str:
    """Overlay transition SFX at specified timestamps without touching main audio volume.

    SFX is mixed on a separate track and added on top.  Main audio passes through
    unchanged — no ducking, no volume expression, no side effects.
    """
    if not timestamps or not sfx_path or not os.path.exists(sfx_path):
        return mixed_path

    output_path = os.path.join(work_dir, "bgm_mixed_sfx.wav")
    filter_script = os.path.join(work_dir, "sfx_filter.txt")

    # Main audio passes through untouched
    filter_parts = []
    inputs = ["-i", mixed_path]
    sfx_labels = []

    for i, ts in enumerate(timestamps):
        inputs.extend(["-i", sfx_path])
        delay_ms = int(ts * 1000)
        idx = i + 1
        label = f"sfx{i}"
        # Downmix to mono (match main), short fade-in to avoid click
        filter_parts.append(
            f"[{idx}:a]adelay={delay_ms}|{delay_ms},"
            f"pan=mono|c0=0.5*c0+0.5*c1,"
            f"afade=t=in:d=0.01,"
            f"volume={SFX_TRANSITION_VOLUME}[{label}]"
        )
        sfx_labels.append(f"[{label}]")

    # Merge all SFX into one track, then add on top of main audio
    if len(sfx_labels) > 1:
        all_sfx = "".join(sfx_labels)
        filter_parts.append(
            f"{all_sfx}amix=inputs={len(sfx_labels)}:"
            f"duration=longest:normalize=0[sfx_all]"
        )
        filter_parts.append(
            "[0:a][sfx_all]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_parts.append(
            f"[0:a]{sfx_labels[0]}amix=inputs=2:duration=first:normalize=0[aout]"
        )

    with open(filter_script, "w") as f:
        f.write(";\n".join(filter_parts))

    subprocess.run(
        ["ffmpeg", "-y"] + inputs + [
            "-filter_complex_script", filter_script,
            "-map", "[aout]",
            "-c:a", "pcm_s16le",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def run_bgm(
    trimmed_video: str,
    work_dir: str,
    words_path: Optional[str] = None,
    manual_bgm: Optional[str] = None,
    sfx_path: Optional[str] = None,
    broll_plan_path: Optional[str] = None,
    script_path: Optional[str] = None,
    music_request: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Orchestrate BGM pipeline: mood analysis → select/synth → duck → mix → SFX.

    Args:
        trimmed_video: Path to silence-removed video.
        work_dir: Working directory for intermediate files.
        words_path: Path to words.json for transcript text (optional).
        manual_bgm: Path to user-supplied BGM file (skips mood analysis).
        sfx_path: Path to transition SFX file (optional, e.g. whoosh sound).
        broll_plan_path: Path to broll_plan.json for topic transition detection.
        script_path: Path to tech-digest script JSON for timing hints (optional).

    Returns:
        Path to bgm_mixed.wav (speech + ducked BGM + optional SFX).
    """
    # 1. Extract speech audio
    print("  Extracting speech audio...")
    speech_path = extract_speech_audio(trimmed_video, work_dir)
    total_duration = get_audio_duration(speech_path)

    # 1b. A track the user NAMED is not a mood. Resolve it before falling back
    # to mood analysis, so "音樂：<artist> — <title>" is honoured instead of
    # silently replaced by whatever the mood picker likes. The ladder always
    # terminates, so this can never stall the build (see resolve_music.py).
    music_note = None
    if not manual_bgm and music_request:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from resolve_music import resolve as _resolve
        picked = _resolve(music_request, project_dir=project_dir)
        music_note = picked
        print(f"  Music: {picked.note}")
        if picked.path:
            manual_bgm = picked.path
        if not picked.exact:
            print("  NOTE: this is a STAND-IN, not the track that was asked for. "
                  "Name the deliverable -standin-<mood>, never after their track.")

    # 2. Analyze mood (skip if manual BGM)
    moods = [BGM_DEFAULT_MOOD]
    if not manual_bgm and words_path and os.path.exists(words_path):
        print("  Analyzing mood from transcript...")
        with open(words_path, "r", encoding="utf-8") as f:
            words_data = json.load(f)
        transcript = " ".join(w["text"] for w in words_data)
        moods = analyze_mood(transcript)
        print(f"  Detected moods: {moods}")

    # 3. Plan segments
    segments = plan_bgm_segments(manual_bgm, moods, total_duration)
    print(f"  Planned {len(segments)} BGM segment(s)")

    # 4. Select music or generate synth for each segment
    for seg in segments:
        if seg.source_path and os.path.exists(seg.source_path):
            continue  # manual BGM already has path
        track = select_music(seg.mood)
        if track:
            print(f"  Using library track: {os.path.basename(track)} ({seg.mood})")
            seg.source_path = track
        else:
            print(f"  No library for '{seg.mood}', generating synth pad...")
            seg.source_path = generate_synth_pad(seg.mood, BGM_SYNTH_PAD_DURATION, work_dir)

    # 5. Assemble continuous BGM track
    print("  Assembling BGM track...")
    bgm_track = assemble_bgm_track(segments, total_duration, work_dir)

    # 6. Apply ducking
    print("  Applying auto-ducking (sidechaincompress)...")
    bgm_ducked = apply_ducking(bgm_track, speech_path, work_dir)

    # 7. Mix speech + BGM
    print("  Mixing speech + BGM...")
    bgm_mixed = mix_speech_and_bgm(speech_path, bgm_ducked, work_dir)

    # 8. Overlay transition SFX (if provided)
    if sfx_path and os.path.exists(sfx_path):
        plan_path = broll_plan_path or os.path.join(work_dir, "broll_plan.json")
        transitions = detect_topic_transitions(
            plan_path, words_path=words_path, script_path=script_path
        )
        if transitions:
            print(f"  Detected {len(transitions)} topic transition(s): "
                  f"{[f'{t:.1f}s' for t in transitions]}")
            print(f"  Mixing transition SFX ({os.path.basename(sfx_path)})...")
            bgm_mixed = mix_transition_sfx(bgm_mixed, sfx_path, transitions, work_dir)
        else:
            print("  No topic transitions detected — skipping SFX")

    print(f"  Done: {bgm_mixed}")
    return bgm_mixed


def measure_audible_end(path: str, floor_dbfs: float = -40.0) -> float:
    """Seconds at which the track stops making sound.

    A property of the FILE, so it is measured rather than passed in. It was once
    a hand-typed constant: correct for one track, silently wrong for the next,
    and being wrong here plays the closing card in silence.
    """
    import math
    import subprocess

    sr = 8000
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
         "-ar", str(sr), "-"], capture_output=True).stdout
    import array
    a = array.array("f")
    a.frombytes(raw[: len(raw) // 4 * 4])
    if not a:
        return 0.0

    win = sr // 4
    last = 0.0
    for i in range(len(a) // win):
        chunk = a[i * win:(i + 1) * win]
        rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
        if 20 * math.log10(max(rms, 1e-9)) > floor_dbfs:
            last = (i + 1) * (win / sr)
    return last


TAIL_FADE_MAX = 1.0


def derive_tail_fade(closing_shot_s: float) -> float:
    """Length of the music fade at the very end.

    EDGE, not a constant: it depends on the closing shot. Half the shot, capped,
    so the fade can never be longer than the picture it plays under.
    """
    return min(TAIL_FADE_MAX, closing_shot_s * 0.5)
