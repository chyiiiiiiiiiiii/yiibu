"""The Instagram profile grid shows only the middle 3:4 of a cover.

Reconstructs 2026-10-25: a cover passed every gate with the subject's head at
y~170 on a 1080x1920 frame. The grid crops to y 240-1680, so on the profile
page the head was gone and only the title was left. gate_cover now reads the
subject box cover.build() records in cover_meta.json and fails it outside the
crop or under the title.
"""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "modules")]

import cover  # noqa: E402
import gates  # noqa: E402
import positioning  # noqa: E402

W, H = 1080, 1920

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")


def _cover_and_video(tmp_path, **kw):
    src = tmp_path / "src.png"
    Image.new("RGB", (W, H), (40, 44, 52)).save(src)
    cover.build(str(src), "標題", "副標題", str(tmp_path / "cover.jpg"), **kw)
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i",
                    str(tmp_path / "cover.jpg"), "-t", "0.5", "-pix_fmt", "yuv420p",
                    str(video)], check=True, capture_output=True)
    return str(video), json.loads((tmp_path / "cover_meta.json").read_text())


def _crop_fails(fails):
    return [f for f in fails if "3:4 crop" in f or "title band" in f]


def test_the_grid_crop_is_the_middle_three_quarters():
    assert cover.grid_crop([3, 4], W, H) == (240, 1680)


@needs_ffmpeg
def test_a_face_at_y_170_fails(tmp_path):
    video, meta = _cover_and_video(tmp_path, subject_box=(390, 170, 690, 470))
    assert meta["subject_box"] == [390, 170, 690, 470]
    assert meta["subject_source"] == "declared"
    fails, det = gates.gate_cover(video, str(tmp_path))
    hit = _crop_fails(fails)
    assert hit and "above the profile grid" in hit[0], fails
    assert det["grid_crop_y"] == [240, 1680]


@needs_ffmpeg
def test_a_face_at_y_500_passes(tmp_path):
    video, _ = _cover_and_video(tmp_path, subject_box=(390, 500, 690, 800))
    fails, _ = gates.gate_cover(video, str(tmp_path))
    assert not _crop_fails(fails), fails


@needs_ffmpeg
def test_a_face_under_the_title_fails(tmp_path):
    video, meta = _cover_and_video(tmp_path, subject_box=(390, 900, 690, 1200))
    assert meta["title_top_px"] < 1200
    fails, _ = gates.gate_cover(video, str(tmp_path))
    assert any("title band" in f for f in _crop_fails(fails)), fails


@needs_ffmpeg
def test_no_detector_skips_cleanly_and_says_so(tmp_path, monkeypatch):
    """cv2 is optional: without it the cover still builds, and the gate says
    the crop went unchecked instead of reporting a pass it never measured."""
    monkeypatch.setattr(positioning, "cv2", None)
    video, meta = _cover_and_video(tmp_path)
    assert meta["subject_box"] is None and meta["subject_source"] == "none found"
    fails, det = gates.gate_cover(video, str(tmp_path))
    assert not _crop_fails(fails), fails
    assert "unchecked" in det["subject_box"]


def test_declaring_no_subject_skips_detection(tmp_path, monkeypatch):
    def boom(im):
        raise AssertionError("detector ran on a cover declared to have no subject")
    monkeypatch.setattr(cover, "detect_subject", boom)
    src = tmp_path / "src.png"
    Image.new("RGB", (W, H), (40, 44, 52)).save(src)
    cover.build(str(src), "標題", "副標題", str(tmp_path / "cover.jpg"), subject_box=False)
    meta = json.loads((tmp_path / "cover_meta.json").read_text())
    assert meta["subject_box"] is None and meta["subject_source"] == "declared none"


def test_review_draws_the_grid_tile(tmp_path):
    import review
    (tmp_path / "cover_meta.json").write_text(json.dumps({"subject_box": [390, 170, 690, 470]}))
    frame = Image.new("RGB", (300, 533), (200, 200, 200))
    from PIL import ImageFont
    tile = review.grid_tile(frame, str(tmp_path), ImageFont.load_default())
    assert tile.size == (300, 533 + 46)
    # the rows above the crop are blacked out, the middle is untouched
    assert tile.getpixel((150, 30)) == (0, 0, 0)
    assert tile.getpixel((150, 266)) == (200, 200, 200)
