"""Tests for BGM module."""
import pytest
from modules.bgm import BgmSegment, plan_bgm_segments, analyze_mood
from config import BGM_DEFAULT_MOOD


def test_bgm_segment_dataclass():
    """BgmSegment should store mood, source_path, start, duration."""
    seg = BgmSegment(mood="chill", source_path="/tmp/track.wav", start=0.0, duration=30.0)
    assert seg.mood == "chill"
    assert seg.source_path == "/tmp/track.wav"
    assert seg.start == 0.0
    assert seg.duration == 30.0


def test_plan_bgm_segments_manual():
    """Manual BGM should produce a single segment covering full duration."""
    segments = plan_bgm_segments(
        manual_bgm="/tmp/my_song.mp3",
        moods=["chill"],
        total_duration=60.0,
    )
    assert len(segments) == 1
    assert segments[0].mood == "manual"
    assert segments[0].source_path == "/tmp/my_song.mp3"
    assert segments[0].start == 0.0
    assert segments[0].duration == 60.0


def test_plan_bgm_segments_single_mood():
    """Single mood should produce one segment."""
    segments = plan_bgm_segments(
        manual_bgm=None,
        moods=["energetic"],
        total_duration=30.0,
    )
    assert len(segments) == 1
    assert segments[0].mood == "energetic"
    assert segments[0].start == 0.0
    assert segments[0].duration == 30.0


def test_plan_bgm_segments_multi_mood():
    """Multiple moods should produce evenly distributed segments."""
    segments = plan_bgm_segments(
        manual_bgm=None,
        moods=["chill", "dramatic", "inspiring"],
        total_duration=90.0,
    )
    assert len(segments) == 3
    assert segments[0].mood == "chill"
    assert segments[0].start == 0.0
    assert segments[0].duration == 30.0
    assert segments[1].mood == "dramatic"
    assert segments[1].start == 30.0
    assert segments[1].duration == 30.0
    assert segments[2].mood == "inspiring"
    assert segments[2].start == 60.0
    assert segments[2].duration == 30.0


def test_plan_bgm_segments_empty_moods_fallback():
    """Empty moods list should fall back to default mood."""
    segments = plan_bgm_segments(
        manual_bgm=None,
        moods=[],
        total_duration=20.0,
    )
    assert len(segments) == 1
    assert segments[0].mood == BGM_DEFAULT_MOOD


def test_analyze_mood_empty_transcript():
    """Empty transcript should return default mood."""
    result = analyze_mood("")
    assert result == [BGM_DEFAULT_MOOD]


def test_analyze_mood_none_transcript():
    """None transcript should return default mood."""
    result = analyze_mood(None)
    assert result == [BGM_DEFAULT_MOOD]


# ── audible end: a music bed that runs out plays the closing card in silence ──

def _make_track(path, tone_s, silence_s):
    """tone_s of sound followed by silence_s of digital silence."""
    import subprocess
    subprocess.run(
        ["ffmpeg", "-v", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone_s}",
         "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={silence_s}",
         "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
         "-map", "[a]", "-y", str(path)],
        check=True, capture_output=True)
    return str(path)


def test_measure_audible_end_ignores_trailing_silence(tmp_path):
    """The audible end is where the sound stops, not where the file stops.

    A track whose last 2s are silence has 3s of usable music; treating the file
    length as usable is what left a closing card with no audio.
    """
    from modules.bgm import measure_audible_end
    track = _make_track(tmp_path / "t.wav", tone_s=3.0, silence_s=2.0)
    assert measure_audible_end(track) == pytest.approx(3.0, abs=0.3)


def test_measure_audible_end_of_a_fully_audible_track(tmp_path):
    """No trailing silence — the audible end is the file's own length."""
    from modules.bgm import measure_audible_end
    track = _make_track(tmp_path / "t2.wav", tone_s=4.0, silence_s=0.0)
    assert measure_audible_end(track) == pytest.approx(4.0, abs=0.3)


# ── tail fade: derived from the closing shot, never a constant ────────────────

def test_tail_fade_is_half_the_closing_shot():
    """A 2s closing card must not be swallowed by a 3s fade.

    The fade was a constant chosen when the closing shot was 4.2s. The shot later
    shrank to 2.0s and the fade ate the entire payoff card — twice.
    """
    from modules.bgm import derive_tail_fade
    assert derive_tail_fade(2.0) == pytest.approx(1.0)
    assert derive_tail_fade(0.8) == pytest.approx(0.4)


def test_tail_fade_is_capped_for_long_closing_shots():
    """A long closing shot does not earn an equally long fade."""
    from modules.bgm import derive_tail_fade
    assert derive_tail_fade(4.2) == pytest.approx(1.0)
    assert derive_tail_fade(30.0) == pytest.approx(1.0)


def test_tail_fade_never_exceeds_the_closing_shot():
    """Invariant: the fade can never be longer than the shot it fades under."""
    from modules.bgm import derive_tail_fade
    for closing in (0.1, 0.5, 1.0, 2.0, 5.0, 12.0):
        assert derive_tail_fade(closing) <= closing


# ── ducking: the bed must survive to the end of the speech ────────────────────
#
# Regression for the defect in references/delivery-traps.md #4b: the music was
# gone for the last seconds of a delivery while every intermediate file looked
# healthy. sidechaincompress could stop passing the bed entirely; a compressor
# that only ever ATTENUATES cannot.

def _tone(path, dur, freq=440, amp=0.2, sr=48000, gate_after=None):
    import subprocess
    expr = f"sin(2*PI*{freq}*t)*{amp}"
    if gate_after is not None:
        expr += rf"*lt(t\,{gate_after})"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", f"aevalsrc={expr}:s={sr}:d={dur}",
         "-ac", "2", "-c:a", "pcm_s16le", "-y", str(path)],
        check=True, capture_output=True)
    return str(path)


def test_duck_gain_only_attenuates_and_never_reaches_zero():
    """Gain is bounded in (0, 1]: a duck may quieten the bed, never mute it."""
    import numpy as np
    from modules.bgm import duck_gain
    sr = 48000
    loud = np.ones((sr * 2, 2), dtype=np.float32) * 0.9      # relentless speech
    g = duck_gain(loud, sr=sr)
    assert g.shape == (sr * 2,)
    assert g.max() <= 1.0 + 1e-6
    assert g.min() > 0.0, "the bed was muted outright, not ducked"


def test_duck_gain_recovers_after_the_key_stops():
    """When speech stops the bed comes back — the tail is where it went missing."""
    import numpy as np
    from modules.bgm import duck_gain
    sr = 48000
    key = np.zeros((sr * 4, 2), dtype=np.float32)
    key[: sr * 2] = 0.9                                       # loud, then silent
    g = duck_gain(key, sr=sr, release_ms=200)
    assert g[sr] < 0.9, "no ducking happened while the key was loud"
    assert g[-1] > 0.9, f"bed never recovered after the key stopped (g={g[-1]:.3f})"


def test_ducked_bed_is_the_length_of_the_speech_even_if_the_track_is_short(tmp_path):
    """A short track loops. Running short is how music vanishes from the ending."""
    from modules.bgm import apply_ducking, _decode_f32
    speech = _tone(tmp_path / "speech.wav", 6.0, freq=220)
    bgm = _tone(tmp_path / "bgm.wav", 2.0, freq=880)          # shorter than speech
    out = apply_ducking(bgm, speech, str(tmp_path))
    assert len(_decode_f32(out)) == pytest.approx(len(_decode_f32(speech)), abs=2400)


def test_ducked_bed_is_still_audible_under_the_last_of_the_speech(tmp_path):
    """The exact shipped defect: bed present early, gone at the end."""
    import numpy as np
    from modules.bgm import apply_ducking, _decode_f32
    speech = _tone(tmp_path / "s.wav", 6.0, freq=220, amp=0.3)
    bgm = _tone(tmp_path / "b.wav", 6.0, freq=880, amp=0.3)
    out = apply_ducking(bgm, speech, str(tmp_path))
    bed = _decode_f32(out)
    sr = 48000
    tail = bed[-sr:]                                          # final second
    rms = float(np.sqrt((tail ** 2).mean()))
    assert 20 * np.log10(max(rms, 1e-9)) > -40, "bed is silent under the ending"
