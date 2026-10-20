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


def test_spotlight_size_is_derived_from_the_phrase_not_chosen():
    """Four characters reach max_scale; seven come out smaller; a sentence too
    long to stay over min_scale is refused rather than shrunk (2026-10-23)."""
    import re
    import title
    spec = __import__("gates").house()
    sp = spec["captions"]["spotlight"]
    speech = spec["captions"]["styles"][sp["base_style"]]["size"]
    base = speech / title.libass_em(title._find_font())

    def scale(text):
        line = bk.spotlight_caption(0, 2, text)[1]
        fs = int(re.search(r"\\fs(\d+)", line).group(1))
        return fs / title.libass_em(title.spotlight_font()) / base

    assert abs(scale("**環境**很大") - sp["max_scale"]) < 0.02
    assert sp["min_scale"] <= scale("**環境**也非常重要") < sp["max_scale"]
    with pytest.raises(ValueError, match="split the sentence"):
        bk.spotlight_caption(0, 2, "所以你不管多久都還是只有 **100** 塊")
    with pytest.raises(ValueError, match="one line"):
        bk.spotlight_caption(0, 2, "環境\\N很大")


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
         "-show_entries", "stream=nb_read_packets", "-of", "default=nw=1:nk=1", p],
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


def _rotated(clip, tmp_path):
    rot = str(tmp_path / "rot.mov")
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", clip,
                    "-c", "copy", "-y", rot], check=True, capture_output=True)
    return rot


def test_av_length_reads_a_stream_that_carries_side_data(clip, tmp_path):
    """2026-10-14, a running reel: a friend's iPhone clip carries an 'Ambient
    viewing environment' block, prep_segment copies it onto the segment, and
    ffprobe's csv writer prints that section as an extra empty column — `84,`.
    int() refused it and the first build of the edit stopped inside
    prep_segment. A display rotation does the same and is easy to make."""
    assert bk.av_length(_rotated(clip, tmp_path)) == bk.av_length(clip)


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


def _ending_noise_case(tmp_path):
    """3 s of syllables, then 4 s of crowd noise with nobody talking.

    Reconstructs 2026-10-20: after the last word, room noise on the closing
    shots kept crossing the automatic threshold, so the bed sat ~17 dB under
    the cut for the whole ending — the critic heard "the music goes dull".
    """
    import wave
    import numpy as np
    sr = 48000
    t = np.arange(7 * sr) / sr
    x = np.full(len(t), 0.002)
    talk = (t < 3.0) & ((t % 0.2) < 0.15)
    x[talk] = 0.5 * np.sin(2 * np.pi * 200 * t[talk])
    steps = (t >= 3.0) & ((t % 0.5) < 0.4)
    x[steps] = 0.3 * np.random.default_rng(0).uniform(-1, 1, steps.sum())
    sp = str(tmp_path / "speech.wav")
    with wave.open(sp, "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((np.repeat(x, 2) * 32767).astype("<i2").tobytes())
    bed = str(tmp_path / "bed.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=1320:sample_rate=48000:duration=8",
                    "-ac", "2", "-c:a", "pcm_s16le", bed], check=True,
                   capture_output=True)
    return sp, bed


def _bed_gain_db(f32, sp, bed, a_s, b_s):
    import numpy as np

    def rd(p):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-f", "f32le",
                              "-ac", "2", "-ar", "48000", "-"],
                             capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)

    out = np.frombuffer(open(f32, "rb").read(), dtype=np.float32).reshape(-1, 2)
    s, b = rd(sp)[:len(out)], rd(bed)[:len(out)]
    i0, i1 = int(a_s * 48000), int(b_s * 48000)
    got = np.sqrt(((out - s)[i0:i1] ** 2).mean())
    ref = np.sqrt((b[i0:i1] ** 2).mean())
    return 20 * np.log10(got / ref)


def test_duck_mix_releases_after_the_last_word(tmp_path):
    sp, bed = _ending_noise_case(tmp_path)
    (tmp_path / "words.json").write_text(json.dumps(
        [{"text": "好", "start": 2.6, "end": 2.95}]))
    f32, _ = bk.duck_mix(sp, bed, str(tmp_path))
    assert _bed_gain_db(f32, sp, bed, 1.0, 2.5) < -5, "no longer ducks under speech"
    assert _bed_gain_db(f32, sp, bed, 4.0, 7.0) > -1, \
        "bed held down after the last word by room noise"


def test_duck_mix_speech_until_overrides_and_none_disables(tmp_path):
    sp, bed = _ending_noise_case(tmp_path)
    f32, _ = bk.duck_mix(sp, bed, str(tmp_path), speech_until=3.0)
    assert _bed_gain_db(f32, sp, bed, 4.0, 7.0) > -1
    f32, _ = bk.duck_mix(sp, bed, str(tmp_path), speech_until=None)
    assert _bed_gain_db(f32, sp, bed, 4.0, 7.0) < -3, \
        "None must keep the old envelope-only behaviour"


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


def test_caption_window_pads_after_the_words():
    """A finished build: a 1.2s quote held to the 1.8s floor opened 0.9s before the
    speaker, because the padding went in front (2026-10-21)."""
    assert bk.caption_window(5.53, 6.79) == (5.53, 7.33)


def test_caption_window_keeps_a_long_line_to_its_words():
    assert bk.caption_window(1.0, 4.0) == (1.0, 4.0)


def test_caption_window_borrows_only_the_allowed_lead_when_boxed_in():
    start, end = bk.caption_window(5.53, 6.79, next_start=6.9)
    assert end == 6.9
    assert 5.53 - start <= 0.3


def test_caption_window_never_cuts_the_last_word():
    assert bk.caption_window(5.53, 6.79, next_start=6.5)[1] == 6.79
