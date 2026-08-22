"""Tests for compose module — transitions, Ken Burns, hardware encoding."""
from modules.compose import (
    _get_transition_for_segment,
    _get_kenburns_direction,
    _build_kenburns_zoompan,
)


def test_transition_rotation():
    """Transition type should cycle through BROLL_TRANSITION_TYPES."""
    # Default config: ["fade", "zoom_in", "slide_left", "slide_up"]
    assert _get_transition_for_segment(0) == "fade"
    assert _get_transition_for_segment(1) == "zoom_in"
    assert _get_transition_for_segment(2) == "slide_left"
    assert _get_transition_for_segment(3) == "slide_up"
    # Cycle repeats
    assert _get_transition_for_segment(4) == "fade"
    assert _get_transition_for_segment(7) == "slide_up"


def test_transition_deterministic():
    """Same index should always return same transition."""
    for i in range(10):
        assert _get_transition_for_segment(i) == _get_transition_for_segment(i)


def test_kenburns_direction_rotation():
    """Ken Burns direction should cycle through BROLL_KENBURNS_DIRECTIONS."""
    # Default: ["zoom_in_center", "zoom_out_center", "pan_left", "pan_right"]
    assert _get_kenburns_direction(0) == "zoom_in_center"
    assert _get_kenburns_direction(1) == "zoom_out_center"
    assert _get_kenburns_direction(2) == "pan_left"
    assert _get_kenburns_direction(3) == "pan_right"
    assert _get_kenburns_direction(4) == "zoom_in_center"


def test_kenburns_zoompan_contains_required_params():
    """zoompan filter string should contain z, x, y, d, s, fps parameters."""
    result = _build_kenburns_zoompan("zoom_in_center", dur=4.0, width=1080, height=1920)
    assert "zoompan=" in result
    assert "z=" in result
    assert "x=" in result
    assert "y=" in result
    assert "d=" in result
    assert "s=1080x1920" in result
    assert "fps=" in result


def test_kenburns_zoompan_dur_frames():
    """Duration in frames should match dur * fps."""
    result = _build_kenburns_zoompan("zoom_in_center", dur=4.0, width=1080, height=1920)
    # 4.0s * 30fps = 120 frames
    assert "d=120" in result


def test_kenburns_all_directions_valid():
    """All 4 Ken Burns directions should produce valid filter strings."""
    for direction in ["zoom_in_center", "zoom_out_center", "pan_left", "pan_right"]:
        result = _build_kenburns_zoompan(direction, dur=3.0, width=1080, height=1920)
        assert "zoompan=" in result
        assert len(result) > 20  # Not empty/trivial


def test_kenburns_min_one_frame():
    """Very short duration should produce at least 1 frame."""
    result = _build_kenburns_zoompan("zoom_in_center", dur=0.001, width=1080, height=1920)
    assert "d=1" in result or "d=0" not in result
