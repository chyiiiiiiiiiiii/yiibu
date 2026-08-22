"""LLM-driven visual moment extraction from transcript.

Analyzes word-level transcript to identify products, tools, concepts that
should be visualized with B-roll, producing a coverage plan targeting 50-70%.
"""
import json
import re
import subprocess
from typing import List, Dict

from config import (
    BROLL_COVERAGE_TARGET_MIN,
    BROLL_COVERAGE_TARGET_MAX,
    BROLL_SELFIE_BREATHING_MIN,
    BROLL_OPENING_SELFIE,
    BROLL_CLOSING_SELFIE,
    BROLL_MAX_VISUAL_MOMENTS,
    BROLL_DURATION,
)
from modules.types import VisualMoment, Word, load_words


def _build_timestamped_transcript(words: List[Word]) -> str:
    """Format words into timestamped transcript lines: [M:SS] text."""
    lines = []
    current_line = []
    current_start = 0.0
    for w in words:
        if not current_line:
            current_start = w.start
        current_line.append(w.text)
        joined = "".join(current_line)
        if len(joined) >= 80 or w.text.rstrip() in ("。", "！", "？", ".", "!", "?"):
            mins = int(current_start // 60)
            secs = int(current_start % 60)
            lines.append(f"[{mins}:{secs:02d}] {joined}")
            current_line = []
    if current_line:
        mins = int(current_start // 60)
        secs = int(current_start % 60)
        lines.append(f"[{mins}:{secs:02d}] {''.join(current_line)}")
    return "\n".join(lines)


def analyze_transcript_for_visuals(
    words_path: str,
    total_duration: float,
    digest_broll_items: List[Dict] = None,
    digest_mustread_urls: Dict = None,
) -> List[VisualMoment]:
    """Extract visual moments from transcript using Gemini.

    Acts as a "video editor" — identifies every product/tool mention,
    abstract concepts needing visualization, and marks selfie-preferred segments.

    When digest_broll_items/digest_mustread_urls are provided (from tech digest),
    the LLM is given these verified URLs to use as screenshot sources.

    Returns up to BROLL_MAX_VISUAL_MOMENTS moments.
    """
    words = load_words(words_path)
    if not words:
        return []

    transcript = _build_timestamped_transcript(words)

    # Build known sources section from tech digest
    known_sources = ""
    if digest_broll_items or digest_mustread_urls:
        source_lines = []
        if digest_broll_items:
            source_lines.append("B-Roll sources from tech digest (USE THESE URLs):")
            for item in digest_broll_items:
                source_lines.append(
                    f"  - [{item['timestamp']}s] {item['title']}: {item['url']} ({item.get('description', '')})"
                )
        if digest_mustread_urls:
            source_lines.append("\nSupplementary article URLs (use when relevant to transcript):")
            for key, info in digest_mustread_urls.items():
                source_lines.append(f"  - {info['title']}: {info['url']}")
        known_sources = "\n".join(source_lines)

    known_sources_section = ""
    if known_sources:
        known_sources_section = f"""

KNOWN SOURCE URLs (from today's tech digest):
{known_sources}

CRITICAL: For products/tools mentioned in the transcript, ALWAYS check the known source URLs above first.
Use the exact URLs provided — do NOT make up URLs. Each topic segment should use multiple screenshots
from these sources (different pages/scroll positions) to maximize coverage.
If the same URL applies to multiple moments, set _scroll_offset to show different parts of the page
(0, 500, 1000, 1500 pixels etc.).
"""

    prompt = f"""You are a professional video editor analyzing a transcript to decide where B-roll visuals should appear.

Transcript (timestamped):
{transcript}

Total video duration: {total_duration:.1f}s
{known_sources_section}
For each visual moment, identify:
1. Products/tools/articles mentioned → category "product", source_type "screenshot"
   - You MUST provide url_hint with a REAL, valid URL (starting with https://)
   - Use URLs from the known sources above when available
   - For the same URL appearing multiple times, set _scroll_offset (0, 500, 1000...) to show different page sections
   - If you cannot determine the real URL, set source_type to "stock_footage" instead of "screenshot" and leave url_hint empty
2. Abstract concepts needing visualization → category "concept", source_type "stock_footage"
3. Data points/statistics → category "data", source_type "generated"
4. Comparisons between things → category "comparison", source_type "stock_footage"

Mark segments where the speaker's face/emotion is MORE impactful than any visual as selfie_preferred=true.
These include: personal opinions, emotional reactions, direct audience address, jokes.

Rules:
- Maximum {BROLL_MAX_VISUAL_MOMENTS} moments
- Each moment needs start/end times matching the transcript timestamps
- title: 15 chars max, 繁體中文
- search_terms: 2-3 English terms for finding stock footage/images
- priority: 1=essential (named products), 2=helpful (concepts), 3=nice-to-have
- Do NOT create visuals for the first 2.5s or last 4s (reserved for selfie)
- url_hint MUST be a real URL starting with https:// or empty string "". NEVER put search instructions, descriptions, or product names as url_hint.
- Prefer screenshots of official sources over stock footage. Each topic discussed should have AT LEAST one screenshot from an official source.
- For topics spanning 10+ seconds, create 2-3 visual moments (different URLs or different scroll positions of the same URL).

Return ONLY valid JSON array:
[
  {{
    "start": 5.2,
    "end": 12.0,
    "category": "product",
    "source_type": "screenshot",
    "title": "OpenFang 框架",
    "search_terms": ["OpenFang", "AI framework"],
    "context": "Speaker introduces OpenFang as new AI agent framework",
    "priority": 1,
    "url_hint": "https://github.com/example/openfang",
    "_scroll_offset": 0,
    "selfie_preferred": false
  }}
]"""

    try:
        from .llm import gemini_generate
        output = gemini_generate(prompt) or ""

        # Extract JSON array
        json_match = re.search(r'\[.*\]', output, re.DOTALL)
        if not json_match:
            print("  Could not parse Gemini visual analysis result")
            return []

        raw_moments = json.loads(json_match.group())
        moments = []
        for m in raw_moments:
            moments.append(VisualMoment(
                start=float(m.get("start", 0)),
                end=float(m.get("end", 0)),
                category=m.get("category", "concept"),
                source_type=m.get("source_type", "stock_footage"),
                title=m.get("title", ""),
                search_terms=m.get("search_terms", []),
                context=m.get("context", ""),
                priority=int(m.get("priority", 2)),
                url_hint=m.get("url_hint", ""),
                selfie_preferred=bool(m.get("selfie_preferred", False)),
                scroll_offset=int(m.get("_scroll_offset", 0)),
            ))

        print(f"  Extracted {len(moments)} visual moments from transcript")
        return moments[:BROLL_MAX_VISUAL_MOMENTS]

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Gemini visual analysis failed: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"  JSON parse error from Gemini: {e}")
        return []


def merge_with_script_items(
    visual_moments: List[VisualMoment],
    script_items: List[Dict],
) -> List[Dict]:
    """Merge LLM-extracted visual moments with script B-roll items.

    Script items always win within their time range (+-2s overlap).
    Visual moments fill the gaps. Deduplicates same product/tool.

    Returns unified segment list compatible with plan_broll_segments() output.
    """
    # Convert script items to segments with time ranges
    script_segments = []
    for item in script_items:
        from modules.broll import parse_timing_hint
        start = parse_timing_hint(item.get("timing_start", "")) or \
                parse_timing_hint(item.get("timing_hint", ""))
        end = parse_timing_hint(item.get("timing_end", ""))
        duration = (end - start) if (start and end and end > start) else \
                   item.get("duration", BROLL_DURATION.get(
                       item.get("broll_type", "screenshot"), 4))

        script_segments.append({
            "title": item["title"],
            "url": item.get("url", ""),
            "media_url": item.get("media_url", ""),
            "keywords": item.get("keywords", []),
            "start_hint": start,
            "source_type": item.get("broll_type", "screenshot" if item.get("url") else "stock"),
            "duration": duration,
            "text_duration": len(item.get("title", "")) * 0.15,
            "display_text": item["title"],
            "from_script": True,
        })

    # Build occupied time ranges from script items (+-2s overlap zone)
    occupied = []
    for seg in script_segments:
        occupied.append((seg["start_hint"] - 2.0, seg["start_hint"] + seg["duration"] + 2.0))

    # Track titles from script items for dedup
    script_titles = {seg["title"].lower() for seg in script_segments}

    # Convert visual moments to segments, skipping conflicts
    visual_segments = []
    for vm in visual_moments:
        if vm.selfie_preferred:
            continue

        # Dedup: skip if same title already in script
        if vm.title.lower() in script_titles:
            continue

        # Skip if overlaps with any script item time range
        overlaps = any(
            occ_start <= vm.start <= occ_end or occ_start <= vm.end <= occ_end
            for occ_start, occ_end in occupied
        )
        if overlaps:
            continue

        # Only use url_hint if it's a real URL (starts with https://)
        url = vm.url_hint if vm.url_hint.startswith("https://") else ""

        # If source_type is screenshot but no valid URL, fall back to stock_footage
        source_type = vm.source_type
        if source_type == "screenshot" and not url:
            source_type = "stock_footage"

        visual_segments.append({
            "title": vm.title,
            "url": url,
            "media_url": "",
            "keywords": vm.search_terms,
            "start_hint": vm.start,
            "source_type": source_type,
            "duration": vm.end - vm.start,
            "text_duration": len(vm.title) * 0.15,
            "display_text": vm.title,
            "from_script": False,
            "priority": vm.priority,
            "context": vm.context,
            "_scroll_offset": vm.scroll_offset,
        })

    # Combine and sort by start time
    all_segments = script_segments + visual_segments
    all_segments.sort(key=lambda s: s["start_hint"])
    return all_segments


def apply_coverage_targets(
    segments: List[Dict],
    total_duration: float,
) -> List[Dict]:
    """Prune or extend segments to hit 50-70% B-roll coverage.

    Rules:
    - First BROLL_OPENING_SELFIE seconds always selfie (face = hook)
    - Last BROLL_CLOSING_SELFIE seconds always selfie (direct audience address)
    - Minimum BROLL_SELFIE_BREATHING_MIN selfie gap between B-roll segments
    - selfie_preferred moments stay as selfie
    - If >70% → prune lowest priority moments first
    - If <50% → extend durations of existing moments
    """
    if not segments or total_duration <= 0:
        return segments

    # Enforce opening/closing selfie zones
    usable_start = BROLL_OPENING_SELFIE
    usable_end = total_duration - BROLL_CLOSING_SELFIE

    # Filter out segments outside usable zone and selfie_preferred
    filtered = []
    for seg in segments:
        # selfie_preferred moments stay as selfie (remove from B-roll)
        if seg.get("selfie_preferred", False):
            continue
        seg_end = seg["start_hint"] + seg["duration"]
        # Clamp to usable zone
        if seg["start_hint"] < usable_start:
            seg["start_hint"] = usable_start
        if seg_end > usable_end:
            seg["duration"] = usable_end - seg["start_hint"]
        if seg["duration"] > 0 and seg["start_hint"] < usable_end:
            filtered.append(seg)

    # Enforce minimum selfie breathing gap between segments
    spaced = []
    for seg in sorted(filtered, key=lambda s: s["start_hint"]):
        if spaced:
            prev_end = spaced[-1]["start_hint"] + spaced[-1]["duration"]
            gap = seg["start_hint"] - prev_end
            if gap < BROLL_SELFIE_BREATHING_MIN:
                # Push this segment later to maintain gap
                seg["start_hint"] = prev_end + BROLL_SELFIE_BREATHING_MIN
                # If pushed past usable end, skip
                if seg["start_hint"] + seg["duration"] > usable_end:
                    continue
        spaced.append(seg)

    # Calculate coverage
    def calc_coverage(segs):
        return sum(s["duration"] for s in segs) / total_duration

    coverage = calc_coverage(spaced)

    # If >70% → prune lowest priority moments first (non-script items)
    if coverage > BROLL_COVERAGE_TARGET_MAX:
        # Sort non-script items by priority (highest number = lowest priority)
        prunable = [(i, s) for i, s in enumerate(spaced) if not s.get("from_script")]
        prunable.sort(key=lambda x: -x[1].get("priority", 2))

        while calc_coverage(spaced) > BROLL_COVERAGE_TARGET_MAX and prunable:
            idx, _ = prunable.pop(0)
            spaced = [s for i, s in enumerate(spaced) if i != idx]
            # Reindex prunable
            prunable = [(i if i < idx else i - 1, s) for i, s in prunable]

    # If <50% → extend durations of existing moments (up to 2x)
    coverage = calc_coverage(spaced)
    if coverage < BROLL_COVERAGE_TARGET_MIN and spaced:
        deficit = (BROLL_COVERAGE_TARGET_MIN * total_duration) - sum(s["duration"] for s in spaced)
        per_segment_extra = deficit / len(spaced)
        for seg in spaced:
            max_extend = seg["duration"]  # at most double
            seg["duration"] += min(per_segment_extra, max_extend)

    return spaced
