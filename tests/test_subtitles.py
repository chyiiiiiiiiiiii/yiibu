import pytest
"""Tests for subtitles module — keyword matching, ASS time, karaoke generation."""
from modules.subtitles import (
    is_keyword, format_ass_time,
    _split_phrase_into_chunks, _parse_emphasis_indices, _build_emphasis_events,
    _build_word_id_map,
)
from modules.positioning import calculate_subtitle_position
from modules.types import Word
from config import FONT_SIZE_EMPHASIS, OUTPUT_HEIGHT
import re as _re


def test_is_keyword_exact_match():
    keywords = ["Rust", "Claude Code", "picolm"]
    assert is_keyword("Rust", keywords) is True
    assert is_keyword("rust", keywords) is True  # case-insensitive
    assert is_keyword("Python", keywords) is False


def test_is_keyword_partial_match():
    """ASR might output 'Claude' separately from 'Code'."""
    keywords = ["Claude Code", "SWE-Bench"]
    assert is_keyword("Claude", keywords) is True
    assert is_keyword("SWE", keywords) is True


def test_format_ass_time():
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(65.5) == "0:01:05.50"
    assert format_ass_time(3723.12) == "1:02:03.12"


@pytest.mark.xfail(reason="stale: generate_karaoke_line was removed from modules/subtitles.py; test never imported it. Rewrite against the current API or delete.", raises=NameError, strict=True)
def test_generate_karaoke_line_basic():
    """Karaoke line should contain \\k tags for timing."""
    words = [
        Word(text="大家", start=0.0, end=0.3, confidence=0.95),
        Word(text="好", start=0.3, end=0.5, confidence=0.90),
    ]
    line = generate_karaoke_line(words, keywords=[], style="Default")
    assert "\\k" in line
    assert "大家" in line
    assert "好" in line


@pytest.mark.xfail(reason="stale: generate_karaoke_line was removed from modules/subtitles.py; test never imported it. Rewrite against the current API or delete.", raises=NameError, strict=True)
def test_generate_karaoke_line_keyword_styling():
    """Keywords should use gold color override."""
    words = [
        Word(text="用", start=0.0, end=0.2, confidence=0.95),
        Word(text="Rust", start=0.2, end=0.5, confidence=0.90),
        Word(text="重寫", start=0.5, end=0.8, confidence=0.88),
    ]
    line = generate_karaoke_line(words, keywords=["Rust"], style="Default")
    # Rust should have keyword color override (gold = &H0000D7FF)
    assert "\\c&H0000D7FF" in line


# ─── Emphasis captions ───────────────────────────────────────

def test_split_phrase_into_chunks_at_punctuation():
    """A phrase with an internal clause break splits into two chunks there."""
    phrase = [
        Word(text="勇敢的", start=0.0, end=0.4, confidence=0.9),
        Word(text="，", start=0.4, end=0.4, confidence=0.9),
        Word(text="去做你自己", start=0.5, end=1.2, confidence=0.9),
    ]
    chunks = _split_phrase_into_chunks(phrase)
    assert len(chunks) == 2
    assert "".join(w.text for w in chunks[0]).startswith("勇敢的")
    assert "".join(w.text for w in chunks[1]) == "去做你自己"


def test_split_phrase_into_chunks_at_pause():
    """No punctuation → split at the largest inter-word gap."""
    phrase = [
        Word(text="這", start=0.0, end=0.2, confidence=0.9),
        Word(text="很重要", start=0.2, end=0.6, confidence=0.9),
        Word(text="真的", start=1.2, end=1.6, confidence=0.9),  # 0.6s gap before this
    ]
    chunks = _split_phrase_into_chunks(phrase)
    assert len(chunks) == 2
    assert "".join(w.text for w in chunks[1]) == "真的"


def test_split_phrase_single_chunk_when_short():
    """A tiny phrase stays a single chunk (nothing to stagger)."""
    phrase = [Word(text="哇", start=0.0, end=0.3, confidence=0.9)]
    chunks = _split_phrase_into_chunks(phrase)
    assert len(chunks) == 1


def test_parse_emphasis_indices_filters_and_caps():
    """Parser keeps only eligible (short) indices and honours the cap."""
    eligible = {0, 2, 4}
    out = "0, 1, 2, 4"  # 1 is not eligible → dropped
    got = _parse_emphasis_indices(out, eligible, max_moments=2)
    assert got == {0, 2}  # first two eligible, cap 2


def test_parse_emphasis_indices_bad_output_is_empty():
    """Unparseable LLM output fails safe to no emphasis."""
    assert _parse_emphasis_indices("no numbers here", {0, 1}, 6) == set()


def test_build_emphasis_events_big_staggered_bilingual():
    """A two-chunk emphasis phrase yields two big, positioned events with English."""
    phrase = [
        Word(text="勇敢的", start=0.0, end=0.4, confidence=0.9),
        Word(text="去做你自己", start=0.5, end=1.2, confidence=0.9),
    ]
    word_id_map = _build_word_id_map(phrase)
    lines = _build_emphasis_events(
        phrase, ["brave", "just be yourself"],
        word_id_map, kw_indices=set(), keywords=[], phrase_end=1.2, align=2,
    )
    assert len(lines) == 2
    joined = "\n".join(lines)
    assert f"\\fs{FONT_SIZE_EMPHASIS}" in joined      # enlarged
    assert "\\pos(" in joined                          # explicitly positioned
    assert "勇敢的" in joined and "去做你自己" in joined
    assert "brave" in joined and "just be yourself" in joined
    # Second chunk starts when it is spoken, not at phrase start
    assert "0:00:00.50" in joined


def _pos_ys(lines):
    """Extract every \\pos(x,y) y-coordinate from emphasis Dialogue lines."""
    ys = []
    for ln in lines:
        for m in _re.finditer(r"\\pos\(\d+,(\d+)\)", ln):
            ys.append(int(m.group(1)))
    return ys


def test_emphasis_text_never_covers_the_face():
    """Face-aware invariant: with a detected face, no emphasis chunk may sit in
    the face's vertical extent — it must live in the face-free band."""
    face_box = (400, 300, 280, 350)          # face occupies y 300..650
    pos = calculate_subtitle_position(face_box, 1080, OUTPUT_HEIGHT)
    band = (pos["clear_top"] * OUTPUT_HEIGHT, pos["clear_bottom"] * OUTPUT_HEIGHT)
    phrase = [
        Word(text="勇敢的", start=0.0, end=0.4, confidence=0.9),
        Word(text="去做你自己", start=0.5, end=1.2, confidence=0.9),
    ]
    word_id_map = _build_word_id_map(phrase)
    lines = _build_emphasis_events(
        phrase, ["brave", "just be yourself"],
        word_id_map, kw_indices=set(), keywords=[], phrase_end=1.2, align=2, band=band,
    )
    face_bottom_px = 300 + 350
    for y in _pos_ys(lines):
        # anchor minus a generous half-line must clear the face bottom
        assert y - FONT_SIZE_EMPHASIS > face_bottom_px, f"chunk y={y} overlaps face"
        assert y <= OUTPUT_HEIGHT, f"chunk y={y} off-screen"


def test_emphasis_block_stays_on_screen():
    """Even a tall stack in a shallow band is clamped on-screen (no clipping)."""
    band = (0.72 * OUTPUT_HEIGHT, 0.98 * OUTPUT_HEIGHT)  # face-fills-frame case
    phrase = [
        Word(text="這是一句", start=0.0, end=0.5, confidence=0.9),
        Word(text="很長的金句", start=0.9, end=1.6, confidence=0.9),
    ]
    word_id_map = _build_word_id_map(phrase)
    lines = _build_emphasis_events(
        phrase, ["a", "b"], word_id_map, set(), [], 1.6, 2, band=band,
    )
    for y in _pos_ys(lines):
        assert 0 < y < OUTPUT_HEIGHT
        # the English line beneath the lowest chunk must not run off the bottom
        assert y + 120 < OUTPUT_HEIGHT
