"""Smoke tests for buildkit — each primitive on tiny synthetic media.

These run real ffmpeg with h264_videotoolbox, so they are macOS-only by
design: buildkit exists to lock THIS machine's fast path.
"""
import json
import os
import subprocess
import sys

import pytest

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

import buildkit as bk  # noqa: E402


def test_run_records_opt_in_command_timing(tmp_path, monkeypatch):
    timing_log = tmp_path / "timings.jsonl"
    env_log = tmp_path / "env-timings.jsonl"
    monkeypatch.setenv("YIIBU_TIMING_LOG", str(env_log))

    result = bk.run(
        [sys.executable, "-c", "print('ok')"],
        timing_log=timing_log,
    )

    row = json.loads(timing_log.read_text())
    assert result.stdout.strip() == "ok"
    assert row["command_kind"] == os.path.basename(sys.executable)
    assert row["elapsed_seconds"] >= 0
    assert row["outcome"] == "success"
    assert row["returncode"] == 0
    assert "cmd" not in row
    assert "args" not in row
    assert not env_log.exists()


def test_run_records_env_failure_without_command_arguments(tmp_path, monkeypatch):
    timing_log = tmp_path / "timings.jsonl"
    monkeypatch.setenv("YIIBU_TIMING_LOG", str(timing_log))

    with pytest.raises(RuntimeError, match="FAILED"):
        bk.run([sys.executable, "-c", "raise SystemExit(7)", "secret-value"])

    raw = timing_log.read_text()
    row = json.loads(raw)
    assert row["command_kind"] == os.path.basename(sys.executable)
    assert row["outcome"] == "failure"
    assert row["returncode"] == 7
    assert "secret-value" not in raw


def test_run_timing_write_error_does_not_change_command_result(tmp_path, capsys):
    result = bk.run(
        [sys.executable, "-c", "print('ok')"],
        timing_log=tmp_path,
    )

    assert result.stdout.strip() == "ok"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not write timing log" in captured.err

    with pytest.raises(RuntimeError, match="FAILED"):
        bk.run(
            [sys.executable, "-c", "raise SystemExit(9)"],
            timing_log=tmp_path,
        )


def _has_videotoolbox() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError):
        return False
    return "h264_videotoolbox" in (r.stdout or "")


# Without this the whole module ERRORS on Linux — the fixture below builds its
# synthetic clip with h264_videotoolbox, which only exists on macOS. A fresh
# clone there ran `pytest` and got a red suite on its first command, which is
# exactly the failure conftest.py was written to prevent.
pytestmark = pytest.mark.skipif(
    not _has_videotoolbox(),
    reason="buildkit locks the macOS fast path; no h264_videotoolbox on this machine",
)


@pytest.fixture()
def clip(tmp_path):
    p = str(tmp_path / "src.mov")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "color=c=slategray:s=1080x1920:r=30:d=4",
         "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4",
         "-c:v", "h264_videotoolbox", "-b:v", "5M", "-c:a", "pcm_s16le",
         "-y", p], check=True, capture_output=True)
    return p


def _frames_and_samples(p):
    """Each stream counted on its own: packets for the picture, DECODED samples
    for the sound. The container's duration is the longer of the two, which is
    exactly why it could not see this defect."""
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", p],
        check=True, capture_output=True, text=True).stdout.strip()
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-map", "0:a",
                          "-f", "s16le", "-ac", "1", "-"],
                         check=True, capture_output=True).stdout
    return int(frames), len(pcm) // 2


def test_prep_segment_is_frame_and_sample_exact_after_input_seek(clip, tmp_path):
    """2026-10-05, a 30 fps iPhone MOV cut at 29.95s for 2.8667s: input -ss plus
    an OUTPUT -t under -r 30 wrote 87 frames (2.900s) over 2.867s of audio. The
    container said 2.90s, the ±0.10s check passed, and concat then started each
    next file where the picture ended — the audio ran 50 ms early by the end.
    0.95s reproduces it on synthetic media: not a whole frame after the seek,
    and 2.8667s is not a whole number of frames either."""
    out = bk.prep_segment(clip, 0.95, 0.95 + 2.8667, str(tmp_path / "seg.mov"))
    assert _frames_and_samples(out) == (86, 86 * 1600)


def test_prep_segment_refuses_a_cut_the_source_cannot_fill(clip, tmp_path):
    """The source has 30 frames after 3.0s and the cut asks for 32. The ±0.10s
    check let that through, and a timeline built from tin/tout then runs two
    frames long against the picture for every cut after this one."""
    with pytest.raises(RuntimeError, match="30 frames"):
        bk.prep_segment(clip, 3.0, 4.08, str(tmp_path / "seg.mov"))


def test_concat_keeps_audio_in_lockstep_with_picture(clip, tmp_path):
    a = bk.prep_segment(clip, 0.5, 0.5 + 1.4333, str(tmp_path / "a.mov"))
    b = bk.prep_segment(clip, 2.013, 2.013 + 1.4333, str(tmp_path / "b.mov"))
    out = bk.concat([a, b], str(tmp_path / "cat.mov"))
    assert _frames_and_samples(out) == (86, 86 * 1600)


def test_concat_refuses_a_part_whose_audio_and_picture_differ(clip, tmp_path):
    """A part cut the old way, by hand. The concat demuxer starts the next
    file where this one's container ends, so its short audio becomes a gap
    that the final asetpts=N/SR/TB closes up — every later word early."""
    bad = str(tmp_path / "bad.mov")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.95", "-i", clip,
                    "-t", "2.867", "-vf", bk.VF_FILL, "-af", "asetpts=N/SR/TB",
                    *bk.VENC, *bk.AENC_PCM, bad], check=True, capture_output=True)
    frames, samples = _frames_and_samples(bad)
    assert samples != frames * 1600, "this ffmpeg no longer reproduces the defect"
    good = bk.prep_segment(clip, 0.0, 0.5, str(tmp_path / "good.mov"))
    with pytest.raises(RuntimeError, match="bad.mov"):
        bk.concat([good, bad], str(tmp_path / "cat.mov"))


def test_overlay_pills_renders_every_pill(clip, tmp_path):
    """The framesync regression: chained overlays showed only the FIRST pill."""
    import numpy as np
    from PIL import Image
    pngs = []
    for i, colour in enumerate([(255, 0, 0, 255), (0, 255, 0, 255)]):
        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        img.paste(Image.new("RGBA", (400, 120), colour), (340, 380))
        p = str(tmp_path / f"pill{i}.png")
        img.save(p)
        pngs.append(p)
    pills = [{"start": 0.5, "end": 1.5, "png": pngs[0]},
             {"start": 2.5, "end": 3.5, "png": pngs[1]}]
    out = bk.overlay_pills(clip, pills, str(tmp_path), str(tmp_path / "p.mov"))

    def frame(t):
        f = str(tmp_path / f"f{t}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", out,
                        "-frames:v", "1", "-update", "1", f],
                       check=True, capture_output=True)
        return np.asarray(Image.open(f).convert("RGB"))[380:500, 340:740]

    assert frame(1.0)[:, :, 0].mean() > 150, "first pill (red) missing"
    assert frame(3.0)[:, :, 1].mean() > 150, "SECOND pill (green) missing — framesync regression"
    assert frame(2.0).mean() < 150, "pill visible outside its window"


def test_duck_mix_keeps_bed_to_the_end(clip, tmp_path):
    import numpy as np
    bed = str(tmp_path / "bed.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=1320:sample_rate=48000:duration=4",
                    "-ac", "2", "-c:a", "pcm_s16le", bed], check=True,
                   capture_output=True)
    f32, n = bk.duck_mix(clip, bed, str(tmp_path))
    a = np.frombuffer(open(f32, "rb").read(), dtype=np.float32).reshape(-1, 2)
    tail = a[-48000:]
    rms = float(np.sqrt((tail ** 2).mean()))
    assert 20 * np.log10(max(rms, 1e-9)) > -40, "bed/mix silent at the end"


def test_duck_mix_rejects_short_bed(clip, tmp_path):
    bed = str(tmp_path / "short.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=1320:sample_rate=48000:duration=1",
                    "-ac", "2", "-c:a", "pcm_s16le", bed], check=True,
                   capture_output=True)
    with pytest.raises(RuntimeError, match="missing"):
        bk.duck_mix(clip, bed, str(tmp_path))


def test_final_encode_aborts_above_full_scale(clip, tmp_path):
    out = bk.final_encode(clip, str(tmp_path / "f.mp4"), bk.afx_chain(0.0))
    pk, over = bk.decoded_peak(out)
    assert pk <= 0.0 and over == 0


def test_build_lint_catches_the_expensive_patterns(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('subprocess.run(["ffmpeg","-c:v","libx264"])\n'
                   'x="[a][b]sidechaincompress=threshold=0.1[d]"\n')
    sys.path.insert(0, SKILL)
    import build_lint
    hits = build_lint.lint(str(bad))
    assert len(hits) == 2
