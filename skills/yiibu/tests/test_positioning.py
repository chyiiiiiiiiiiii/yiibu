"""Tests for positioning module — subtitle placement based on face detection."""
from unittest.mock import patch, MagicMock
import numpy as np
from modules.positioning import calculate_subtitle_position, detect_face, detect_face_mediapipe


def test_face_top_half_puts_subs_bottom():
    """When face is in top area, subtitles go to bottom."""
    face_box = (400, 200, 280, 350)  # x, y, w, h — face in upper area
    frame_w, frame_h = 1080, 1920
    pos = calculate_subtitle_position(face_box, frame_w, frame_h)
    assert pos["y_ratio"] > 0.5
    assert pos["alignment"] == 2  # ASS bottom-center


def test_face_bottom_half_puts_subs_top():
    """When face is in bottom area, subtitles go to top."""
    face_box = (400, 1500, 280, 350)  # face very low
    frame_w, frame_h = 1080, 1920
    pos = calculate_subtitle_position(face_box, frame_w, frame_h)
    assert pos["y_ratio"] < 0.5
    assert pos["alignment"] == 8  # ASS top-center


def test_no_face_defaults_to_bottom():
    """When no face detected, default to bottom."""
    pos = calculate_subtitle_position(None, 1080, 1920)
    assert pos["y_ratio"] > 0.8
    assert pos["alignment"] == 2


def test_face_covers_frame_fallback():
    """When face covers most of the frame, fallback to bottom with small margin."""
    # Face spans nearly the entire frame height
    face_box = (100, 50, 800, 1800)
    pos = calculate_subtitle_position(face_box, 1080, 1920)
    assert pos["alignment"] == 2
    assert pos["y_ratio"] >= 0.85


def test_no_overlap_guarantee():
    """Subtitle zone should not overlap with face zone (with padding)."""
    face_box = (400, 400, 280, 500)  # face center ~ y=650
    frame_h = 1920
    pos = calculate_subtitle_position(face_box, 1080, frame_h)

    # Face extent with padding
    face_top_ratio = 400 / frame_h
    face_bottom_ratio = 900 / frame_h
    padding = 0.15
    padded_top = max(0.0, face_top_ratio - padding)
    padded_bottom = min(1.0, face_bottom_ratio + padding)

    # Subtitle y_ratio should be outside the padded face zone
    assert pos["y_ratio"] < padded_top or pos["y_ratio"] > padded_bottom


def test_y_ratio_range():
    """y_ratio should always be between 0 and 1."""
    test_cases = [
        None,
        (0, 0, 100, 100),         # face at top-left corner
        (0, 1800, 100, 120),      # face at very bottom
        (400, 960, 280, 350),     # face in center
    ]
    for face in test_cases:
        pos = calculate_subtitle_position(face, 1080, 1920)
        assert 0.0 <= pos["y_ratio"] <= 1.0, f"y_ratio out of range for face={face}"


def test_no_pixel_keys():
    """Return dict should not contain legacy pixel keys 'x' or 'y'."""
    pos = calculate_subtitle_position(None, 1080, 1920)
    assert "x" not in pos
    assert "y" not in pos
    assert "y_ratio" in pos
    assert "alignment" in pos


# ─── MediaPipe face detection tests ──────────────────────────


def test_mediapipe_returns_none_when_not_installed():
    """detect_face_mediapipe should return None if mediapipe not installed."""
    # Create a dummy frame
    frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    with patch.dict("sys.modules", {"mediapipe": None}):
        result = detect_face_mediapipe(frame)
    # Should gracefully return None (ImportError caught)
    assert result is None


def test_detect_face_falls_back_to_haar():
    """detect_face should fall back to Haar when MediaPipe returns None."""
    frame = np.zeros((1920, 1080, 3), dtype=np.uint8)

    with patch("modules.positioning.detect_face_mediapipe", return_value=None), \
         patch("modules.positioning.detect_face_haar", return_value=(100, 200, 300, 400)):
        result = detect_face(frame)

    assert result == (100, 200, 300, 400)


def test_detect_face_mediapipe_takes_priority():
    """detect_face should use MediaPipe result when available."""
    frame = np.zeros((1920, 1080, 3), dtype=np.uint8)

    with patch("modules.positioning.detect_face_mediapipe", return_value=(50, 100, 200, 250)), \
         patch("modules.positioning.detect_face_haar") as mock_haar:
        result = detect_face(frame)

    assert result == (50, 100, 200, 250)
    # Haar should not be called when MediaPipe succeeds
    mock_haar.assert_not_called()


# ─── Face-free band (for emphasis hero captions) ─────────────

def test_position_exposes_clear_band_below_face():
    """A face in the upper area yields a clear band spanning below the face to
    the bottom edge — the safe zone big emphasis text must live in."""
    face_box = (400, 300, 280, 350)  # face occupies y 300..650 of 1920
    pos = calculate_subtitle_position(face_box, 1080, 1920)
    assert "clear_top" in pos and "clear_bottom" in pos
    face_bottom_ratio = (300 + 350) / 1920
    assert pos["clear_top"] >= face_bottom_ratio   # band starts at/after face bottom
    assert pos["clear_bottom"] <= 1.0
    assert pos["clear_bottom"] - pos["clear_top"] > 0.1


def test_position_clear_band_avoids_face_when_above():
    """Face low → clear band is above the face, never overlapping it."""
    face_box = (400, 1400, 280, 400)  # face occupies y 1400..1800
    pos = calculate_subtitle_position(face_box, 1080, 1920)
    face_top_ratio = 1400 / 1920
    assert pos["clear_bottom"] <= face_top_ratio   # band ends at/before face top


def test_position_no_face_has_lower_band():
    pos = calculate_subtitle_position(None, 1080, 1920)
    assert pos["clear_top"] < pos["clear_bottom"] <= 1.0
