"""Speech-to-text with word-level timestamps using faster-whisper."""
import os
import subprocess
from typing import List

from config import WHISPER_MODEL, WHISPER_LANGUAGE, WHISPER_INITIAL_PROMPT, CONFIDENCE_THRESHOLD
from modules.types import Word, save_words


def _convert_to_traditional(words: List[Word]) -> List[Word]:
    """Convert simplified Chinese characters to traditional in word texts."""
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
        for w in words:
            w.text = cc.convert(w.text)
        return words
    except ImportError:
        print("  Warning: opencc not installed, skipping 简→繁 conversion")
        return words


def format_transcript_for_review(
    words: List[Word],
    threshold: float = CONFIDENCE_THRESHOLD,
) -> str:
    """Format transcript for human review. Flag low-confidence words."""
    lines = []
    current_line = []
    current_start = 0.0

    for w in words:
        if w.confidence < threshold:
            token = f"[? {w.text} ({int(w.confidence * 100)}%)]"
        else:
            token = w.text
        current_line.append(token)

        # Line break every ~10 words for readability
        if len(current_line) >= 10:
            ts = f"[{current_start:.1f}s]"
            lines.append(f"{ts} {''.join(current_line)}")
            current_line = []
            current_start = w.end

    if current_line:
        ts = f"[{current_start:.1f}s]"
        lines.append(f"{ts} {''.join(current_line)}")

    return "\n".join(lines)


def transcribe(video_path: str, work_dir: str) -> List[Word]:
    """Transcribe video using faster-whisper. Returns word-level data."""
    from faster_whisper import WhisperModel

    os.makedirs(work_dir, exist_ok=True)
    audio_path = os.path.join(work_dir, "audio_16k.wav")

    # Extract 16kHz mono audio
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_path,
        ],
        check=True, capture_output=True,
    )

    # Load model and transcribe
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        audio_path,
        language=WHISPER_LANGUAGE,
        word_timestamps=True,
        vad_filter=True,
        # Stops the runaway repeat loop: on near-silent audio large-v3 will
        # otherwise re-feed its own output and never terminate. Observed
        # 2026-08-18 hanging >4 minutes on a 1.5s clip.
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        initial_prompt=WHISPER_INITIAL_PROMPT,
    )

    words = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append(Word(
                    text=w.word.strip(),
                    start=w.start,
                    end=w.end,
                    confidence=w.probability,
                ))

    bad = asr_sanity(words, WHISPER_INITIAL_PROMPT)
    if bad:
        print(f"  ⚠️  ASR SANITY: {bad}")
        print("     Treat this transcript as UNUSABLE — re-run without an "
              "initial_prompt, or author the caption instead of quoting it.")
    return words


def _norm(s: str) -> str:
    import re as _re
    return _re.sub(r"[\s，。、！？,.!?]", "", s or "")


def asr_sanity(words, prompt: str = "", echo_ratio: float = 0.6,
               repeat_max: int = 4):
    """Reasons this transcript must not be trusted. Returns a string or None.

    Whisper ECHOES THE PROMPT BACK when the audio is noisy: on 2026-08-18 a
    6-second clip of a noisy room returned the initial_prompt verbatim as its
    transcript, at word probabilities that looked ordinary. Nothing downstream
    can tell that apart from real speech, and it would have shipped as a quote
    the person never said. It is cheap to detect and catastrophic to miss.
    """
    if not words:
        return None
    text = _norm("".join(getattr(w, "text", "") or
                         (w.get("text") if isinstance(w, dict) else "")
                         for w in words))
    if not text:
        return None

    p = _norm(prompt)
    if p and len(text) >= 8:
        # longest common substring between transcript and prompt
        best = 0
        for i in range(len(p)):
            for j in range(i + best + 1, len(p) + 1):
                if p[i:j] in text:
                    best = max(best, j - i)
                else:
                    break
        if best >= max(8, int(echo_ratio * len(text))):
            return (f"the transcript is {best}/{len(text)} characters of the "
                    f"initial_prompt echoed back, not speech")

    # runaway repetition: the same phrase over and over
    for size in (6, 8, 12):
        if len(text) < size * 3:
            continue
        counts = {}
        for i in range(len(text) - size + 1):
            g = text[i:i + size]
            counts[g] = counts.get(g, 0) + 1
        g, c = max(counts.items(), key=lambda kv: kv[1])
        if c > repeat_max and c * size > 0.5 * len(text):
            return f"'{g}' repeats {c}x — the decoder looped instead of transcribing"
    return None


def run_transcribe(video_path: str, work_dir: str) -> str:
    """Full transcription pipeline.

    1. Transcribe with faster-whisper
    2. Save raw words JSON
    3. Print review transcript (BLOCKING -- user must verify)
    4. Return path to words JSON

    Returns path to words.json (user should verify before next step).
    """
    os.makedirs(work_dir, exist_ok=True)
    words_path = os.path.join(work_dir, "words.json")

    print("  Transcribing with faster-whisper...")
    words = transcribe(video_path, work_dir)

    # Convert simplified Chinese → traditional Chinese
    words = _convert_to_traditional(words)
    save_words(words, words_path)

    # Format for review
    review = format_transcript_for_review(words)
    low_conf = [w for w in words if w.confidence < CONFIDENCE_THRESHOLD]

    print(f"\n{'='*60}")
    print("TRANSCRIPT FOR REVIEW")
    print(f"{'='*60}")
    print(review)
    print(f"{'='*60}")
    print(f"Total words: {len(words)}")
    if low_conf:
        print(f"Low confidence ({len(low_conf)} words marked with [?]):")
        for w in low_conf:
            print(f"  [{w.start:.1f}s] \"{w.text}\" -- {int(w.confidence*100)}%")
    else:
        print("All words high confidence.")
    print(f"\nSaved to: {words_path}")
    print("Review the transcript above. Edit words.json if needed, then continue.")

    return words_path
