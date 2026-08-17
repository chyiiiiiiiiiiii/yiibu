"""ASS subtitle generation with keyword highlighting and LLM-based segmentation."""
import json
import os
import re
import subprocess
from typing import Dict, List, Optional, Set, Tuple
from modules.types import Word
from config import (
    SKILL_DIR,
    FONT_NAME, FONT_SIZE_DEFAULT, FONT_SIZE_KEYWORD,
    FONT_SIZE_COUNTER, FONT_SIZE_TITLE, FONT_SIZE_SUBTITLE_CARD,
    COLOR_WHITE, COLOR_BLACK, COLOR_DIM, COLOR_GOLD, COLOR_GOLD_SHADOW,
    COLOR_OUTLINE, COLOR_BG_SHADOW, COLOR_SHADOW,
    SUBTITLE_OUTLINE, SUBTITLE_SHADOW,
    KEYWORD_SCALE, KEYWORD_POP_ANIMATION,
    SUBTITLE_MAX_WIDTH_RATIO,
    PHRASE_PAUSE_THRESHOLD, PHRASE_MAX_CHARS,
    SUBTITLE_GAP,
    SUBTITLE_FLOAT_PX, SUBTITLE_FLOAT_MS, SUBTITLE_FADE_IN_MS, SUBTITLE_BOTTOM_EXTRA,
    TITLE_CARD_DURATION, TITLE_CARD_FADE_IN_MS, TITLE_CARD_FADE_OUT_MS,
    TITLE_CARD_OUTLINE, TITLE_CARD_SHADOW, TITLE_CARD_LAYER, TITLE_CARD_GAP_PX,
    OUTPUT_WIDTH, OUTPUT_HEIGHT,
    SUBTITLE_BILINGUAL, FONT_SIZE_ENGLISH, COLOR_ENGLISH, SUBTITLE_ENGLISH_KEYWORD_GOLD,
    SUBTITLE_EMPHASIS_ENABLED, FONT_SIZE_EMPHASIS, FONT_SIZE_EMPHASIS_ENGLISH,
    EMPHASIS_MAX_MOMENTS, EMPHASIS_MAX_CHARS, EMPHASIS_STAGGER_X,
    EMPHASIS_BASE_Y_RATIO, EMPHASIS_BLOCK_STEP, EMPHASIS_MIN_CHUNK_SEC, EMPHASIS_MIN_PHRASE_SEC,
)

_SENTENCE_ENDERS = set("。？！?!")
_CLAUSE_BREAKS = set("，、,;；：:")
_CJK_PARTICLES = set("的了在是和或而等把被比從到對讓跟")
# Characters that should NEVER end a subtitle line — they belong at the
# START of the next clause.  Breaking after them hurts readability.
_BAD_LINE_ENDERS = set("但不從若且雖往")
_CJK_WIDTH_RATIO = 1.0
_ASCII_WIDTH_RATIO = 0.55

_ASCII_RE = re.compile(r'^[A-Za-z0-9%\-_.]+$')


def _merge_english_fragments(words: List[Word]) -> List[Word]:
    """Merge consecutive ASCII/number tokens into single words.

    Whisper often splits English words char-by-char (e.g. "M"+"ine"+"craft").
    This merges them back into "Minecraft" as one Word with combined timing.
    Also merges mixed CJK+ASCII tokens like "AI這是" that Whisper concatenates.
    """
    if not words:
        return words

    merged: List[Word] = []
    i = 0
    while i < len(words):
        w = words[i]
        # Check if this is an ASCII-only token that might be a fragment
        if _ASCII_RE.match(w.text):
            # Collect consecutive ASCII fragments with tiny gaps
            group = [w]
            j = i + 1
            while j < len(words):
                nxt = words[j]
                gap = nxt.start - group[-1].end
                if gap > 0.15:  # >150ms gap = separate word
                    break
                if _ASCII_RE.match(nxt.text):
                    group.append(nxt)
                    j += 1
                else:
                    break
            if len(group) > 1:
                # Smart merge: concatenate fragments but add space between
                # separate words.  Heuristic: merge directly (no space) only
                # when (a) first token is a single char, OR (b) first ends
                # lowercase AND second starts lowercase, OR (c) second token
                # is a single non-alnum char (%, ., etc.).  Otherwise insert
                # a space to preserve word boundaries like "AI agent",
                # "Code Review", "Feature Flag", "Latent Space".
                parts = [group[0].text]
                for k in range(1, len(group)):
                    prev_t = group[k - 1].text
                    curr_t = group[k].text
                    direct_merge = (
                        len(prev_t) <= 1
                        or (prev_t[-1].islower() and curr_t[0].islower())
                        or (len(curr_t) == 1 and not curr_t.isalnum())
                    )
                    if direct_merge:
                        parts.append(curr_t)
                    else:
                        parts.append(" ")
                        parts.append(curr_t)
                merged_text = "".join(parts)
                merged.append(Word(
                    text=merged_text,
                    start=group[0].start,
                    end=group[-1].end,
                    confidence=min(g.confidence for g in group),
                ))
                i = j
                continue
        merged.append(w)
        i += 1

    return merged


def is_keyword(word: str, keywords: List[str]) -> bool:
    """Rule-based keyword detection (fallback when LLM tagging unavailable)."""
    w = word.lower().strip()
    if len(w) < 2:
        return False
    for kw in keywords:
        if w in kw.lower() or kw.lower() in w:
            return True
        for part in kw.lower().split():
            if w == part or part in w:
                return True
    return False


def format_ass_time(seconds: float) -> str:
    total_cs = round(seconds * 100)
    h = total_cs // 360000
    total_cs %= 360000
    m = total_cs // 6000
    total_cs %= 6000
    s = total_cs // 100
    cs = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ends_with_any(text: str, char_set: set) -> bool:
    return any(c in text for c in char_set)


def _estimate_word_width(text: str, font_size: int, scale: float = 1.0) -> float:
    width = 0.0
    for c in text:
        if ord(c) > 127:
            width += font_size * _CJK_WIDTH_RATIO
        else:
            width += font_size * _ASCII_WIDTH_RATIO
    return width * scale


# ─── LLM-based smart segmentation + keyword tagging ──────────

def _call_gemini(prompt: str) -> Optional[str]:
    """Generate text via the google-genai SDK (.venv). Returns text or None.

    Migrated off the `gemini -p` CLI (disallowed + unreliable) to the SDK helper.
    """
    from .llm import gemini_generate
    return gemini_generate(prompt)


def _segment_with_llm(words: List[Word]) -> Optional[List[List[Word]]]:
    """Use Gemini CLI to segment transcript into natural subtitle phrases.

    Returns list of word groups, or None if LLM segmentation fails.
    """
    full_text = "".join(w.text for w in words)

    prompt = f"""你是短影片字幕分段專家。將以下口語轉錄文字分段為 TikTok/Shorts 字幕行。

規則：
- 每行最多 10 個中文字（英文字母/數字算半個字）
- 一次只顯示一行，不要讓兩句黏在一起
- 在語意自然的地方斷句，讓觀眾好閱讀
- 關鍵字/專有名詞（如 ChatGPT、Flutter、AI Agent）盡量獨立成一段或放在短行開頭
- 招呼語單獨一行（如「嗨我是某某」）
- 問句結尾處斷句
- 數據資訊盡量完整（如「兩萬五千行」不要拆開）
- 主題轉換處斷句（如「這代表...」開頭表示新觀點）
- 逗號（，）處必須斷句，用 | 標記，並移除逗號本身
- 輸出中不要保留任何逗號（，、,）

用 | 標記每個斷點。只輸出標記後的完整文字，不要加任何說明或修改文字。

{full_text}"""

    output = _call_gemini(prompt)
    if not output:
        return None

    # Parse: extract only the line with | markers
    segmented = None
    for line in output.split("\n"):
        line = line.strip()
        if "|" in line and len(line) > 10:
            segmented = line
            break
    if not segmented:
        if "|" in output:
            segmented = output.replace("\n", "")
        else:
            return None

    segments = [s.strip() for s in segmented.split("|") if s.strip()]
    if not segments:
        return None

    return _map_segments_to_words(words, segments)


def _tag_keywords_with_llm(
    words: List[Word],
    keywords: List[str],
) -> Optional[Set[int]]:
    """Use Gemini CLI to identify which character spans are keywords.

    Returns a set of Word indices that are keywords, or None on failure.
    The LLM returns keyword strings found in the text; we then find them
    in the original text using substring search.
    """
    full_text = "".join(w.text for w in words)
    kw_str = "、".join(keywords)

    prompt = f"""你是科技影片字幕關鍵字標記專家。

以下是語音轉錄文字和關鍵字列表。請找出文字中所有的關鍵字，並用 [ ] 標記。

規則：
- 參考關鍵字列表：{kw_str}
- 用 [關鍵字] 包住完整的關鍵字
- 例如：原文有 "Codex"（由ASR拆成 "Code"+"x"），整體是一個詞，標記為 [Codex]
- 人名如 "AndreasKling" 也可標記
- Test262 是測試套件名稱，標記為 [Test262]
- 同一個關鍵字出現多次，每次都要標記
- 不要修改任何原文內容，不要加空格

只輸出標記後的完整文字（一行），不要加說明。

{full_text}"""

    output = _call_gemini(prompt)
    if not output:
        return None

    # Find the line with brackets
    tagged = None
    for line in output.split("\n"):
        line = line.strip()
        if "[" in line and "]" in line and len(line) > 10:
            tagged = line
            break
    if not tagged:
        if "[" in output:
            tagged = output.replace("\n", "")
        else:
            return None

    # Extract keyword spans from the tagged text
    # Parse [...] positions and map back to original text using char alignment
    return _map_keyword_tags_to_words(words, full_text, tagged)


def _map_keyword_tags_to_words(
    words: List[Word],
    original: str,
    tagged: str,
) -> Optional[Set[int]]:
    """Map LLM-tagged [...] spans back to Word indices.

    Aligns tagged text (with brackets) to original text character by character,
    tracking which original characters fall inside [...] spans.
    """
    total_chars = len(original)
    char_to_word: List[int] = []
    for idx, w in enumerate(words):
        for _ in w.text:
            char_to_word.append(idx)

    # Walk through tagged text, tracking bracket state
    kw_word_indices: Set[int] = set()
    orig_pos = 0
    in_bracket = False
    kw_count = 0

    for tc in tagged:
        if tc == "[":
            in_bracket = True
            kw_count += 1
            continue
        if tc == "]":
            in_bracket = False
            continue

        # Regular character — try to match with original
        if orig_pos < total_chars and tc == original[orig_pos]:
            if in_bracket:
                kw_word_indices.add(char_to_word[orig_pos])
            orig_pos += 1
        elif orig_pos < total_chars:
            # LLM may have added a space — skip it
            if tc == " " or tc == "\u3000":
                continue
            # Try advancing original to find match (LLM might have skipped)
            found = False
            for lookahead in range(1, 4):
                if orig_pos + lookahead < total_chars and tc == original[orig_pos + lookahead]:
                    # Mark skipped chars if we're in a bracket
                    if in_bracket:
                        for skip in range(orig_pos, orig_pos + lookahead + 1):
                            kw_word_indices.add(char_to_word[skip])
                    orig_pos = orig_pos + lookahead + 1
                    found = True
                    break
            if not found:
                # Can't align — skip this LLM character
                continue

    print(f"  Keyword tagging: {len(kw_word_indices)} words across {kw_count} spans "
          f"(aligned {orig_pos}/{total_chars} chars)")
    return kw_word_indices


def _map_segments_to_words(
    words: List[Word],
    segments: List[str],
    strip_table=None,
) -> Optional[List[List[Word]]]:
    """Map LLM text segments back to Word objects using fuzzy character matching.

    Tolerates minor LLM modifications (added/removed chars) by scanning the
    original text for each segment character, skipping unmatched LLM chars.
    """
    # Build char_to_word index
    original_chars: List[str] = []
    char_to_word: List[int] = []
    for i, w in enumerate(words):
        text = w.text.translate(strip_table) if strip_table else w.text
        for c in text:
            original_chars.append(c)
            char_to_word.append(i)

    total_chars = len(char_to_word)
    if total_chars == 0:
        return None

    groups: List[List[Word]] = []
    orig_pos = 0  # position in original text

    for seg in segments:
        if not seg or orig_pos >= total_chars:
            continue
        start_word_idx = char_to_word[orig_pos]
        # Match segment chars against original, skipping LLM-added chars
        for sc in seg:
            if orig_pos >= total_chars:
                break
            if sc == original_chars[orig_pos]:
                orig_pos += 1
            elif sc == " " or sc == "\u3000":
                continue  # skip spaces LLM added
            # else: LLM added a char not in original — just skip it
        end_word_idx = char_to_word[min(orig_pos - 1, total_chars - 1)] if orig_pos > 0 else start_word_idx
        if end_word_idx >= start_word_idx:
            groups.append(words[start_word_idx:end_word_idx + 1])

    # Append any remaining words as last group
    if orig_pos < total_chars:
        remaining_start = char_to_word[orig_pos]
        groups.append(words[remaining_start:])

    # Ensure all words are covered: rebuild groups as contiguous word slices
    if not groups:
        return None
    # Convert overlapping/gapped groups into clean contiguous coverage
    clean_groups: List[List[Word]] = []
    next_word_idx = 0
    for g in groups:
        if not g:
            continue
        # Find the earliest word index in this group
        first_idx = next((i for i, w in enumerate(words) if w is g[0]), None)
        last_idx = next((i for i, w in enumerate(words) if w is g[-1]), None)
        if first_idx is None or last_idx is None:
            continue
        # Fill any gap from previous group
        start = max(first_idx, next_word_idx)
        end = last_idx + 1
        if start < end:
            clean_groups.append(words[start:end])
            next_word_idx = end
    # Append any remaining words
    if next_word_idx < len(words):
        if clean_groups:
            clean_groups[-1] = list(clean_groups[-1]) + words[next_word_idx:]
        else:
            clean_groups.append(words[next_word_idx:])

    total_mapped = sum(len(g) for g in clean_groups)
    if total_mapped != len(words):
        return None

    return clean_groups


# ─── Rule-based fallback segmentation ─────────────────────────

def _find_keyword_word_spans(words: List[Word], keywords: List[str]) -> List[Tuple[int, int]]:
    """Find keyword spans in word list (start_idx, end_idx inclusive).

    Matches keyword strings against concatenated word text to protect
    keywords from being split across phrase boundaries.
    """
    spans = []
    text = "".join(w.text for w in words)
    # Build char-to-word index mapping
    char_to_word = []
    for wi, w in enumerate(words):
        char_to_word.extend([wi] * len(w.text))

    for kw in keywords:
        kw_lower = kw.lower()
        pos = 0
        while True:
            idx = text.lower().find(kw_lower, pos)
            if idx == -1:
                break
            end_char = idx + len(kw_lower) - 1
            if idx < len(char_to_word) and end_char < len(char_to_word):
                spans.append((char_to_word[idx], char_to_word[end_char]))
            pos = idx + 1
    return spans


def _inside_keyword_span(word_idx: int, kw_spans: List[Tuple[int, int]]) -> bool:
    """Check if word_idx is inside (but not at the end of) a keyword span."""
    for s, e in kw_spans:
        if s <= word_idx < e:  # inside but not the last word
            return True
    return False


def _best_lookback_break(current: List[Word], _spans: List[Tuple[int, int]], global_offset: int) -> int:
    """Find the best break point within `current` by looking back from the end.

    Returns local index in `current` to break AFTER (inclusive).
    Returns -1 if no good break found.
    Enforces: left side >= 5 chars, right side >= 3 chars.
    """
    if len(current) <= 2:
        return -1

    best_idx = -1
    best_score = -1  # higher = better

    for j in range(len(current) - 2, 0, -1):  # skip last word, skip first word
        global_j = global_offset + j
        # Don't break inside keyword span
        if _inside_keyword_span(global_j, _spans):
            continue

        left_chars = sum(len(current[k].text) for k in range(j + 1))
        right_chars = sum(len(current[k].text) for k in range(j + 1, len(current)))

        # Hard minimum: both sides must be readable
        if left_chars < 5 or right_chars < 3:
            continue

        text = current[j].text
        last_char = text[-1] if text else ""

        # Score break points: keyword end > clause > particle > any
        if _is_keyword_span_end(global_j, _spans):
            score = 30  # best: right after keyword ends
        elif last_char in _CLAUSE_BREAKS:
            score = 25  # great: after clause break
        elif last_char in _CJK_PARTICLES:
            score = 20  # good: after particle (的/了/在/...)
        else:
            score = 5   # fallback: any position

        if score > best_score:
            best_score = score
            best_idx = j

    return best_idx


def _is_keyword_span_end(word_idx: int, kw_spans: List[Tuple[int, int]]) -> bool:
    """Check if word_idx is the last word of a keyword span."""
    for s, e in kw_spans:
        if word_idx == e:
            return True
    return False


def _group_words_rule_based(
    words: List[Word],
    pause_threshold: float = PHRASE_PAUSE_THRESHOLD,
    max_chars: int = PHRASE_MAX_CHARS,
    kw_spans: Optional[List[Tuple[int, int]]] = None,
) -> List[List[Word]]:
    """Fallback: group words using punctuation, pause, and keyword rules.

    When max_chars is hit, looks back for the best semantic break point
    (after keyword, after particle) instead of cutting at the limit.
    """
    phrases: List[List[Word]] = []
    current: List[Word] = []
    chars = 0
    _spans = kw_spans or []
    global_offset = 0  # tracks where current[0] is in the global words list

    for i, w in enumerate(words):
        current.append(w)
        chars += len(w.text)

        # Never break inside a keyword span
        if _inside_keyword_span(i, _spans):
            continue

        if _ends_with_any(w.text, _SENTENCE_ENDERS):
            phrases.append(current)
            global_offset = i + 1
            current = []
            chars = 0
            continue

        if i + 1 < len(words):
            gap = words[i + 1].start - w.end
            if gap >= pause_threshold:
                phrases.append(current)
                global_offset = i + 1
                current = []
                chars = 0
                continue

        if chars >= 6 and _ends_with_any(w.text, _CLAUSE_BREAKS):
            phrases.append(current)
            global_offset = i + 1
            current = []
            chars = 0
            continue

        # Break after keyword span ends when phrase is long enough
        if chars >= 6 and _is_keyword_span_end(i, _spans):
            phrases.append(current)
            global_offset = i + 1
            current = []
            chars = 0
            continue

        # Break after particles (的/了/在/...) when phrase is long enough
        if chars >= 10 and w.text and w.text[-1] in _CJK_PARTICLES:
            phrases.append(current)
            global_offset = i + 1
            current = []
            chars = 0
            continue

        if chars >= max_chars:
            # Look back for a better break point
            break_at = _best_lookback_break(current, _spans, global_offset)
            if break_at >= 0:
                # Split: emit words up to break_at, carry the rest
                phrases.append(current[:break_at + 1])
                leftover = current[break_at + 1:]
                current = leftover
                global_offset = i - len(leftover) + 1
                chars = sum(len(w2.text) for w2 in current)
            else:
                # No good break found — emit as-is
                phrases.append(current)
                global_offset = i + 1
                current = []
                chars = 0

    if current:
        phrases.append(current)

    return phrases


# ─── Line wrapping ────────────────────────────────────────────

def _build_word_id_map(all_words: List[Word]) -> Dict[int, int]:
    """Build id(word) → index map for O(1) lookups."""
    return {id(w): i for i, w in enumerate(all_words)}


def _has_cjk(text: str) -> bool:
    """True if text contains any CJK character."""
    return any(ord(c) >= 0x3000 for c in text)


def _build_keyword_spans(
    words: List[Word],
    word_id_map: Dict[int, int],
    kw_indices: Set[int],
) -> List[Tuple[int, int]]:
    """Build atomic keyword spans as (start_idx, end_idx) tuples (inclusive).

    Only merge consecutive keyword words when they share the same script:
    - Both Latin/ASCII → merge (e.g., "Quiver" + "AI" → one span)
    - Both CJK → merge (e.g., "配" + "置" + "狀" + "態" → one span)
    At script boundaries (CJK↔Latin), start a new span to separate
    different concepts (e.g., "Icon" | "插圖" | "UI" | "素材").
    """
    spans: List[Tuple[int, int]] = []
    i = 0
    while i < len(words):
        wi = word_id_map.get(id(words[i]), -1)
        if wi in kw_indices:
            start = i
            i += 1
            while i < len(words) and word_id_map.get(id(words[i]), -1) in kw_indices:
                prev_cjk = _has_cjk(words[i - 1].text)
                curr_cjk = _has_cjk(words[i].text)
                if prev_cjk != curr_cjk:
                    # Script boundary (CJK↔Latin) — start a new span
                    spans.append((start, i - 1))
                    start = i
                i += 1
            spans.append((start, i - 1))
        else:
            i += 1
    return spans


def _is_inside_keyword_span(break_after_idx: int, spans: List[Tuple[int, int]]) -> bool:
    """True if splitting after break_after_idx would break a keyword span."""
    for start, end in spans:
        if start <= break_after_idx < end:
            return True
    return False


def _is_before_keyword_span(break_after_idx: int, spans: List[Tuple[int, int]]) -> bool:
    """True if the next word starts a keyword span (good break point for emphasis)."""
    next_idx = break_after_idx + 1
    for start, _ in spans:
        if next_idx == start:
            return True
    return False


def _compute_break_penalty(
    words: List[Word],
    break_after: int,
    total: int,
    line2_char_count: int,
    kw_spans: List[Tuple[int, int]],
) -> int:
    """Compute penalty for breaking after words[break_after].

    Lower = better break point.
    """
    # Forbidden: split inside keyword span
    if _is_inside_keyword_span(break_after, kw_spans):
        return 10000

    # Orphan: <=2 chars on last line
    if line2_char_count <= 2:
        return 1000

    text = words[break_after].text
    last_char = text[-1] if text else ""

    # Bad: ending on a conjunction/preposition that should start next clause
    if last_char in _BAD_LINE_ENDERS:
        return 5000

    # Best: after clause punctuation
    if last_char in _CLAUSE_BREAKS or last_char in _SENTENCE_ENDERS:
        return 0

    # Good: after particle (的/了/在/...)
    if last_char in _CJK_PARTICLES:
        return 1

    # Good: right before a keyword span (lets keyword stand out on new line)
    if _is_before_keyword_span(break_after, kw_spans):
        return 2

    # Default: between content characters
    return 10


def _wrap_into_lines(
    words: List[Word],
    word_id_map: Dict[int, int],
    kw_indices: Set[int],
    max_width_px: float,
    font_size: int,
) -> List[List[Word]]:
    """Split a phrase into visual lines that fit within max_width_px.

    Uses penalty-based wrapping to avoid:
    - Orphaning single characters on a line
    - Splitting keyword spans
    - Breaking at awkward positions in CJK text
    """
    # Calculate per-word widths
    widths: List[float] = []
    char_counts: List[int] = []
    for w in words:
        wi = word_id_map.get(id(w), -1)
        is_kw = wi in kw_indices
        scale = KEYWORD_SCALE / 100.0 if is_kw else 1.0
        widths.append(_estimate_word_width(w.text, font_size, scale))
        char_counts.append(len(w.text))

    total_width = sum(widths)

    # Single line fits — no wrapping needed
    if total_width <= max_width_px:
        return [words]

    # Need to wrap — find best break point using penalties
    kw_spans = _build_keyword_spans(words, word_id_map, kw_indices)
    total = len(words)

    best_break = -1
    best_penalty = float('inf')

    cumulative_width = 0.0
    cumulative_chars = 0
    total_chars = sum(char_counts)

    for i in range(total - 1):
        cumulative_width += widths[i]
        cumulative_chars += char_counts[i]
        remaining_width = total_width - cumulative_width
        remaining_chars = total_chars - cumulative_chars

        # Both lines must fit within max_width
        if cumulative_width > max_width_px:
            break
        if remaining_width > max_width_px:
            continue

        penalty = _compute_break_penalty(words, i, total, remaining_chars, kw_spans)

        if penalty < best_penalty:
            best_penalty = penalty
            best_break = i

    # If best break would split a keyword, relax line2 width constraint
    # and allow line2 to overflow (it will be recursively wrapped)
    if best_penalty >= 10000:
        cumulative_width = 0.0
        cumulative_chars = 0
        for i in range(total - 1):
            cumulative_width += widths[i]
            cumulative_chars += char_counts[i]
            remaining_chars = total_chars - cumulative_chars

            if cumulative_width > max_width_px:
                break

            penalty = _compute_break_penalty(words, i, total, remaining_chars, kw_spans)
            if penalty < best_penalty:
                best_penalty = penalty
                best_break = i

    if best_break >= 0:
        line1 = words[:best_break + 1]
        line2 = words[best_break + 1:]
        # Recursively wrap line2 if it's still too wide
        if sum(widths[best_break + 1:]) > max_width_px:
            return [line1] + _wrap_into_lines(line2, word_id_map, kw_indices, max_width_px, font_size)
        return [line1, line2]

    # Fallback: greedy wrap (no valid penalty break found)
    lines: List[List[Word]] = [[]]
    current_width = 0.0
    for i, w in enumerate(words):
        if current_width + widths[i] > max_width_px and current_width > 0:
            lines.append([])
            current_width = 0.0
        lines[-1].append(w)
        current_width += widths[i]
    return lines


def _join_kw_texts(texts: list) -> str:
    """Join keyword word texts with proper spacing.

    CJK words join directly (no space). Latin words join with a space.
    """
    if not texts:
        return ""
    result = texts[0]
    for t in texts[1:]:
        if result and t:
            # Strip punctuation to get last real char
            last_ch = ""
            for ch in reversed(result):
                if ch.isalnum():
                    last_ch = ch
                    break
            first_ch = t[0]
            # Both Latin → add space
            if (last_ch and last_ch.isascii() and last_ch.isalnum()
                    and first_ch.isascii() and first_ch.isalnum()):
                result += " " + t
            else:
                result += t
        else:
            result += t
    return result


def _load_display_corrections() -> Dict[str, str]:
    """Load display_corrections from term_corrections.json.

    Returns dict mapping wrong text → correct text.
    """
    path = os.path.join(SKILL_DIR, "term_corrections.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("display_corrections", {})
    except (json.JSONDecodeError, IOError):
        return {}


def _apply_display_corrections(text: str) -> str:
    """Apply known term corrections to subtitle text.

    E.g., "Open Claw" → "OpenClaw", "Claw Jacked" → "ClawJacked".
    Case-insensitive matching with case-correct replacement.
    """
    corrections = _load_display_corrections()
    for wrong, correct in corrections.items():
        # Case-insensitive replacement
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        text = pattern.sub(correct, text)
    return text


def _kw_scale_tags() -> str:
    """Scale tags for a gold keyword run.

    With KEYWORD_POP_ANIMATION on, the run pops 100→130→120 over 300ms; with it
    off the keyword simply renders at KEYWORD_SCALE with no motion.
    """
    if not KEYWORD_POP_ANIMATION:
        return f"\\fscx{KEYWORD_SCALE}\\fscy{KEYWORD_SCALE}"
    return (
        f"\\fscx100\\fscy100"
        f"\\t(0,150,\\fscx{KEYWORD_SCALE + 10}\\fscy{KEYWORD_SCALE + 10})"
        f"\\t(150,300,\\fscx{KEYWORD_SCALE}\\fscy{KEYWORD_SCALE})"
    )


def _render_words(words: List[Word], word_id_map: Dict[int, int], kw_indices: Set[int]) -> str:
    """Render words with keyword highlighting + pop animation.

    Keywords get: gold color, 120% scale, pop-in bounce via \\t().
    Adjacent keyword words are merged into one styled span (no \\r between them)
    to avoid mid-keyword white flashes.
    """
    _STRIP_COMMAS = str.maketrans("", "", "，、,。.")
    parts = []
    i = 0
    while i < len(words):
        wi = word_id_map.get(id(words[i]), -1)
        if wi in kw_indices:
            # Collect keyword words, splitting at CJK boundaries
            kw_texts = [words[i].text]
            i += 1
            while i < len(words):
                wi2 = word_id_map.get(id(words[i]), -1)
                if wi2 not in kw_indices:
                    break
                prev_text = words[i - 1].text
                curr_text = words[i].text
                if _has_cjk(prev_text) != _has_cjk(curr_text):
                    # Script boundary (CJK↔Latin) — render current group, start new
                    kw_str_inner = _apply_display_corrections(
                        _join_kw_texts(kw_texts).translate(_STRIP_COMMAS)
                    )
                    if parts and parts[-1] and not parts[-1].endswith(" "):
                        last_v = parts[-1].rstrip("}")
                        if last_v and ord(last_v[-1]) > 127 and kw_str_inner and kw_str_inner[0].isascii() and kw_str_inner[0].isalnum():
                            parts.append(" ")
                    parts.append(
                        f"{{\\1c{COLOR_GOLD}"
                        f"{_kw_scale_tags()}}}"
                        f"{kw_str_inner}{{\\r}}"
                    )
                    kw_texts = [curr_text]
                else:
                    kw_texts.append(curr_text)
                i += 1
            kw_str = _apply_display_corrections(
                _join_kw_texts(kw_texts).translate(_STRIP_COMMAS)
            )
            # Add space before keyword if previous part ends with CJK
            if parts and parts[-1] and not parts[-1].endswith(" "):
                last_visible = parts[-1].rstrip("}")
                if last_visible and ord(last_visible[-1]) > 127:
                    # Previous ends with CJK, keyword starts with Latin
                    if kw_str and kw_str[0].isascii() and kw_str[0].isalnum():
                        parts.append(" ")
            parts.append(
                f"{{\\1c{COLOR_GOLD}"
                f"{_kw_scale_tags()}}}"
                f"{kw_str}{{\\r}}"
            )
        else:
            text = words[i].text.translate(_STRIP_COMMAS)
            # Add CJK-Latin spacing
            if parts and text:
                last_part = parts[-1]
                # Find last visible char (skip ASS tags ending with })
                last_visible = ""
                for ch in reversed(last_part):
                    if ch == '}':
                        # Skip to matching {
                        tag_end = last_part.rfind('{')
                        if tag_end >= 0:
                            before_tag = last_part[:tag_end]
                            if before_tag:
                                last_visible = before_tag[-1]
                        break
                    else:
                        last_visible = ch
                        break
                if last_visible:
                    # CJK → Latin or Latin → CJK
                    if ord(last_visible) > 127 and text[0].isascii() and text[0].isalnum():
                        parts.append(" ")
                    elif last_visible.isascii() and last_visible.isalnum() and ord(text[0]) > 127:
                        parts.append(" ")
            parts.append(text)
            i += 1
    return "".join(parts)


def generate_subtitle_text(
    words: List[Word],
    word_id_map: Dict[int, int],
    kw_indices: Set[int],
    max_width_px: float,
    font_size: int,
) -> str:
    """Generate subtitle text as a single line (no wrapping)."""
    return _render_words(words, word_id_map, kw_indices)


# ─── LLM review pass ─────────────────────────────────────────

_CJK_RANGE = re.compile(r'([\u4e00-\u9fff\u3400-\u4dbf])')
_CJK_THEN_LATIN = re.compile(r'([\u4e00-\u9fff\u3400-\u4dbf])([A-Za-z0-9])')
_LATIN_THEN_CJK = re.compile(r'([A-Za-z0-9])([\u4e00-\u9fff\u3400-\u4dbf])')


def _add_cjk_latin_spacing(text: str) -> str:
    """Insert a half-width space between CJK and Latin/digit characters."""
    text = _CJK_THEN_LATIN.sub(r'\1 \2', text)
    text = _LATIN_THEN_CJK.sub(r'\1 \2', text)
    return text


def _review_subtitles_with_llm(
    words: List[Word],
    phrases: List[List[Word]],
    keywords: List[str],
) -> Optional[List[List[Word]]]:
    """Post-process subtitles with LLM for readability review.

    Sends current segmentation to LLM, asks it to review and fix:
    - Split words/compound nouns (直|覺 → 直覺)
    - Sentence boundaries (trailing words from next sentence)
    - Keyword integrity (Demo, ARKit stay whole)
    - CJK-Latin spacing
    Returns refined phrases or None if LLM unavailable.
    """
    current_lines = []
    for i, phrase in enumerate(phrases):
        text = "".join(w.text for w in phrase)
        current_lines.append(f"{i+1}. {text}")

    preview = "\n".join(current_lines)
    full_text = "".join(w.text for w in words)
    kw_list = "、".join(keywords) if keywords else "（自動偵測技術名詞）"

    prompt = f"""你是短影片字幕可讀性審核專家。以下是自動分段的字幕，請審核並修正。

## 目前的字幕分段：
{preview}

## 完整原文：
{full_text}

## 關鍵字參考：{kw_list}

## 審核規則：
1. 每段 5-10 個字（英文/數字算半個字），超過 10 字必須拆開
2. 一次只顯示一行，不要把兩句黏在一起（「操作介面你用眼睛」→「操作介面」|「你用眼睛看哪裡」）
3. 禁止拆開詞語（「直覺」「介面」「觸控」必須完整）
4. 關鍵字/專有名詞必須完整（Demo、ARKit、SwiftUI、Arrow1.0）
5. 關鍵字盡量獨立成段或放在短段開頭，不要被淹沒在長句中
6. 在自然語氣停頓處斷句（的、了 等助詞後面是好斷點）
7. 並列項目必須拆成獨立段落（「Icon插圖UI素材」→「Icon」|「插圖」|「UI 素材」）
8. 中文和英文/數字之間加半形空格（如「用 AI」「叫 Arrow1.0」）
9. 不要改變原文文字內容，只調整分段和加空格
10. ⚠️ 嚴禁用連接詞/介詞/否定詞結尾：但、不、從、而、若、且 必須放在下一段開頭，不能黏在上一段尾巴（「多了98%但」→「多了 98%」|「但 review 時間暴增」）
11. 每段必須是完整語意：觀眾看完一段就能理解意思，不需等下一段補充

## 輸出：
只輸出用 | 分隔的字幕段落，一行，不要其他文字。"""

    print("  Reviewing subtitles with LLM...")
    result = _call_gemini(prompt)
    if not result:
        return None

    # Parse LLM output: find the line with | markers
    segmented = None
    for line in result.split("\n"):
        line = line.strip()
        # Skip empty lines and markdown artifacts
        if not line or line.startswith("```") or line.startswith("#"):
            continue
        if "|" in line and len(line) > 10:
            segmented = line
            break
    if not segmented:
        if "|" in result:
            segmented = result.replace("\n", "")
        else:
            print("  LLM review: no valid output")
            return None

    segments = [s.strip() for s in segmented.split("|") if s.strip()]
    if not segments or len(segments) < 3:
        print(f"  LLM review: too few segments ({len(segments)})")
        return None

    # Strip spaces and punctuation for mapping
    _strip_for_map = str.maketrans("", "", " \u3000，、,。？！?!；;：:""''「」")
    clean_segments = [s.translate(_strip_for_map) for s in segments]

    full_text = "".join(w.text for w in words)
    refined = _map_segments_to_words(words, clean_segments, strip_table=_strip_for_map)
    if refined is None:
        print(f"  LLM review: failed to map {len(segments)} segments to words")
        return None

    print(f"  LLM review: {len(phrases)} → {len(refined)} segments (approved)")
    return refined


# ─── Topic counter ────────────────────────────────────────────

def _parse_timing_hint(hint: str) -> Optional[float]:
    """Parse timing_hint like '[10s]' to seconds."""
    m = re.match(r'\[(\d+(?:\.\d+)?)s?\]', hint.strip())
    return float(m.group(1)) if m else None


def _generate_counter_events(
    script_items: List[dict],
    last_end: float,
) -> List[str]:
    """Generate animated topic counter Dialogue events.

    Shows "1 / N" pill in top-left corner for each topic transition,
    with fade + subtle pop animation.
    """
    total = len(script_items)
    if total == 0:
        return []

    timings: List[Optional[float]] = [
        _parse_timing_hint(item.get("timing_hint", ""))
        for item in script_items
    ]

    events: List[str] = []
    for i in range(total):
        start = timings[i]
        if start is None:
            continue

        end = timings[i + 1] if i + 1 < total and timings[i + 1] is not None else last_end
        if end <= start:
            continue

        num = i + 1
        # Fade in/out + subtle pop bounce (100→108→100)
        # Gold number at 115% scale, white "/ N"
        counter_text = (
            f"{{\\fad(400,250)"
            f"\\t(0,200,\\fscx108\\fscy108)"
            f"\\t(200,350,\\fscx100\\fscy100)}}"
            f"{{\\1c{COLOR_GOLD}\\fscx115\\fscy115}}{num}{{\\r}} / {total}"
        )
        events.append(
            f"Dialogue: 2,{format_ass_time(start)},{format_ass_time(end)},"
            f"Counter,,0,0,0,,{counter_text}"
        )

    return events


# ─── Title card ───────────────────────────────────────────────

def _generate_title_card_events(
    title: str,
    subtitle: Optional[str] = None,
    duration: float = TITLE_CARD_DURATION,
) -> List[str]:
    """Generate ASS Dialogue events for the opening title card.

    Returns 1 event (title only) or 2 events (title + subtitle) on Layer 3.
    Animation: fade in/out + subtle scale 95%→100%. Subtitle staggered +100ms.
    """
    events: List[str] = []
    x = OUTPUT_WIDTH // 2
    # Upper quarter of screen (roughly 1/4 from top)
    y_anchor = OUTPUT_HEIGHT // 6

    if subtitle:
        y_title = y_anchor - TITLE_CARD_GAP_PX
        y_sub = y_anchor + FONT_SIZE_TITLE // 2 + TITLE_CARD_GAP_PX
    else:
        y_title = y_anchor
        y_sub = 0  # unused

    fade_in = TITLE_CARD_FADE_IN_MS
    fade_out = TITLE_CARD_FADE_OUT_MS

    # Title event
    title_text = (
        f"{{\\an5\\pos({x},{y_title})"
        f"\\fad({fade_in},{fade_out})"
        f"\\fscx95\\fscy95"
        f"\\t(0,{fade_in},\\fscx100\\fscy100)}}"
        f"{title}"
    )
    events.append(
        f"Dialogue: {TITLE_CARD_LAYER},"
        f"{format_ass_time(0)},{format_ass_time(duration)},"
        f"TitleCard,,0,0,0,,{title_text}"
    )

    # Subtitle event (staggered 100ms)
    if subtitle:
        stagger = 100
        sub_text = (
            f"{{\\an5\\pos({x},{y_sub})"
            f"\\fad({fade_in + stagger},{fade_out})"
            f"\\fscx95\\fscy95"
            f"\\t({stagger},{fade_in + stagger},\\fscx100\\fscy100)}}"
            f"{subtitle}"
        )
        events.append(
            f"Dialogue: {TITLE_CARD_LAYER},"
            f"{format_ass_time(0)},{format_ass_time(duration)},"
            f"TitleCardSub,,0,0,0,,{sub_text}"
        )

    return events


# ─── Bilingual (English) subtitle line ───────────────────────

def _translate_phrases_to_english(phrase_texts: List[str]) -> Optional[List[str]]:
    """Translate Chinese caption phrases to concise English via the .venv Gemini SDK.

    One batched call preserves cross-line context. Technical terms / product names /
    version numbers are kept verbatim. Returns a list aligned 1:1 with the input, or
    None on any failure (missing key, bad parse) so callers fall back to CJK-only.
    """
    texts = [t.strip() for t in phrase_texts]
    if not any(texts):
        return None
    try:
        from modules.llm import gemini_generate
    except Exception:
        return None
    numbered = "\n".join(f"{i + 1}. {t if t else '（空）'}" for i, t in enumerate(texts))
    prompt = (
        "You translate on-screen short-form video captions from Traditional Chinese to English.\n"
        "Rules:\n"
        "- Keep each translation SHORT and caption-like (it sits under the Chinese line).\n"
        "- No trailing punctuation.\n"
        "- Keep technical terms, product/library names, English words and version numbers "
        "VERBATIM (e.g. Flutter, OpenGL, GLTF, GLB, material app, Production, Design System, 0.9.1).\n"
        "- These lines are fragments of continuous speech; translate each as-is, do not merge.\n"
        "- Output EXACTLY one line per input, same count and order, each prefixed with its "
        "number and a period. Output nothing else.\n\n"
        f"{numbered}"
    )
    out = gemini_generate(prompt)
    if not out:
        return None
    parsed: Dict[int, str] = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)[.\)．]\s*(.+)", line)
        if m:
            parsed[int(m.group(1))] = m.group(2).strip()
    result = [parsed.get(i + 1, "").strip() for i in range(len(texts))]
    # Require a translation for every non-empty source line, else bail to CJK-only.
    for src, dst in zip(texts, result):
        if src and not dst:
            return None
    return result


def _highlight_english_keywords(text: str, keywords: List[str]) -> str:
    """Gold-highlight latin technical terms inside an English caption line."""
    if not text or not SUBTITLE_ENGLISH_KEYWORD_GOLD:
        return text
    latin_kw = sorted({k for k in keywords if re.search(r"[A-Za-z]", k)}, key=len, reverse=True)
    for kw in latin_kw:
        text = re.sub(
            re.escape(kw),
            lambda m: f"{{\\c{COLOR_GOLD}}}{m.group(0)}{{\\c{COLOR_WHITE}}}",
            text, flags=re.IGNORECASE,
        )
    return text


def _english_line_suffix(english: str, keywords: List[str], font_size: int = FONT_SIZE_ENGLISH) -> str:
    """Build the trailing '\\N{smaller English}' appended under a Chinese caption."""
    en = _highlight_english_keywords(english.strip(), keywords)
    return f"\\N{{\\fs{font_size}\\c{COLOR_ENGLISH}}}{en}"


# ─── Emphasis captions (punchline / emotional hero lines) ────────

_EMPHASIS_BREAKS = _CLAUSE_BREAKS | _SENTENCE_ENDERS


def _phrase_char_len(phrase: List[Word]) -> int:
    """Visible CJK/Latin char count of a phrase, ignoring punctuation/spaces."""
    text = "".join(w.text for w in phrase)
    return len(re.sub(r"[，、。．.！!？?；;：:\s]", "", text))


def _split_phrase_into_chunks(phrase: List[Word], max_chunks: int = 2) -> List[List[Word]]:
    """Split an emphasis phrase into up to `max_chunks` stacked chunks.

    Break priority: internal clause punctuation nearest the midpoint → largest
    inter-word pause → char midpoint. A phrase too short to stack stays whole.
    """
    n = len(phrase)
    if n <= 1 or _phrase_char_len(phrase) <= 4:
        return [list(phrase)]

    total_chars = sum(len(w.text) for w in phrase)
    mid = total_chars / 2

    # 1. Punctuation break nearest the middle.
    punct = []
    running = 0
    for i in range(n - 1):
        running += len(phrase[i].text)
        last = phrase[i].text[-1] if phrase[i].text else ""
        if last in _EMPHASIS_BREAKS:
            punct.append((abs(running - mid), i))
    if punct:
        punct.sort()
        split_after = punct[0][1]
    else:
        # 2. Largest inter-word pause, if it is a real beat.
        gaps = sorted(
            ((phrase[i + 1].start - phrase[i].end, i) for i in range(n - 1)),
            reverse=True,
        )
        if gaps and gaps[0][0] >= 0.12:
            split_after = gaps[0][1]
        else:
            # 3. Char midpoint.
            running = 0
            split_after = 0
            for i in range(n - 1):
                running += len(phrase[i].text)
                split_after = i
                if running >= mid:
                    break

    c1 = list(phrase[: split_after + 1])
    c2 = list(phrase[split_after + 1:])
    if not c2:
        return [list(phrase)]
    return [c1, c2]


def _parse_emphasis_indices(out: str, eligible: Set[int], max_moments: int) -> Set[int]:
    """Parse LLM output into emphasis phrase indices, keeping only eligible ones.

    Fails safe to an empty set on unparseable output. Honours `max_moments`,
    preferring the lowest indices (earliest moments) for determinism.
    """
    nums = [int(m) for m in re.findall(r"\d+", out or "")]
    picked = [i for i in nums if i in eligible]
    # De-dup preserving order, then cap by earliest index for stability.
    seen: Set[int] = set()
    ordered = [i for i in picked if not (i in seen or seen.add(i))]
    return set(sorted(ordered)[:max_moments])


def _detect_emphasis_moments(phrase_texts: List[str]) -> Set[int]:
    """LLM pass: flag the most emotionally-loaded / quotable caption lines.

    Only short punchy lines qualify (<= EMPHASIS_MAX_CHARS). Returns phrase
    indices to render with the big staggered treatment, or an empty set on any
    failure (no key / bad parse) so callers fall back to normal captions.
    """
    if not SUBTITLE_EMPHASIS_ENABLED:
        return set()
    eligible = {
        i for i, t in enumerate(phrase_texts)
        if 0 < len(re.sub(r"\s", "", t)) <= EMPHASIS_MAX_CHARS
    }
    if not eligible:
        return set()
    try:
        from modules.llm import gemini_generate
    except Exception:
        return set()
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(phrase_texts))
    prompt = (
        "These are consecutive on-screen captions from a Traditional-Chinese short video.\n"
        "Pick the lines that are the emotional peaks / punchlines / quotable turning "
        "points — the ones a viewer would screenshot. Be selective: choose at most "
        f"{EMPHASIS_MAX_MOMENTS}, and ONLY genuinely powerful short lines. Plain "
        "expository or filler lines must NOT be picked.\n"
        "Output ONLY the chosen line numbers, comma-separated (e.g. `2, 7, 11`). "
        "If none qualify, output `none`.\n\n"
        f"{numbered}"
    )
    try:
        out = gemini_generate(prompt)
    except Exception:
        return set()
    return _parse_emphasis_indices(out, eligible, EMPHASIS_MAX_MOMENTS)


def _build_emphasis_events(
    phrase: List[Word],
    chunk_english: List[str],
    word_id_map: Dict[int, int],
    kw_indices: Set[int],
    keywords: List[str],
    phrase_end: float,
    align: int,
    band: Optional[Tuple[float, float]] = None,
) -> List[str]:
    """Render one emphasis phrase as big, staggered, stacked chunk events.

    Each chunk is a separate Dialogue line (Layer 1, above normal captions),
    entering when its words are spoken and persisting to the phrase end. Chunks
    are horizontally staggered around centre and stacked vertically, each with a
    smaller English line beneath — mirroring the IG-style hero-caption look.
    `chunk_english` is a translation per split chunk (may contain "" entries).

    `band` is the face-free vertical zone in px (top, bottom) from face
    detection; the whole stack is centred inside it and clamped on-screen so the
    big text never lands on the speaker's face. Falls back to
    EMPHASIS_BASE_Y_RATIO when no band is known (e.g. direct callers / no video).
    """
    chunks = _split_phrase_into_chunks(phrase)
    # A chunk enters when its words are spoken and holds to the phrase end. When
    # a later chunk starts almost at that end it would flash for a few frames —
    # fold those back into the previous chunk instead of blinking.
    while len(chunks) > 1 and phrase_end - chunks[-1][0].start < EMPHASIS_MIN_CHUNK_SEC:
        chunks[-2] = chunks[-2] + chunks[-1]
        chunks.pop()
    cx = OUTPUT_WIDTH // 2
    n = len(chunks)

    # Vertical footprint of a single chunk (big CJK line + the English beneath it).
    line_half = int(FONT_SIZE_EMPHASIS * 0.62)          # half-height of the CJK line
    eng_drop = FONT_SIZE_EMPHASIS_ENGLISH + 28          # English sits below the anchor
    block_span = (n - 1) * EMPHASIS_BLOCK_STEP          # first-anchor → last-anchor

    if band:
        top_px, bot_px = band
    else:
        c = EMPHASIS_BASE_Y_RATIO * OUTPUT_HEIGHT
        top_px = c - block_span / 2 - line_half
        bot_px = c + block_span / 2 + eng_drop
    # Hard on-screen safety margins.
    top_px = max(top_px, 48)
    bot_px = min(bot_px, OUTPUT_HEIGHT - 48)
    # Anchors must leave room for the CJK half above and the English line below.
    anchor_top = top_px + line_half
    anchor_bot = bot_px - eng_drop
    if anchor_bot < anchor_top:                          # band too shallow → best effort
        anchor_bot = anchor_top
    band_center = (anchor_top + anchor_bot) / 2
    start_y = band_center - block_span / 2
    start_y = max(anchor_top, start_y)
    if start_y + block_span > anchor_bot:
        start_y = max(anchor_top, anchor_bot - block_span)
    start_y = int(start_y)

    events: List[str] = []
    for ci, chunk in enumerate(chunks):
        # Alternate the horizontal offset so stacked lines lean opposite ways.
        x_off = -EMPHASIS_STAGGER_X if ci % 2 == 0 else EMPHASIS_STAGGER_X
        x = cx + x_off
        y = start_y + ci * EMPHASIS_BLOCK_STEP
        start_t = chunk[0].start
        start = format_ass_time(start_t)
        end = format_ass_time(max(start_t + 0.1, phrase_end - SUBTITLE_GAP))
        cjk = _render_words(chunk, word_id_map, kw_indices)
        text = f"{{\\an5\\pos({x},{y})\\fs{FONT_SIZE_EMPHASIS}\\b1\\fad(0,0)}}{cjk}"
        eng = chunk_english[ci] if ci < len(chunk_english) else ""
        if eng:
            text += _english_line_suffix(eng, keywords, FONT_SIZE_EMPHASIS_ENGLISH)
        events.append(
            f"Dialogue: 1,{start},{end},Default,,0,0,0,,{text}"
        )
    return events


# ─── Main ASS generation ─────────────────────────────────────

def generate_ass_file(
    words: List[Word],
    keywords: List[str],
    subtitle_pos: dict,
    output_path: str,
    script_items: Optional[List[dict]] = None,
    title: Optional[str] = None,
    card_subtitle: Optional[str] = None,
    bilingual: Optional[bool] = None,
):
    """Generate complete ASS subtitle file.

    Segmentation priority:
    1. LLM (Gemini CLI) — understands Chinese grammar, semantic breaks
    2. Rule-based fallback — punctuation + speech pauses

    When `bilingual` is True (defaults to config.SUBTITLE_BILINGUAL), a smaller
    English translation line is added under each Chinese caption. Translation uses
    the .venv Gemini SDK and fails safe to Chinese-only if no key is available.
    """
    if bilingual is None:
        bilingual = SUBTITLE_BILINGUAL
    align = subtitle_pos['alignment']
    y_ratio = subtitle_pos['y_ratio']
    side_margin = int(OUTPUT_WIDTH * (1 - SUBTITLE_MAX_WIDTH_RATIO) / 2)
    max_width_px = OUTPUT_WIDTH * SUBTITLE_MAX_WIDTH_RATIO

    if align == 2:
        margin_v = int((1.0 - y_ratio) * OUTPUT_HEIGHT) + SUBTITLE_BOTTOM_EXTRA
    else:
        margin_v = int(y_ratio * OUTPUT_HEIGHT)

    header = f"""[Script Info]
Title: Tech Digest Subtitles
ScriptType: v4.00+
PlayResX: {OUTPUT_WIDTH}
PlayResY: {OUTPUT_HEIGHT}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE_DEFAULT},{COLOR_WHITE},{COLOR_WHITE},{COLOR_OUTLINE},{COLOR_BG_SHADOW},-1,0,0,0,100,100,0,0,1,{SUBTITLE_OUTLINE},{SUBTITLE_SHADOW},{align},{side_margin},{side_margin},{margin_v},1
Style: Keyword,{FONT_NAME},{FONT_SIZE_KEYWORD},{COLOR_GOLD},{COLOR_GOLD},{COLOR_OUTLINE},{COLOR_BG_SHADOW},-1,0,0,0,{KEYWORD_SCALE},{KEYWORD_SCALE},0,0,1,{SUBTITLE_OUTLINE},{SUBTITLE_SHADOW},{align},{side_margin},{side_margin},{margin_v},1
Style: Counter,{FONT_NAME},{FONT_SIZE_COUNTER},{COLOR_WHITE},{COLOR_WHITE},&HA0000000,&H00000000,-1,0,0,0,100,100,2,0,3,12,0,7,40,0,50,1
Style: TitleCard,{FONT_NAME},{FONT_SIZE_TITLE},{COLOR_WHITE},{COLOR_WHITE},{COLOR_OUTLINE},{COLOR_GOLD_SHADOW},-1,0,0,0,100,100,0,0,1,{TITLE_CARD_OUTLINE},{TITLE_CARD_SHADOW},5,10,10,10,1
Style: TitleCardSub,{FONT_NAME},{FONT_SIZE_SUBTITLE_CARD},{COLOR_WHITE},{COLOR_WHITE},{COLOR_OUTLINE},{COLOR_SHADOW},-1,0,0,0,100,100,0,0,1,{TITLE_CARD_OUTLINE - 1},{TITLE_CARD_SHADOW - 1},5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""

    lines = [header.strip()]

    # Title card events (Layer 3, above everything)
    if title:
        tc_events = _generate_title_card_events(title, card_subtitle)
        lines.extend(tc_events)
        print(f"  Title card: {len(tc_events)} event(s)")

    # Step 0: Merge English fragments (M+ine+craft → Minecraft, S+aaS → SaaS)
    orig_word_count = len(words)
    words = _merge_english_fragments(words)
    if len(words) != orig_word_count:
        print(f"  Merged English fragments: {orig_word_count} → {len(words)} words")

    # Step 1: Keyword tagging FIRST (needed for segmentation protection).
    # Deterministic substring match — Gemini CLI is disallowed per user policy AND
    # its char-alignment was unreliable (returned an empty set → no highlight).
    # _find_keyword_word_spans matches keywords across ASR-split tokens exactly.
    print("  Tagging keywords (rule-based substring match)...")
    kw_indices = set()
    for s, e in _find_keyword_word_spans(words, keywords):
        kw_indices.update(range(s, e + 1))
    print(f"  Keyword tagging: {len(kw_indices)} words matched")

    # Step 2: Build keyword spans for segmentation protection
    # Merge script-based spans + LLM-tagged spans
    kw_spans = _find_keyword_word_spans(words, keywords)
    # Also build spans from tagged keyword indices (consecutive kw words = one span)
    if kw_indices:
        sorted_kw = sorted(kw_indices)
        i = 0
        while i < len(sorted_kw):
            start = sorted_kw[i]
            end = start
            while i + 1 < len(sorted_kw) and sorted_kw[i + 1] == end + 1:
                i += 1
                end = sorted_kw[i]
            kw_spans.append((start, end))
            i += 1
    # Deduplicate overlapping spans
    if kw_spans:
        kw_spans.sort()
        merged = [kw_spans[0]]
        for s, e in kw_spans[1:]:
            if s <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        kw_spans = merged
    if kw_spans:
        print(f"  Keyword protection: {len(kw_spans)} span(s)")

    # Step 3: Segmentation (LLM first, rule-based fallback)
    print("  Segmenting transcript (LLM)...")
    phrases = _segment_with_llm(words)
    if phrases:
        print(f"  LLM segmentation: {len(phrases)} phrases")
    else:
        print("  LLM unavailable, using rule-based segmentation")
        phrases = _group_words_rule_based(words, kw_spans=kw_spans)
        print(f"  Rule-based segmentation: {len(phrases)} phrases")

    # Step 4: LLM review pass — check readability, fix boundaries
    reviewed = _review_subtitles_with_llm(words, phrases, keywords)
    if reviewed:
        phrases = reviewed
    else:
        print("  LLM review unavailable, using current segmentation")

    word_id_map = _build_word_id_map(words)

    # Step 5: Width validation — enforce single-line constraint
    # Allow 20% overflow tolerance for keyword scaling before splitting
    overflow_tolerance = 1.2
    orig_count = len(phrases)
    validated = []
    for phrase in phrases:
        total_w = sum(
            _estimate_word_width(
                w.text, FONT_SIZE_DEFAULT,
                KEYWORD_SCALE / 100.0 if word_id_map.get(id(w), -1) in kw_indices else 1.0
            )
            for w in phrase
        )
        if total_w > max_width_px * overflow_tolerance:
            sub_lines = _wrap_into_lines(
                phrase, word_id_map, kw_indices, max_width_px, FONT_SIZE_DEFAULT
            )
            validated.extend(sub_lines)
        else:
            validated.append(phrase)
    if len(validated) != orig_count:
        print(f"  Width validation: {orig_count} → {len(validated)} phrases (split long lines)")
    phrases = validated

    # Step 6: Merge tiny phrases — prevent single-character subtitle entries
    # Any phrase with fewer than MIN_PHRASE_CHARS characters gets merged with
    # its neighbor, but only if the result still fits within max_width_px.
    # IMPORTANT: Conjunctions (但/而/不/從) merge FORWARD into the next phrase,
    # never backward — they start a new clause, not end the previous one.
    MIN_PHRASE_CHARS = 3
    merged_phrases: List[List[Word]] = []
    for idx, phrase in enumerate(phrases):
        char_count = sum(len(w.text) for w in phrase)
        if char_count < MIN_PHRASE_CHARS:
            first_char = phrase[0].text[0] if phrase and phrase[0].text else ""
            is_conjunction = first_char in _BAD_LINE_ENDERS or first_char in set("而所因如不然")
            if is_conjunction:
                # Merge FORWARD: defer — store as pending for next phrase
                merged_phrases.append(list(phrase))  # add now, merge into next
                continue
            elif merged_phrases:
                # Merge BACKWARD (default): append to previous phrase
                candidate = merged_phrases[-1] + list(phrase)
                candidate_w = sum(
                    _estimate_word_width(
                        w.text, FONT_SIZE_DEFAULT,
                        KEYWORD_SCALE / 100.0 if word_id_map.get(id(w), -1) in kw_indices else 1.0
                    )
                    for w in candidate
                )
                if candidate_w <= max_width_px * overflow_tolerance:
                    merged_phrases[-1] = candidate
                else:
                    merged_phrases.append(list(phrase))
                continue
        # Check if previous phrase was a tiny conjunction that needs forward merge
        if len(merged_phrases) >= 1:
            prev_chars = sum(len(w.text) for w in merged_phrases[-1])
            prev_first = merged_phrases[-1][0].text[0] if merged_phrases[-1] and merged_phrases[-1][0].text else ""
            if prev_chars < MIN_PHRASE_CHARS and (prev_first in _BAD_LINE_ENDERS or prev_first in set("而所因如不然")):
                candidate = merged_phrases[-1] + list(phrase)
                candidate_w = sum(
                    _estimate_word_width(
                        w.text, FONT_SIZE_DEFAULT,
                        KEYWORD_SCALE / 100.0 if word_id_map.get(id(w), -1) in kw_indices else 1.0
                    )
                    for w in candidate
                )
                if candidate_w <= max_width_px * overflow_tolerance:
                    merged_phrases[-1] = candidate
                    continue
        merged_phrases.append(list(phrase))
    # Also check if last phrase is tiny, merge backward (with width check)
    if len(merged_phrases) > 1:
        last_chars = sum(len(w.text) for w in merged_phrases[-1])
        if last_chars < MIN_PHRASE_CHARS:
            candidate = merged_phrases[-2] + merged_phrases[-1]
            candidate_w = sum(
                _estimate_word_width(
                    w.text, FONT_SIZE_DEFAULT,
                    KEYWORD_SCALE / 100.0 if word_id_map.get(id(w), -1) in kw_indices else 1.0
                )
                for w in candidate
            )
            if candidate_w <= max_width_px * overflow_tolerance:
                merged_phrases[-2] = candidate
                merged_phrases.pop()
    if len(merged_phrases) != len(phrases):
        print(f"  Tiny-phrase merge: {len(phrases)} → {len(merged_phrases)} phrases")
    phrases = merged_phrases

    # Step 7: Final width enforcement — split any phrase that still overflows
    final_phrases: List[List[Word]] = []
    for phrase in phrases:
        total_w = sum(
            _estimate_word_width(
                w.text, FONT_SIZE_DEFAULT,
                KEYWORD_SCALE / 100.0 if word_id_map.get(id(w), -1) in kw_indices else 1.0
            )
            for w in phrase
        )
        if total_w > max_width_px * overflow_tolerance:
            sub_lines = _wrap_into_lines(
                phrase, word_id_map, kw_indices, max_width_px, FONT_SIZE_DEFAULT
            )
            final_phrases.extend(sub_lines)
        else:
            final_phrases.append(phrase)
    if len(final_phrases) != len(phrases):
        print(f"  Final width enforcement: {len(phrases)} → {len(final_phrases)} phrases")
    phrases = final_phrases

    # Bilingual: translate each phrase's plain text to English (one batched call).
    eng_by_phrase: Optional[List[str]] = None
    if bilingual:
        phrase_texts = ["".join(w.text for w in phrase) for phrase in phrases]
        eng_by_phrase = _translate_phrases_to_english(phrase_texts)
        if eng_by_phrase:
            print(f"  Bilingual: translated {len(eng_by_phrase)} caption lines to English")
        else:
            print("  Bilingual: translation unavailable (no key / parse failed) → Chinese-only")

    # Emphasis detection: flag the emotional-peak / punchline phrases to render
    # big + staggered instead of as a normal caption. Fails safe to none.
    # The face-free band (from face detection) keeps the big text off the face.
    ct = subtitle_pos.get('clear_top')
    cb = subtitle_pos.get('clear_bottom')
    emphasis_band = (ct * OUTPUT_HEIGHT, cb * OUTPUT_HEIGHT) if ct is not None and cb is not None else None
    phrase_plain = ["".join(w.text for w in phrase) for phrase in phrases]
    emphasis_idx = _detect_emphasis_moments(phrase_plain)
    # A hero caption that is on screen for only a few frames reads as a blink,
    # so very short phrases stay in the normal caption style.
    emphasis_idx = {
        i for i in emphasis_idx
        if phrases[i][-1].end - phrases[i][0].start >= EMPHASIS_MIN_PHRASE_SEC
    }
    # Translate each emphasis phrase's split chunks to English (one batched call).
    emphasis_chunks: Dict[int, List[str]] = {}  # phrase idx → English per chunk
    if emphasis_idx:
        print(f"  Emphasis: {len(emphasis_idx)} hero line(s) → big staggered style")
        flat_texts: List[str] = []
        chunk_slices: Dict[int, Tuple[int, int]] = {}
        for i in sorted(emphasis_idx):
            chunks = _split_phrase_into_chunks(phrases[i])
            s = len(flat_texts)
            flat_texts.extend("".join(w.text for w in c) for c in chunks)
            chunk_slices[i] = (s, len(flat_texts))
        translated = _translate_phrases_to_english(flat_texts) if (flat_texts and bilingual) else None
        for i, (s, e) in chunk_slices.items():
            emphasis_chunks[i] = translated[s:e] if translated else ["" for _ in range(e - s)]

    # Static position with fade-in (no float animation)
    x_center = OUTPUT_WIDTH // 2
    if align == 2:  # bottom-center
        y_pos = OUTPUT_HEIGHT - margin_v
    else:  # top-center (8)
        y_pos = margin_v

    for idx, phrase in enumerate(phrases):
        start_t = phrase[0].start
        end_t = phrase[-1].end
        # Trim end time to create a small gap before next subtitle
        end_t = max(start_t + 0.1, end_t - SUBTITLE_GAP)

        # Emphasis phrases get the big staggered treatment (skip normal caption).
        if idx in emphasis_idx:
            lines.extend(_build_emphasis_events(
                phrase, emphasis_chunks.get(idx, []),
                word_id_map, kw_indices, keywords, end_t, align,
                band=emphasis_band,
            ))
            continue

        start = format_ass_time(start_t)
        end = format_ass_time(end_t)
        text = generate_subtitle_text(phrase, word_id_map, kw_indices, max_width_px, FONT_SIZE_DEFAULT)
        # Append the smaller English line underneath (\an anchors keep it below the CJK line)
        if eng_by_phrase and eng_by_phrase[idx]:
            text += _english_line_suffix(eng_by_phrase[idx], keywords)
        # Static position + fade-in only
        float_prefix = (
            f"{{\\an{align}"
            f"\\pos({x_center},{y_pos})"
            f"\\fad({SUBTITLE_FADE_IN_MS},0)}}"
        )
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{float_prefix}{text}"
        )

    # Counter events (animated topic counter pill) — disabled for now
    # if script_items:
    #     last_end = phrases[-1][-1].end if phrases else 0
    #     counter_events = _generate_counter_events(script_items, last_end)
    #     lines.extend(counter_events)
    #     if counter_events:
    #         print(f"  Counter: {len(counter_events)} topic markers")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return output_path
