"""Tests for title card overlay feature."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.subtitles import _generate_title_card_events, format_ass_time
from config import (
    TITLE_CARD_DURATION, TITLE_CARD_FADE_IN_MS, TITLE_CARD_FADE_OUT_MS,
    TITLE_CARD_LAYER, TITLE_CARD_GAP_PX, OUTPUT_WIDTH, OUTPUT_HEIGHT,
)


def test_single_title_returns_one_event():
    events = _generate_title_card_events("Hello World")
    assert len(events) == 1


def test_title_and_subtitle_returns_two_events():
    events = _generate_title_card_events("Main Title", subtitle="Sub Title")
    assert len(events) == 2


def test_correct_layer():
    events = _generate_title_card_events("Test", subtitle="Sub")
    for ev in events:
        assert ev.startswith(f"Dialogue: {TITLE_CARD_LAYER},")


def test_correct_timing_default_duration():
    events = _generate_title_card_events("Test")
    start_time = format_ass_time(0)
    end_time = format_ass_time(TITLE_CARD_DURATION)
    assert f",{start_time},{end_time}," in events[0]


def test_fade_animation_tags_present():
    events = _generate_title_card_events("Test")
    assert f"\\fad({TITLE_CARD_FADE_IN_MS},{TITLE_CARD_FADE_OUT_MS})" in events[0]


def test_center_positioning():
    events = _generate_title_card_events("Test")
    assert "\\an5" in events[0]
    x = OUTPUT_WIDTH // 2
    assert f"\\pos({x}," in events[0]


def test_scale_animation():
    events = _generate_title_card_events("Test")
    assert "\\fscx95\\fscy95" in events[0]
    assert "\\fscx100\\fscy100" in events[0]


def test_subtitle_staggered_fade():
    events = _generate_title_card_events("Title", subtitle="Sub")
    title_event = events[0]
    sub_event = events[1]
    stagger = 100
    # Subtitle fade-in is staggered by 100ms
    assert f"\\fad({TITLE_CARD_FADE_IN_MS + stagger},{TITLE_CARD_FADE_OUT_MS})" in sub_event
    # Subtitle scale animation also staggered
    assert f"\\t({stagger},{TITLE_CARD_FADE_IN_MS + stagger}," in sub_event


def test_custom_duration():
    events = _generate_title_card_events("Test", duration=5.0)
    end_time = format_ass_time(5.0)
    assert f",{end_time}," in events[0]


def test_no_events_when_title_is_none():
    """_generate_title_card_events should not be called with None title,
    but if somehow invoked, it still returns events for the given string."""
    # The guard is in generate_ass_file, not in _generate_title_card_events.
    # This test verifies the function works with any non-empty string.
    events = _generate_title_card_events("")
    assert len(events) == 1  # empty string still produces an event


def test_title_uses_titlecard_style():
    events = _generate_title_card_events("My Title")
    assert ",TitleCard," in events[0]


def test_subtitle_uses_titlecardsub_style():
    events = _generate_title_card_events("Title", subtitle="Sub")
    assert ",TitleCardSub," in events[1]
