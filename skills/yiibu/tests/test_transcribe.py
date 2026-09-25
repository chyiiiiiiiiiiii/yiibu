"""Tests for the transcribe module."""
import sys
import types

import pytest

from modules import transcribe as transcribe_module
from modules.types import Word
from modules.transcribe import format_transcript_for_review


def test_format_transcript_flags_low_confidence():
    """Words below confidence threshold should be flagged with [?]."""
    words = [
        Word(text="今天", start=0.0, end=0.3, confidence=0.95),
        Word(text="的", start=0.3, end=0.4, confidence=0.90),
        Word(text="picolm", start=0.4, end=0.9, confidence=0.45),
        Word(text="很厲害", start=0.9, end=1.3, confidence=0.88),
    ]
    result = format_transcript_for_review(words, threshold=0.7)
    assert "[?" in result
    assert "picolm" in result
    assert "今天" in result
    # Low-confidence word should be highlighted
    assert "[? picolm (45%)]" in result


def test_format_transcript_all_high_confidence():
    """All high-confidence words should have no flags."""
    words = [
        Word(text="大家好", start=0.0, end=0.5, confidence=0.98),
        Word(text="我是", start=0.5, end=0.8, confidence=0.95),
    ]
    result = format_transcript_for_review(words, threshold=0.7)
    assert "[?" not in result


# ── ASR sanity: reasons a transcript must not be trusted ──────────────
# Both cases are real failures from the 2026-08-18 Dev Jam build. Neither was
# visible to any gate: the echoed prompt would have shipped as a quote the
# person never said, and the loop hung the batch for minutes on a 1.5s clip.
from modules.transcribe import asr_sanity  # noqa: E402

_PROMPT = "這是一場黑客松評審現場，主題是智慧城市，有學生團隊 demo 作品、評審提問與評分討論。"


def _words(text):
    return [Word(text=c, start=0.0, end=0.1, confidence=0.9) for c in text]


def test_asr_sanity_catches_the_prompt_echoed_back():
    echoed = "這場黑客松評審現場，有學生團隊 demo 作品、評審提問與評分討論。"
    reason = asr_sanity(_words(echoed), _PROMPT)
    assert reason and "echoed back" in reason


def test_asr_sanity_catches_a_decoder_loop():
    reason = asr_sanity(_words("謝謝大家" * 12), _PROMPT)
    assert reason and "looped" in reason


def test_asr_sanity_passes_real_speech():
    real = "你們有在做第二次的確認嗎確認說這些他給的資訊是正確的還是說他會有失誤"
    assert asr_sanity(_words(real), _PROMPT) is None


def test_asr_sanity_is_quiet_without_a_prompt():
    assert asr_sanity(_words("今天來當評審"), "") is None


def test_run_transcribe_rejects_untrusted_words_without_leaving_stale_output(
    tmp_path, monkeypatch,
):
    words_path = tmp_path / "words.json"
    words_path.write_text('[{"text": "old"}]', encoding="utf-8")
    monkeypatch.setattr(
        transcribe_module,
        "transcribe",
        lambda _video, _work: _words("謝謝大家" * 12),
    )

    with pytest.raises(RuntimeError, match="ASR sanity failed"):
        transcribe_module.run_transcribe("input.mov", str(tmp_path))

    assert not words_path.exists()
    backups = list(tmp_path.glob("words.previous-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '[{"text": "old"}]'


def test_run_transcribe_never_supplies_an_initial_prompt(tmp_path, monkeypatch):
    calls = []

    class FakeModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _audio, **kwargs):
            calls.append(kwargs)
            word = types.SimpleNamespace(
                word="今天", start=0.0, end=0.4, probability=0.95,
            )
            return [types.SimpleNamespace(words=[word])], object()

    fake_whisper = types.ModuleType("faster_whisper")
    fake_whisper.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_whisper)
    monkeypatch.setattr(transcribe_module.subprocess, "run", lambda *_a, **_kw: None)

    transcribe_module.run_transcribe("input.mov", str(tmp_path))

    assert "initial_prompt" not in calls[0]
