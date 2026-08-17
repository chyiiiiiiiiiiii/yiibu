"""Tests for verify.py — cut-boundary pop check."""
import json
import os
import shutil
import subprocess

import pytest

from verify import check_cut_boundaries
from modules.silence_cut import render_faded_cut


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _tone(path: str, duration: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s=320x240:r=30:d={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}:sample_rate=44100",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", path],
        check=True, capture_output=True,
    )


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_check_cut_boundaries_passes_when_faded(tmp_path):
    """A properly faded splice at a listed boundary passes."""
    work = tmp_path
    src = str(work / "src.mp4")
    _tone(src, 3.0)
    render_faded_cut(src, [(0.0, 1.0), (2.0, 3.0)], str(work / "trimmed.mp4"), fade_ms=30)
    (work / "boundaries.json").write_text(json.dumps({"boundaries": [1.0]}))

    result = check_cut_boundaries(str(work))
    assert result["pass"], result["issues"]


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_check_cut_boundaries_flags_unfaded_pop(tmp_path):
    """A listed boundary with no fade (constant amplitude across it) is flagged."""
    work = tmp_path
    # Continuous tone — no dip anywhere — but we claim a boundary at t=1.0.
    _tone(str(work / "trimmed.mp4"), 2.0)
    (work / "boundaries.json").write_text(json.dumps({"boundaries": [1.0]}))

    result = check_cut_boundaries(str(work))
    assert not result["pass"]
    assert result["issues"]


def test_check_cut_boundaries_no_file_is_pass(tmp_path):
    """No boundaries.json -> nothing to check, passes."""
    result = check_cut_boundaries(str(tmp_path))
    assert result["pass"]
