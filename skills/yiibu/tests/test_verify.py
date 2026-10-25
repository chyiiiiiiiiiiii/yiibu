"""Tests for verify.py — cut-boundary pop check, and the advisory checks
that must agree with house_style.json instead of warning on a green build."""
import json
import os
import shutil
import subprocess

import pytest

from verify import check_audio, check_cut_boundaries, check_subtitles
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


# ── Subtitles: the gold the house actually uses ──────────────────────────────

def _ass(work, *texts):
    rows = [f"Dialogue: 0,0:00:{i * 3:02d}.00,0:00:{i * 3 + 2:02d}.00,Speech,,0,0,0,,{t}"
            for i, t in enumerate(texts)]
    (work / "subtitles.ass").write_text(
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _keyword_issues(result):
    return [i for i in result["issues"] if "keyword" in i.lower()]


def test_subtitles_counts_house_gold_in_either_tag_form(tmp_path):
    r"""2026-10-14, a template build: five gold spans written as
    `{\fs90\c&H66DBF6&}`, gates.py exit 0 on every run, and verify.py said
    "No keyword highlights found" because it grepped for `\1c&H0000D7FF`, a
    gold the house dropped. The first line is copied from that build."""
    _ass(tmp_path,
         r"{\an5\pos(540,1344)}今天{\fs90\c&H66DBF6&}六分速{\fs84\c&HFFFFFF&}起跑",
         r"{\an5\pos(540,1344)}{\fs90\1c&H66DBF6&}1.5K{\fs84\1c&HFFFFFF&}")

    result = check_subtitles(str(tmp_path))
    assert result["details"]["keyword_highlights"] == 2
    assert not _keyword_issues(result), result["issues"]


def test_subtitles_still_warns_on_an_all_white_pass(tmp_path):
    """The defect the check exists for (2026-08-17, no gold at all) must still
    warn — and the retired #FFD700 gold is not the house gold."""
    _ass(tmp_path, "今天六分速起跑", r"全新的 {\1c&H0000D7FF&}LiteRT")

    result = check_subtitles(str(tmp_path))
    assert result["details"]["keyword_highlights"] == 0
    assert _keyword_issues(result)


def test_subtitles_reads_gold_from_the_project_override(tmp_path):
    """Same loader as gates.py, so WORK_DIR/house_style.local.json wins."""
    (tmp_path / "house_style.local.json").write_text(
        json.dumps({"captions": {"keyword": {"colour": "&H00FF00"}}}))
    _ass(tmp_path, r"今天{\c&H00FF00&}六分速{\c&HFFFFFF&}起跑")

    result = check_subtitles(str(tmp_path))
    assert result["details"]["keyword_highlights"] == 1
    assert not _keyword_issues(result), result["issues"]


# ── Audio: template builds leave no postprod mix behind ──────────────────────

def _template_work(tmp_path):
    work = tmp_path / "build"
    work.mkdir()
    (work / "timeline.json").write_text(json.dumps({"segments": []}))
    return work


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_audio_measures_the_output_on_a_template_build(tmp_path):
    """2026-10-14, a template build: a template build mixes inside its build
    script, writes no bgm_mixed*.wav / voice_only.wav, and verify.py reported
    "No audio file found" beside a gates.py exit 0. The mix is in the file
    that was delivered; measure that."""
    work = _template_work(tmp_path)
    final = tmp_path / "final.mp4"
    _tone(str(final), 3.0)

    result = check_audio(str(work), str(final))
    assert result["pass"], result["issues"]
    assert result["details"]["audio_file"] == "final.mp4"
    assert "rms_db" in result["details"]


def test_audio_is_not_applicable_on_a_template_build_without_output(tmp_path):
    result = check_audio(str(_template_work(tmp_path)))
    assert result["pass"], result["issues"]
    assert "template" in result["details"]["note"]


def test_audio_still_warns_when_a_postprod_mix_is_missing(tmp_path):
    """Postprod always writes its mix; there, a missing file means something."""
    result = check_audio(str(tmp_path))
    assert not result["pass"]
    assert result["issues"] == ["No audio file found"]
