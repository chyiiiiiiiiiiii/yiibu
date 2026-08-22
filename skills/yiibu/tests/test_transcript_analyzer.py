"""Tests for transcript visual analysis module."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

from modules.types import VisualMoment
from modules.transcript_analyzer import (
    merge_with_script_items,
    apply_coverage_targets,
)


# ─── merge_with_script_items ─────────────────────────────────


def test_merge_script_items_win_in_overlap():
    """Script items should replace visual moments within ±2s overlap."""
    visual_moments = [
        VisualMoment(start=8.0, end=12.0, title="Flutter", category="product", source_type="screenshot"),
        VisualMoment(start=30.0, end=34.0, title="Rust", category="concept", source_type="stock_footage"),
    ]
    script_items = [
        {"title": "Flutter Official", "timing_hint": "[9s]", "duration": 4},
    ]
    result = merge_with_script_items(visual_moments, script_items)
    titles = [s["title"] for s in result]
    # Script item should replace the overlapping visual moment
    assert "Flutter Official" in titles
    # Non-overlapping visual moment should remain
    assert "Rust" in titles
    # Original Flutter visual moment should be removed (overlap)
    assert "Flutter" not in titles


def test_merge_no_script_items():
    """When no script items, all visual moments pass through."""
    visual_moments = [
        VisualMoment(start=5.0, end=9.0, title="AI Agent", category="concept", source_type="stock_footage", priority=1),
        VisualMoment(start=20.0, end=24.0, title="LLM", category="concept", source_type="stock_footage"),
    ]
    result = merge_with_script_items(visual_moments, [])
    assert len(result) == 2
    assert result[0]["title"] == "AI Agent"


def test_merge_deduplicates_same_title():
    """Visual moments with same title as script items should be removed."""
    visual_moments = [
        VisualMoment(start=10.0, end=14.0, title="Gemini", category="product", source_type="screenshot"),
    ]
    script_items = [
        {"title": "Gemini", "timing_hint": "[25s]", "duration": 4},
    ]
    result = merge_with_script_items(visual_moments, script_items)
    # Only the script version should remain
    titles = [s["title"] for s in result]
    assert titles.count("Gemini") == 1


# ─── apply_coverage_targets ──────────────────────────────────


def test_coverage_respects_opening_selfie():
    """Segments in the opening selfie zone should be removed."""
    segments = [
        {"start_hint": 1.0, "duration": 3, "title": "A", "priority": 2},
        {"start_hint": 10.0, "duration": 4, "title": "B", "priority": 1},
    ]
    result = apply_coverage_targets(segments, total_duration=60.0)
    # First segment at 1.0s should be removed (within BROLL_OPENING_SELFIE=2.5s)
    starts = [s["start_hint"] for s in result]
    assert 1.0 not in starts
    assert 10.0 in starts


def test_coverage_respects_closing_selfie():
    """Segments in the closing selfie zone should be removed."""
    segments = [
        {"start_hint": 10.0, "duration": 4, "title": "A", "priority": 1},
        {"start_hint": 57.0, "duration": 4, "title": "B", "priority": 2},
    ]
    result = apply_coverage_targets(segments, total_duration=60.0)
    # Second segment at 57s should be removed (within 4s of end)
    starts = [s["start_hint"] for s in result]
    assert 10.0 in starts
    assert 57.0 not in starts


def test_coverage_prunes_low_priority_when_over_target():
    """When coverage exceeds max target, lowest priority segments pruned first."""
    # 8 segments × 5s = 40s in 50s video = 80% > 70% max
    segments = [
        {"start_hint": 3.0 + i * 6, "duration": 5, "title": f"S{i}", "priority": i % 3 + 1}
        for i in range(8)
    ]
    result = apply_coverage_targets(segments, total_duration=50.0)
    total_broll = sum(s["duration"] for s in result)
    # Should be pruned to within 50-70% of 50s = 25-35s
    assert total_broll <= 50.0 * 0.70 + 1.0  # small tolerance


def test_coverage_empty_segments():
    """Empty segment list should return empty list."""
    result = apply_coverage_targets([], total_duration=60.0)
    assert result == []


def test_coverage_selfie_preferred_segments_removed():
    """Segments marked selfie_preferred should be filtered out."""
    segments = [
        {"start_hint": 10.0, "duration": 4, "title": "A", "priority": 1, "selfie_preferred": True},
        {"start_hint": 30.0, "duration": 4, "title": "B", "priority": 1, "selfie_preferred": False},
    ]
    result = apply_coverage_targets(segments, total_duration=60.0)
    titles = [s["title"] for s in result]
    assert "A" not in titles
    assert "B" in titles
