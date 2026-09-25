"""Tests for silence_cut module — clap detection logic."""
import json
import os
import shutil
import subprocess

import pytest

from modules.silence_cut import (
    find_clap_markers, extract_rms_values, render_faded_cut,
    invert_ranges, chunks_to_keep_ranges, keep_ranges_to_boundaries,
    run_silence_cut,
)


def _stub_silence_pipeline(monkeypatch, tmp_path, *, clap_times, chunks=None):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    renders = []

    def fake_run(command, **kwargs):
        output = command[-1]
        if "auto_editor" in command:
            with open(output, "w") as fh:
                json.dump({"chunks": chunks}, fh)
        else:
            with open(output, "wb") as fh:
                fh.write(b"stage")
        return subprocess.CompletedProcess(command, 0)

    def fake_render(input_video, keep_ranges, output_video, fade_ms=None):
        renders.append((input_video, keep_ranges, output_video))
        with open(output_video, "wb") as fh:
            fh.write(b"render")
        return output_video

    def fake_remove_claps(input_video, output_video, detected_claps):
        renders.append((input_video, detected_claps, output_video))
        with open(output_video, "wb") as fh:
            fh.write(b"render")
        return output_video

    monkeypatch.setattr("modules.silence_cut.subprocess.run", fake_run)
    monkeypatch.setattr("modules.silence_cut.extract_rms_values", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("modules.silence_cut.find_clap_markers", lambda *_args, **_kwargs: clap_times)
    monkeypatch.setattr("modules.silence_cut.remove_clap_segments", fake_remove_claps)
    monkeypatch.setattr("modules.silence_cut.render_faded_cut", fake_render)
    monkeypatch.setattr("modules.silence_cut._probe_fps", lambda _path: 1.0)
    monkeypatch.setattr(
        "modules.silence_cut._probe_duration",
        lambda path: 5.8 if path.endswith("trimmed.mp4") else 10.0,
    )
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object() if chunks is not None else None)
    return source, renders


def test_run_silence_cut_composes_all_cut_stages_into_original_timeline(
    tmp_path, monkeypatch,
):
    source, _ = _stub_silence_pipeline(
        monkeypatch,
        tmp_path,
        clap_times=[4.0],
        chunks=[[0.0, 0.5, 1.0], [0.5, 1.5, 99999.0], [1.5, 6.8, 1.0]],
    )
    work = tmp_path / "work"

    out = run_silence_cut(str(source), str(work), manual_cuts=[(1.0, 2.0)])

    assert out == str(work / "trimmed.mp4")
    with open(work / "timeline.json") as fh:
        timeline = json.load(fh)
    assert timeline == {
        "kind": "postprod",
        "total": 4.8,
        "segments": [
            {"id": "take-000", "file": str(source.resolve()), "start": 0.0,
             "dur": 0.5, "source_start": 0.0, "source_end": 0.5},
            {"id": "take-001", "file": str(source.resolve()), "start": 0.5,
             "dur": 0.5, "source_start": 4.7, "source_end": 5.2},
            {"id": "take-002", "file": str(source.resolve()), "start": 1.0,
             "dur": 3.8, "source_start": 6.2, "source_end": 10.0},
        ],
    }
    with open(work / "boundaries.json") as fh:
        assert json.load(fh) == {"boundaries": [0.5, 1.0]}


def test_run_silence_cut_writes_one_original_segment_when_nothing_is_cut(
    tmp_path, monkeypatch,
):
    source, _ = _stub_silence_pipeline(
        monkeypatch, tmp_path, clap_times=[], chunks=None,
    )
    work = tmp_path / "work"

    run_silence_cut(str(source), str(work))

    with open(work / "timeline.json") as fh:
        timeline = json.load(fh)
    assert timeline == {
        "kind": "postprod",
        "total": 10.0,
        "segments": [
            {"id": "take-000", "file": str(source.resolve()), "start": 0.0,
             "dur": 10.0, "source_start": 0.0, "source_end": 10.0},
        ],
    }
    with open(work / "boundaries.json") as fh:
        assert json.load(fh) == {"boundaries": []}


def test_run_silence_cut_failure_backs_up_stale_timeline_proof(
    tmp_path, monkeypatch,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    work.mkdir()
    previous = {"kind": "authored", "total": 7.0, "segments": []}
    with open(work / "timeline.json", "w") as fh:
        json.dump(previous, fh)

    def fail_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr("modules.silence_cut.subprocess.run", fail_run)

    with pytest.raises(subprocess.CalledProcessError):
        run_silence_cut(str(source), str(work))

    assert not (work / "timeline.json").exists()
    backups = list(work.glob("timeline.previous*.json"))
    assert len(backups) == 1
    with open(backups[0]) as fh:
        assert json.load(fh) == previous


def test_keep_ranges_to_boundaries():
    """Output-timeline boundary offsets = cumulative kept durations,
    excluding the final trailing edge."""
    assert keep_ranges_to_boundaries([(0.0, 1.0), (2.0, 3.0)]) == [1.0]
    assert keep_ranges_to_boundaries([(0.0, 1.0), (2.0, 3.0), (5.0, 6.5)]) == [1.0, 2.0]
    assert keep_ranges_to_boundaries([(0.0, 1.0)]) == []
    assert keep_ranges_to_boundaries([]) == []


def test_invert_ranges_basic():
    """Complement of cut ranges within [0, total]."""
    assert invert_ranges([(0.8, 1.2)], 3.0) == [(0.0, 0.8), (1.2, 3.0)]


def test_invert_ranges_at_start():
    """A cut touching t=0 must not yield a zero-length leading keep."""
    assert invert_ranges([(0.0, 0.5)], 2.0) == [(0.5, 2.0)]


def test_invert_ranges_merges_overlaps():
    """Overlapping/adjacent cut zones collapse before inverting."""
    assert invert_ranges([(0.5, 1.0), (0.9, 1.5)], 3.0) == [(0.0, 0.5), (1.5, 3.0)]


def test_invert_ranges_no_cuts():
    """No cuts -> whole clip is kept."""
    assert invert_ranges([], 2.0) == [(0.0, 2.0)]


def test_chunks_to_keep_ranges_v1():
    """auto-editor v1 chunks -> kept (start_s, end_s) ranges; 99999 = cut."""
    chunks = [[0, 36, 1.0], [36, 54, 99999.0], [54, 90, 1.0]]
    assert chunks_to_keep_ranges(chunks, fps=30.0) == [(0.0, 1.2), (1.8, 3.0)]


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _make_tone_clip(path: str, duration: float = 3.0) -> None:
    """Constant full-amplitude 440Hz tone over a black video."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=320x240:r=30:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}:sample_rate=44100",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", path,
        ],
        check=True, capture_output=True,
    )


def _rms_around(video: str, work: str, t: float, win_frames: int = 4):
    """Return (min RMS within +/-win of t, reference RMS at a mid-segment point)."""
    wav = os.path.join(work, "probe.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", wav],
        check=True, capture_output=True,
    )
    rms = extract_rms_values(wav, frame_ms=10)
    idx = int(t * 100)  # 10ms frames -> 100 frames/sec
    lo, hi = max(0, idx - win_frames), min(len(rms), idx + win_frames)
    boundary_min = min(rms[lo:hi])
    ref = rms[int(0.5 * 100)]  # mid of first kept segment
    return boundary_min, ref


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_render_faded_cut_fades_internal_boundary(tmp_path):
    """Splicing two non-adjacent keep-ranges must fade audio at the internal
    boundary — a hard cut leaves full amplitude across the splice (pop)."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_tone_clip(src, duration=3.0)

    # Keep [0,1] and [2,3] -> internal splice lands at output t=1.0s
    render_faded_cut(src, [(0.0, 1.0), (2.0, 3.0)], out, fade_ms=30)

    boundary_min, ref = _rms_around(out, str(tmp_path), t=1.0)
    # With a real fade, amplitude near the boundary collapses toward zero.
    assert boundary_min < 0.25 * ref, (
        f"boundary RMS {boundary_min:.4f} not faded vs mid-segment {ref:.4f}"
    )


def _has_auto_editor() -> bool:
    """Ask the question silence_cut asks, in the interpreter it asks it in.

    This used to shell out to `python3 -m auto_editor`, i.e. whatever python3 is
    first on PATH. modules/silence_cut.py checks importlib.util.find_spec in the
    RUNNING interpreter and then runs sys.executable. Inside a venv with only the
    core deps the two disagreed: the code correctly skipped silence removal, the
    test found the system python's copy, did not skip, and failed on the empty
    result. A probe that asks a different question than the code is worse than no
    probe — it reports a red suite for a machine that is behaving correctly.
    """
    import importlib.util
    return importlib.util.find_spec("auto_editor") is not None


@pytest.mark.skipif(not (_has_ffmpeg() and _has_auto_editor()),
                    reason="ffmpeg/auto-editor not available")
def test_run_silence_cut_fades_manual_cut_boundary(tmp_path):
    """End-to-end through the manual-cut path: a pure tone with the middle
    second cut out must fade the join at output t=1.0, not hard-cut it.

    A pure tone has no silence, so auto-editor keeps everything and the only
    edit is the manual cut — making the boundary position deterministic."""
    from modules.silence_cut import run_silence_cut
    src = str(tmp_path / "src.mp4")
    _make_tone_clip(src, duration=3.0)

    out = run_silence_cut(src, str(tmp_path / "work"), manual_cuts=[(1.0, 2.0)])

    wav = str(tmp_path / "final.wav")
    subprocess.run(["ffmpeg", "-y", "-i", out, "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", wav], check=True, capture_output=True)
    rms = extract_rms_values(wav, frame_ms=10)
    boundary_min = min(rms[92:108])          # +/-80ms around output t=1.0
    ref = rms[50]                            # mid of first kept second
    assert boundary_min < 0.25 * ref, (
        f"manual-cut boundary RMS {boundary_min:.4f} not faded vs {ref:.4f} "
        f"— join was hard-cut"
    )


def _make_multi_gap(path: str) -> None:
    """tone .8s | silence .6s | tone .8s | silence .6s | tone .8s.
    auto-editor should drop both silences → two interior joins."""
    parts = []
    for i, (kind, d) in enumerate([("t", .8), ("s", .6), ("t", .8), ("s", .6), ("t", .8)]):
        src = ("sine=frequency=440:duration={d}:sample_rate=44100"
               if kind == "t" else "anullsrc=r=44100:cl=mono:d={d}").format(d=d)
        parts.append(("-f", "lavfi", "-i", src))
    inputs = [x for p in parts for x in p]
    n = len(parts)
    subprocess.run(
        ["ffmpeg", "-y", *inputs,
         "-filter_complex", f"{''.join(f'[{i}]' for i in range(n))}concat=n={n}:v=0:a=1[a]",
         "-map", "[a]", path.replace(".mp4", ".wav")],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=3.6",
         "-i", path.replace(".mp4", ".wav"),
         "-c:v", "libx264", "-c:a", "aac", "-shortest", path],
        check=True, capture_output=True,
    )


@pytest.mark.skipif(not (_has_ffmpeg() and _has_auto_editor()),
                    reason="ffmpeg/auto-editor not available")
def test_run_silence_cut_silence_path_glue_sync_format(tmp_path):
    """Primary path: auto-editor v1 detection → faded render. Verifies the
    glue (v1 parse + fps), that verify.py accepts the result (silence-adjacent
    joins correctly skipped), A/V sync, and source format preserved.

    Note: with --margin 0.2s the silence joins land between retained silence
    margins, so the join itself is silence-to-silence — the fade is applied
    (unit-tested in render_faded_cut) but there is little pop to measure here.
    Audible-to-audible joins are covered by the manual-cut test."""
    import json as _json
    from modules.silence_cut import run_silence_cut
    from verify import check_cut_boundaries
    src = str(tmp_path / "src.mp4")
    _make_multi_gap(src)
    work = str(tmp_path / "work")

    out = run_silence_cut(src, work)

    # Glue worked: boundaries.json written from v1 chunks
    with open(os.path.join(work, "boundaries.json")) as fh:
        boundaries = _json.load(fh)["boundaries"]
    assert len(boundaries) >= 1, "expected at least one silence join"

    # verify.py accepts it (no un-faded pop; silence-adjacent joins skipped)
    assert check_cut_boundaries(work)["pass"]

    # Silence removed: output shorter than 3.6s source
    def _dur(stream):
        return float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", stream,
             "-show_entries", "stream=duration", "-of", "csv=p=0", out],
            check=True, capture_output=True, text=True).stdout.strip())
    assert _dur("v:0") < 3.4, "silence was not removed"

    # A/V sync preserved through faded concat (within ~1 frame)
    assert abs(_dur("v:0") - _dur("a:0")) < 0.05, "A/V drift after faded concat"

    # Source video format preserved (codec / fps)
    def _probe(entry):
        return subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", f"stream={entry}", "-of", "csv=p=0", out],
            check=True, capture_output=True, text=True).stdout.strip()
    assert _probe("codec_name") == "h264"
    assert _probe("r_frame_rate") == "30/1"


def _zero_cross_rate(wav: str, t0: float, t1: float) -> int:
    """Zero-crossings in [t0,t1) of a mono 16-bit wav — a cheap pitch proxy
    (higher frequency → more crossings)."""
    import wave, struct
    with wave.open(wav, "r") as wf:
        sr = wf.getframerate()
        wf.setpos(int(t0 * sr))
        raw = wf.readframes(int((t1 - t0) * sr))
    s = struct.unpack(f"<{len(raw)//2}h", raw)
    return sum(1 for i in range(1, len(s)) if (s[i - 1] < 0) != (s[i] < 0))


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_render_faded_cut_preserves_segment_order(tmp_path):
    """Output follows keep_ranges order, not source order — guards the
    parallel-encode refactor against out-of-order concatenation."""
    src = str(tmp_path / "src.mp4")
    wav_src = str(tmp_path / "src.wav")
    # 0-1s = 300Hz, 1-2s = 600Hz, 2-3s = 900Hz
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=1:sample_rate=44100",
         "-f", "lavfi", "-i", "sine=frequency=600:duration=1:sample_rate=44100",
         "-f", "lavfi", "-i", "sine=frequency=900:duration=1:sample_rate=44100",
         "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1[a]", "-map", "[a]", wav_src],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=3",
         "-i", wav_src, "-c:v", "libx264", "-c:a", "aac", "-shortest", src],
        check=True, capture_output=True,
    )
    out = str(tmp_path / "out.mp4")
    # Reversed order: 900Hz range first, then 300Hz range → boundary at t=0.6
    render_faded_cut(src, [(2.0, 2.6), (0.0, 0.6)], out, fade_ms=30)

    wav = str(tmp_path / "out.wav")
    subprocess.run(["ffmpeg", "-y", "-i", out, "-vn", "-acodec", "pcm_s16le",
                    "-ar", "44100", "-ac", "1", wav], check=True, capture_output=True)
    # First segment (900Hz) must have far more zero-crossings than second (300Hz)
    first = _zero_cross_rate(wav, 0.1, 0.5)
    second = _zero_cross_rate(wav, 0.7, 1.1)
    assert first > 1.8 * second, f"order not preserved: zcr {first} vs {second}"


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_render_faded_cut_no_av_drift_many_segments(tmp_path):
    """Concatenating many segments must not accumulate A/V drift. The old
    `-c copy` AAC concat added ~1ms of audio padding per segment (~37ms over
    40 segments = >1 frame of lip-sync drift by the end)."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_tone_clip(src, duration=40.0)
    keeps = [(i * 1.0, i * 1.0 + 0.6) for i in range(40)]  # 40 segs, 39 joins

    render_faded_cut(src, keeps, out, fade_ms=30)

    def _dur(stream):
        return float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", stream,
             "-show_entries", "stream=duration", "-of", "csv=p=0", out],
            check=True, capture_output=True, text=True).stdout.strip())
    drift = abs(_dur("v:0") - _dur("a:0"))
    assert drift < 0.010, f"A/V drift {drift*1000:.1f}ms accumulated over 40 segments"


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_render_faded_cut_preserves_kept_duration(tmp_path):
    """Output duration equals the summed length of kept ranges."""
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _make_tone_clip(src, duration=3.0)

    render_faded_cut(src, [(0.0, 1.0), (2.0, 3.0)], out, fade_ms=30)

    dur = float(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", out],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    assert abs(dur - 2.0) < 0.15, f"expected ~2.0s, got {dur:.3f}s"


def test_find_clap_markers_detects_spike():
    """A volume spike above threshold should be detected as a clap marker."""
    # Simulated RMS values per 10ms frame (normalized 0-1)
    # Normal speech ~0.1, clap ~0.9
    rms_values = [0.1] * 100 + [0.9, 0.85] + [0.1] * 100
    markers = find_clap_markers(rms_values, threshold=0.7, frame_ms=10)
    assert len(markers) == 1
    assert abs(markers[0] - 1.0) < 0.05  # ~1.0 seconds


def test_find_clap_markers_no_false_positives():
    """Normal speech should not trigger clap detection."""
    rms_values = [0.1, 0.15, 0.12, 0.08, 0.11] * 50
    markers = find_clap_markers(rms_values, threshold=0.7, frame_ms=10)
    assert len(markers) == 0
