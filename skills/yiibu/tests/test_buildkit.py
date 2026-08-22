"""Smoke tests for buildkit — each primitive on tiny synthetic media.

These run real ffmpeg with h264_videotoolbox, so they are macOS-only by
design: buildkit exists to lock THIS machine's fast path.
"""
import os
import subprocess
import sys

import pytest

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

import buildkit as bk  # noqa: E402


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


def test_prep_segment_asserts_length(clip, tmp_path):
    out = str(tmp_path / "seg.mov")
    bk.prep_segment(clip, 0.5, 2.5, out)
    assert abs(bk.dur(out) - 2.0) < 0.1


def test_concat_asserts_total(clip, tmp_path):
    a = bk.prep_segment(clip, 0.0, 1.5, str(tmp_path / "a.mov"))
    b = bk.prep_segment(clip, 2.0, 3.5, str(tmp_path / "b.mov"))
    out = bk.concat([a, b], str(tmp_path / "cat.mov"))
    assert abs(bk.dur(out) - 3.0) < 0.15


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
                        "-frames:v", "1", f], check=True, capture_output=True)
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
