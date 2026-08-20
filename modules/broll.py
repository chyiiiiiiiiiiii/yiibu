"""B-roll asset collection: screenshots, stock video, stock photos, AI-generated images."""
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

try:
    import requests
except ImportError:                      # B-roll network features skip cleanly
    requests = None

from config import (
    AUTO_BROLL_MAX_ITEMS,
    BROLL_DURATION, BROLL_TEXT_CHAR_RATE,
    BROLL_TEXT_MIN, BROLL_TEXT_MAX,
    BROLL_PEXELS_VIDEO_QUALITY,
    BROLL_VEO_MODEL,
    BROLL_VEO_ENABLED,
    BROLL_GEMINI_IMAGE_MODEL,
    BROLL_OPENAI_IMAGE_MODEL,
    PIXABAY_VIDEO_QUALITY,
    BROLL_KEYWORD_SEARCH_WINDOW,
    BROLL_MIN_SEGMENT_DURATION,
    BROLL_REVIEW_MAX_RETRIES,
    BROLL_REVIEW_MODEL,
    BROLL_PARALLEL_WORKERS,
    BROLL_VALIDATE_RELEVANCE,
    BROLL_RELEVANCE_THRESHOLD,
    BROLL_PRE_ARRIVAL_OFFSET,
    BROLL_ALIGN_MAX_SHIFT,
    BROLL_OPENING_SELFIE,
    OUTPUT_WIDTH, OUTPUT_HEIGHT,
    SKILL_DIR,
)
from modules.types import Word, load_words
from modules.llm import resolve_gemini_key


def parse_digest_broll_urls(digest_path: str) -> List[Dict]:
    """Parse B-Roll URLs from a tech digest markdown file.

    Reads the '🎬 B-Roll 素材建議' table and extracts URLs + timing info.
    Also collects URLs from the '🔥 必讀' section as supplementary sources.

    Returns list of dicts with: title, url, timestamp, source_type.
    """
    if not digest_path or not os.path.exists(digest_path):
        return []

    with open(digest_path, "r", encoding="utf-8") as f:
        content = f.read()

    broll_items = []

    # Parse B-Roll table: | [8s] OpenClaw 漏洞 | ... | screenshot | [GitHub](url) |
    broll_pattern = re.compile(
        r'\|\s*\[(\d+)s?\]\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|\s*\[([^\]]*)\]\(([^)]+)\)\s*\|'
    )
    for m in broll_pattern.finditer(content):
        timestamp = int(m.group(1))
        topic = m.group(2).strip()
        description = m.group(3).strip()
        media_type = m.group(4).strip()
        label = m.group(5).strip()
        url = m.group(6).strip()
        if url.startswith("https://"):
            broll_items.append({
                "title": topic,
                "description": description,
                "url": url,
                "timestamp": timestamp,
                "source_type": "screenshot" if media_type == "screenshot" else media_type,
                "label": label,
            })

    # Also collect URLs from 必讀 section as supplementary sources
    mustread_pattern = re.compile(
        r'\|\s*\d+\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+?)\s*\|'
    )
    mustread_urls = {}
    for m in mustread_pattern.finditer(content):
        title = m.group(1).strip()
        url = m.group(2).strip()
        source = m.group(3).strip()
        if url.startswith("https://"):
            mustread_urls[title.lower()] = {"title": title, "url": url, "source": source}

    if broll_items:
        print(f"  Digest B-Roll: {len(broll_items)} items with URLs")
    if mustread_urls:
        print(f"  Digest must-read: {len(mustread_urls)} supplementary URLs")

    return broll_items, mustread_urls


# --- Term corrections memory ---
TERM_CORRECTIONS_PATH = os.path.join(SKILL_DIR, "term_corrections.json")


def _load_term_corrections() -> Dict:
    """Load persistent term/URL corrections from term_corrections.json."""
    if not os.path.exists(TERM_CORRECTIONS_PATH):
        return {"url_corrections": {}, "term_aliases": {}}
    try:
        with open(TERM_CORRECTIONS_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"url_corrections": {}, "term_aliases": {}}


def _apply_url_correction(seg: Dict) -> Dict:
    """Check segment URL against known corrections. Fix if title matches.

    Example: URL is claude-code but title says "OpenClaw" → swap to correct URL.
    """
    url = seg.get("url", "")
    if not url:
        return seg

    corrections = _load_term_corrections().get("url_corrections", {})
    if url not in corrections:
        return seg

    rule = corrections[url]
    title = seg.get("title", "").lower()
    keywords = [kw.lower() for kw in seg.get("keywords", [])]
    all_text = title + " " + " ".join(keywords)

    for trigger in rule.get("when_title_contains", []):
        if trigger.lower() in all_text:
            old_url = url
            seg["url"] = rule["correct_url"]
            print(f"    URL correction: {old_url} → {seg['url']}")
            print(f"    Reason: {rule.get('reason', 'known correction')}")
            return seg

    return seg


def _resolve_product_url(seg: Dict) -> str:
    """Resolve a real URL for a product/tool mentioned in the transcript.

    Uses Gemini web search to find the official URL when the LLM didn't
    provide a valid one. Returns the URL string or empty string.
    """
    title = seg.get("title", "")
    keywords = seg.get("keywords", [])
    context = seg.get("context", "")

    # Build a search query from the segment info
    search_parts = []
    if keywords:
        search_parts.extend(keywords[:2])
    if title:
        search_parts.append(title)

    search_query = " ".join(search_parts) + " official website OR github"

    prompt = (
        f"Find the official URL for this product/tool: {' '.join(keywords) if keywords else title}\n"
        f"Context: {context}\n\n"
        f"Return ONLY the URL (starting with https://). "
        f"Prefer: GitHub repo > official website > documentation page. "
        f"If you cannot find a real URL, return NONE."
    )

    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        # Extract URL from response
        url_match = re.search(r'(https://[^\s<>"\']+)', output)
        if url_match:
            url = url_match.group(1).rstrip('.')
            print(f"    Resolved URL: {url}")
            return url
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return ""


def _validate_screenshot_content(screenshot_path: str, expected_title: str) -> bool:
    """Validate screenshot content matches expected title using Gemini vision.

    Returns True if content matches or validation is unavailable.
    Returns False if content clearly doesn't match.
    """
    if not BROLL_VALIDATE_RELEVANCE:
        return True
    if not os.path.exists(screenshot_path):
        return False

    prompt = (
        f"Does this screenshot show content about \"{expected_title}\"?\n"
        f"Look at the page title, headings, and main content.\n"
        f"Reply ONLY 'yes' or 'no'."
    )

    try:
        result = subprocess.run(
            ["gemini", "-p", prompt, "--file", screenshot_path],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip().lower()
        if not output:
            return True  # Can't validate → approve
        if "no" in output and "yes" not in output:
            print(f"    Screenshot validation FAILED: content doesn't match \"{expected_title}\"")
            return False
        return True
    except Exception:
        return True  # Validation tool unavailable → approve


def log_term_correction(
    correction_type: str,
    key: str,
    value: Dict,
) -> None:
    """Persist a new correction to term_corrections.json.

    Args:
        correction_type: "url_corrections" or "term_aliases"
        key: The incorrect URL or canonical term name
        value: The correction data dict
    """
    data = _load_term_corrections()
    if correction_type not in data:
        data[correction_type] = {}
    data[correction_type][key] = value
    with open(TERM_CORRECTIONS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Logged correction: [{correction_type}] {key}")


def calculate_broll_text_duration(text: str) -> float:
    """Calculate display duration for B-roll text overlay based on character count."""
    chars = len(text)
    duration = chars * BROLL_TEXT_CHAR_RATE
    return max(BROLL_TEXT_MIN, min(BROLL_TEXT_MAX, duration))


def parse_timing_hint(hint: str) -> float:
    """Parse timing hint like '[8s]' or '[1m20s]' to seconds."""
    if not hint:
        return 0.0
    match = re.match(r'\[(?:(\d+)m)?(\d+)s\]', hint)
    if match:
        minutes = int(match.group(1) or 0)
        seconds = int(match.group(2))
        return float(minutes * 60 + seconds)
    return 0.0


def plan_broll_segments(items: List[Dict]) -> List[Dict]:
    """Convert script items into a B-roll segment plan with timing.

    Duration priority:
    1. Explicit timing_start + timing_end → computed duration
    2. Item-level 'duration' field
    3. BROLL_DURATION config fallback per type
    """
    segments = []
    for item in items:
        broll_type = item.get("broll_type", "screenshot" if item.get("url") else "stock")
        text_duration = calculate_broll_text_duration(item.get("title", ""))

        start = parse_timing_hint(item.get("timing_start", "")) or \
                parse_timing_hint(item.get("timing_hint", ""))
        end = parse_timing_hint(item.get("timing_end", ""))

        if start and end and end > start:
            duration = end - start
        elif item.get("duration"):
            duration = item["duration"]
        else:
            duration = BROLL_DURATION.get(broll_type, 4)

        segments.append({
            "title": item["title"],
            "url": item.get("url", ""),
            "media_url": item.get("media_url", ""),
            "keywords": item.get("keywords", []),
            "start_hint": start,
            "source_type": broll_type,
            "duration": duration,
            "text_duration": text_duration,
            "display_text": item["title"],
        })
    return segments


def _opencc_convert(text: str) -> str:
    """Convert simplified Chinese to traditional for fuzzy matching."""
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
        return cc.convert(text)
    except ImportError:
        return text


def align_broll_to_transcript(segments: List[Dict], words: List[Word]) -> List[Dict]:
    """Align B-roll start times to actual keyword mentions in transcript.

    Enhanced matching:
    - Multi-word sliding window: "Open Fang" matches across consecutive Word objects
    - Simplified→Traditional fuzzy match via OpenCC
    - Pre-arrival offset: visual appears BROLL_PRE_ARRIVAL_OFFSET before keyword spoken

    Falls back to the original start_hint if no keyword match is found.
    """
    if not words:
        return segments

    word_entries = [(w.text.lower(), w.start, w.end) for w in words]

    # Build multi-word concatenations for sliding window matching
    # window_texts[i] = concatenation of words[i:i+window_size]
    max_window = 4  # match up to 4 consecutive words
    windows = []
    for size in range(1, max_window + 1):
        for i in range(len(word_entries) - size + 1):
            concat = "".join(word_entries[j][0] for j in range(i, i + size))
            windows.append((concat, word_entries[i][1], word_entries[i + size - 1][2]))

    for seg in segments:
        keywords = seg.get("keywords", [])
        if not keywords:
            continue

        original_start = seg["start_hint"]
        best_match_start = None

        for kw in keywords:
            kw_lower = kw.lower()
            # Also try traditional Chinese conversion of keyword
            kw_trad = _opencc_convert(kw_lower)

            for text, start, end in windows:
                # Require minimum 2-char overlap to avoid false single-char matches
                # e.g. "l" (from "Latent") matching "remote control"
                matched = False
                if len(kw_lower) >= 2 and len(text) >= 2:
                    matched = (
                        kw_lower in text or text in kw_lower or
                        (kw_trad != kw_lower and (kw_trad in text or text in kw_trad))
                    )
                if matched:
                    if best_match_start is None:
                        best_match_start = start
                    elif abs(start - original_start) < abs(best_match_start - original_start):
                        best_match_start = start
            if best_match_start is not None:
                break  # Found a match with the first keyword, use it

        if best_match_start is not None:
            # Apply pre-arrival offset: show visual slightly before keyword
            # But never before BROLL_OPENING_SELFIE (first 2.5s must be selfie)
            aligned = best_match_start - BROLL_PRE_ARRIVAL_OFFSET
            # Bound shift: don't move more than BROLL_ALIGN_MAX_SHIFT from LLM timing
            if abs(aligned - original_start) <= BROLL_ALIGN_MAX_SHIFT:
                seg["start_hint"] = max(BROLL_OPENING_SELFIE, aligned)

    return segments


def sequence_overlapping_segments(segments: List[Dict]) -> List[Dict]:
    """Distribute multiple segments at the same timestamp into sequential slots.

    Groups segments by start_hint (within 0.5s tolerance), then distributes
    them across the time window so they play one after another instead of
    overlapping.
    """
    if not segments:
        return segments

    # Sort by start_hint
    segments = sorted(segments, key=lambda s: s["start_hint"])

    # Group segments that start within 0.5s of each other
    groups = []
    current_group = [segments[0]]
    for seg in segments[1:]:
        if abs(seg["start_hint"] - current_group[0]["start_hint"]) < 0.5:
            current_group.append(seg)
        else:
            groups.append(current_group)
            current_group = [seg]
    groups.append(current_group)

    result = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
            continue

        # Multiple items at same timestamp: distribute sequentially
        group_start = group[0]["start_hint"]
        total_available = sum(seg["duration"] for seg in group)

        offset = group_start
        for seg in group:
            per_item = max(BROLL_MIN_SEGMENT_DURATION, seg["duration"])
            seg["start_hint"] = offset
            seg["duration"] = per_item
            result.append(seg)
            offset += per_item

    return sorted(result, key=lambda s: s["start_hint"])


# Transition phrases that signal a new topic (shared with bgm.py logic)
_TOPIC_TRANSITION_PHRASES = [
    "第二個", "第二,", "第三個", "第三,",
    "最後,", "最後", "接下來", "再來",
]


def clamp_broll_to_topic_boundaries(
    segments: List[Dict], words: List[Word],
) -> List[Dict]:
    """Prevent B-roll from crossing topic/section boundaries.

    Scans the transcript for transition phrases (e.g. "第二個", "接下來")
    and treats them as topic boundaries. If a B-roll segment's end time
    (start_hint + duration) would extend past a boundary, the duration is
    clamped so the B-roll disappears before the new topic begins.

    Segments clamped below BROLL_MIN_SEGMENT_DURATION are dropped.
    """
    if not words or not segments:
        return segments

    # Detect boundary timestamps from transcript transition markers
    boundaries = []
    for w in words:
        text = w.text.strip().rstrip(",，。")
        if text in [p.rstrip(",，。") for p in _TOPIC_TRANSITION_PHRASES]:
            boundaries.append(w.start)

    if not boundaries:
        return segments

    boundaries.sort()
    buffer = 0.3  # end B-roll 0.3s before the transition phrase

    clamped = []
    for seg in segments:
        start = seg["start_hint"]
        end = start + seg["duration"]

        # Find the next topic boundary after this segment starts
        next_boundary = None
        for b in boundaries:
            if b > start + 0.5:  # boundary must be meaningfully after start
                next_boundary = b
                break

        if next_boundary is not None and end > next_boundary - buffer:
            new_duration = (next_boundary - buffer) - start
            if new_duration < BROLL_MIN_SEGMENT_DURATION:
                # Too short after clamping — drop the segment
                continue
            seg["duration"] = round(new_duration, 2)

        clamped.append(seg)

    dropped = len(segments) - len(clamped)
    if dropped or any(True for s, o in zip(clamped, segments) if s.get("_clamped")):
        print(f"  Topic boundary clamping: {len(boundaries)} boundary(ies) detected"
              f"{f', {dropped} segment(s) dropped' if dropped else ''}")

    return clamped


def _is_public_http_url(url: str) -> bool:
    """Reject URLs that could reach localhost or private networks.

    The URL comes from an LLM (url_hint) or a resolver, not from the user, so a
    hallucinated or poisoned value must not point the headless browser at
    127.0.0.1, RFC1918 space, or link-local metadata endpoints. Hostname-level
    check only (no DNS resolution) — enough for a local single-user tool.
    """
    from urllib.parse import urlparse
    import ipaddress
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        host = u.hostname.lower()
        if host in ("localhost",) or host.endswith((".local", ".internal")):
            return False
        try:
            ip = ipaddress.ip_address(host)
            return not (ip.is_private or ip.is_loopback or ip.is_link_local
                        or ip.is_reserved or ip.is_multicast)
        except ValueError:
            return True   # a normal domain name
    except Exception:                                          # noqa: BLE001
        return False


def capture_screenshot(url: str, output_path: str, scroll_y: int = 0) -> bool:
    """Capture a screenshot of a URL using Playwright (9:16 viewport).

    Args:
        scroll_y: Scroll down by this many pixels before capture.
            Used to show different content when the same URL appears multiple times.
    """
    try:
        if not _is_public_http_url(url):
            print(f"  Screenshot blocked (non-public URL): {url[:100]}")
            return False
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)  # Allow JS rendering
            if scroll_y > 0:
                page.evaluate(f"window.scrollTo(0, {scroll_y})")
                page.wait_for_timeout(500)
            page.screenshot(path=output_path, full_page=False)
            browser.close()
        return True
    except Exception as e:
        print(f"  Screenshot failed for {url}: {e}")
        return False


def _load_pexels_key() -> str:
    """Load Pexels API key: PEXELS_API_KEY env var, else <skill root>/.env.pexels.

    Returns empty string if unavailable. The path is relative to wherever the
    skill is cloned — a hardcoded install path silently killed stock B-roll for
    anyone who cloned to a different folder.
    """
    if requests is None:
        print("  requests not installed — stock B-roll skipped.")
        return ""
    env = os.environ.get("PEXELS_API_KEY", "").strip()
    if env:
        return env
    api_key_path = os.path.join(SKILL_DIR, ".env.pexels")
    if not os.path.exists(api_key_path):
        print("  Pexels API key not found at .env.pexels. Skipping.")
        return ""
    with open(api_key_path, "r") as f:
        return f.read().strip()


def search_pexels_video(query: str, output_path: str) -> bool:
    """Search Pexels for a portrait HD video. Download first matching result.

    Filters for portrait orientation (height > width) since the Pexels video API
    does not support an orientation parameter directly.
    """
    api_key = _load_pexels_key()
    if not api_key:
        return False

    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 5},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"  Pexels Video API error: {resp.status_code}")
        return False

    data = resp.json()
    if not data.get("videos"):
        print(f"  No Pexels video results for: {query}")
        return False

    # Filter for portrait videos (height > width)
    portrait_videos = [v for v in data["videos"] if v["height"] > v["width"]]
    if not portrait_videos:
        print(f"  No portrait Pexels videos for: {query}")
        return False

    # Pick the best quality video file matching preferred quality
    video = portrait_videos[0]
    video_files = video.get("video_files", [])
    chosen = None
    for vf in video_files:
        if vf.get("quality") == BROLL_PEXELS_VIDEO_QUALITY and vf.get("height", 0) > vf.get("width", 0):
            chosen = vf
            break
    # Fallback: pick any portrait file
    if not chosen:
        for vf in video_files:
            if vf.get("height", 0) > vf.get("width", 0):
                chosen = vf
                break
    if not chosen and video_files:
        chosen = video_files[0]
    if not chosen:
        return False

    print(f"  Downloading Pexels video: {chosen.get('link', '?')}")
    vid_resp = requests.get(chosen["link"], timeout=30)
    with open(output_path, "wb") as f:
        f.write(vid_resp.content)
    return True


def search_pexels(query: str, output_path: str) -> bool:
    """Search Pexels for a relevant portrait image. Download first result."""
    api_key = _load_pexels_key()
    if not api_key:
        return False

    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 1, "orientation": "portrait"},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"  Pexels API error: {resp.status_code}")
        return False

    data = resp.json()
    if not data.get("photos"):
        print(f"  No Pexels results for: {query}")
        return False

    photo_url = data["photos"][0]["src"]["portrait"]
    img_resp = requests.get(photo_url, timeout=15)
    with open(output_path, "wb") as f:
        f.write(img_resp.content)
    return True


def _load_pixabay_key() -> str:
    """Load Pixabay API key: PIXABAY_API_KEY env var, else <skill root>/.env.pixabay.

    Returns empty string if unavailable. Same install-path rule as
    _load_pexels_key.
    """
    if requests is None:
        print("  requests not installed — stock B-roll skipped.")
        return ""
    env = os.environ.get("PIXABAY_API_KEY", "").strip()
    if env:
        return env
    api_key_path = os.path.join(SKILL_DIR, ".env.pixabay")
    if not os.path.exists(api_key_path):
        print("  Pixabay API key not found at .env.pixabay. Skipping.")
        return ""
    with open(api_key_path, "r") as f:
        return f.read().strip()


def search_pixabay_video(query: str, output_path: str) -> bool:
    """Search Pixabay for a portrait video. Download first matching result."""
    api_key = _load_pixabay_key()
    if not api_key:
        return False

    resp = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": api_key, "q": query, "per_page": 5, "video_type": "film"},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"  Pixabay Video API error: {resp.status_code}")
        return False

    data = resp.json()
    hits = data.get("hits", [])
    if not hits:
        print(f"  No Pixabay video results for: {query}")
        return False

    # Prefer portrait videos
    for hit in hits:
        videos = hit.get("videos", {})
        chosen = videos.get(PIXABAY_VIDEO_QUALITY, videos.get("medium", {}))
        if not chosen or not chosen.get("url"):
            continue
        # Check orientation (portrait = height > width)
        if chosen.get("height", 0) > chosen.get("width", 0):
            print(f"  Downloading Pixabay video: {chosen['url'][:60]}...")
            vid_resp = requests.get(chosen["url"], timeout=30)
            with open(output_path, "wb") as f:
                f.write(vid_resp.content)
            return True

    # Fallback: any video if no portrait found
    first_hit = hits[0]
    videos = first_hit.get("videos", {})
    chosen = videos.get(PIXABAY_VIDEO_QUALITY, videos.get("medium", {}))
    if chosen and chosen.get("url"):
        print(f"  Downloading Pixabay video (non-portrait): {chosen['url'][:60]}...")
        vid_resp = requests.get(chosen["url"], timeout=30)
        with open(output_path, "wb") as f:
            f.write(vid_resp.content)
        return True

    return False


def search_pixabay(query: str, output_path: str) -> bool:
    """Search Pixabay for a relevant portrait image. Download first result."""
    api_key = _load_pixabay_key()
    if not api_key:
        return False

    resp = requests.get(
        "https://pixabay.com/api/",
        params={
            "key": api_key, "q": query, "per_page": 5,
            "orientation": "vertical", "image_type": "photo",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"  Pixabay API error: {resp.status_code}")
        return False

    data = resp.json()
    hits = data.get("hits", [])
    if not hits:
        print(f"  No Pixabay photo results for: {query}")
        return False

    photo_url = hits[0].get("largeImageURL", hits[0].get("webformatURL", ""))
    if not photo_url:
        return False

    img_resp = requests.get(photo_url, timeout=15)
    with open(output_path, "wb") as f:
        f.write(img_resp.content)
    return True


def review_generated_asset(asset_path: str, topic_title: str, keywords: List[str]) -> bool:
    """Review an AI-generated B-roll asset using Gemini vision.

    Checks if the generated image/video is contextually appropriate,
    readable, and matches the intended topic. Returns True if approved.
    """
    if not os.path.exists(asset_path):
        return False

    prompt = (
        f"Review this image for use as B-roll in a tech news video.\n"
        f"Topic: {topic_title}\n"
        f"Keywords: {', '.join(keywords)}\n\n"
        f"Check these criteria:\n"
        f"1. Does the image relate to the topic?\n"
        f"2. Is any text in the image readable and correct?\n"
        f"3. Is the image visually clean (no artifacts, distortion, weird faces)?\n"
        f"4. Would a viewer understand the connection to the topic?\n\n"
        f"Reply with ONLY 'APPROVED' or 'REJECTED: <brief reason>'."
    )

    # Try Gemini CLI with image input
    try:
        result = subprocess.run(
            ["gemini", "-p", prompt, "--file", asset_path],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            print(f"    Review: skipped (empty response)")
            return True  # Can't review = approve by default
        if "APPROVED" in output.upper():
            print(f"    Review: APPROVED")
            return True
        else:
            print(f"    Review: {output}")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"    Review skipped (Gemini unavailable): {e}")
        return True


def _get_venv_python() -> str:
    """Return path to .venv python3 for SDK calls (has google-genai installed)."""
    venv_python = os.path.join(SKILL_DIR, ".venv", "bin", "python3")
    if os.path.exists(venv_python):
        return venv_python
    return "python3"


_VEO_SKIP_ANNOUNCED = False


def _veo_unavailable_reason() -> str:
    """Why the paid rung cannot run this time — "" means it can.

    Checked in the PARENT before anything is launched. Without this, a run with
    no key spawns one subprocess per segment, waits for the SDK to fail, and
    prints an authentication traceback each time — for a user who simply has not
    configured a paid key, which is a normal way to use this skill.
    """
    if not BROLL_VEO_ENABLED:
        return "YIIBU_VEO_ENABLED=0"
    if not resolve_gemini_key():
        return ("no Gemini API key — Veo is paid and needs your own key "
                "(YIIBU_GEMINI_KEY, or GEMINI_API_KEY in ~/.zshrc)")
    return ""


def generate_video_veo(prompt: str, output_path: str, duration: int = 5) -> bool:
    """Generate a short video using Google Veo 3 via the .venv Python SDK.

    THE FIRST AND ONLY PAID RUNG of the B-roll ladder. Generated video is matched
    to the segment's actual content, where stock is at best thematically close,
    so it is tried before the free sources on purpose — but it costs money per
    call and requires the user's own key. Everything below it is free.

    Runs as a subprocess using the skill's .venv (which has google-genai).
    Returns True if video was successfully generated and saved; False skips to
    the next rung, which is the normal outcome when no key is configured.
    """
    global _VEO_SKIP_ANNOUNCED
    reason = _veo_unavailable_reason()
    if reason:
        # Once per run, not once per segment.
        if not _VEO_SKIP_ANNOUNCED:
            print(f"  Veo video generation skipped ({reason}) — "
                  f"falling back to free stock and image sources")
            _VEO_SKIP_ANNOUNCED = True
        return False

    venv_python = _get_venv_python()

    # Write script to temp file to avoid shell escaping issues
    import tempfile
    script_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, dir=os.path.dirname(output_path)
    )
    script_file.write(f'''import time, sys, json, os, requests
from google import genai
from google.genai import types

prompt_text = json.loads({json.dumps(json.dumps(prompt + ". 9:16 portrait format, clean tech style."))})
output_path = json.loads({json.dumps(json.dumps(output_path))})

client = genai.Client()
operation = client.models.generate_videos(
    model={json.dumps(BROLL_VEO_MODEL)},
    source=types.GenerateVideosSource(prompt=prompt_text),
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",
        number_of_videos=1,
        person_generation="allow_all",
    ),
)

for _ in range(36):
    if operation.done:
        break
    time.sleep(5)
    operation = client.operations.get(operation)

if not operation.done:
    print("TIMEOUT", file=sys.stderr)
    sys.exit(1)

if not operation.result or not operation.result.generated_videos:
    print("NO_RESULT", file=sys.stderr)
    sys.exit(1)

video = operation.result.generated_videos[0]
if video.video and video.video.uri:
    download_url = video.video.uri
    downloaded = False

    # Try 1: ADC bearer token (same auth as Gemini image SDK)
    try:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest
        creds, _ = google.auth.default()
        creds.refresh(AuthRequest())
        headers = {{"Authorization": f"Bearer {{creds.token}}"}}
        resp = requests.get(download_url, headers=headers, timeout=60)
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(resp.content)
            print("OK")
            downloaded = True
        else:
            print(f"ADC_DOWNLOAD_{{resp.status_code}}, trying API key...", file=sys.stderr)
    except Exception as e:
        print(f"ADC_FAILED:{{e}}, trying API key...", file=sys.stderr)

    # Try 2: API key in URL (fallback)
    if not downloaded:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            try:
                api_key = client._api_client._api_key or ""
            except Exception:
                api_key = ""
        if api_key and "key=" not in download_url:
            sep = "&" if "?" in download_url else "?"
            download_url = f"{{download_url}}{{sep}}key={{api_key}}"
        resp = requests.get(download_url, timeout=60)
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(resp.content)
            print("OK")
        else:
            print(f"DOWNLOAD_FAILED:{{resp.status_code}}", file=sys.stderr)
            sys.exit(1)
elif video.video and video.video.video_bytes:
    with open(output_path, "wb") as f:
        f.write(video.video.video_bytes)
    print("OK")
else:
    print("NO_VIDEO", file=sys.stderr)
    sys.exit(1)
''')
    script_path = script_file.name
    script_file.close()

    try:
        # Pass the key EXPLICITLY. resolve_gemini_key() also reads ~/.zshrc, which
        # a child interpreter never sees on its own — so a headless or launchd run
        # would authenticate as nobody and fail on every segment while the user
        # believes the key is configured.
        veo_env = {**os.environ, "GEMINI_API_KEY": resolve_gemini_key()}
        result = subprocess.run(
            [venv_python, script_path],
            capture_output=True, text=True, timeout=200, env=veo_env,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"  Generated video via Veo 3: {output_path} ({size_mb:.1f} MB)")
            return True
        else:
            stderr = result.stderr.strip()
            print(f"  Veo 3 generation failed: {stderr[-200:] if stderr else 'unknown error'}")
    except subprocess.TimeoutExpired:
        print(f"  Veo 3 generation timed out (>200s)")
    except Exception as e:
        print(f"  Veo 3 generation error: {e}")
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)

    return False


def generate_image(prompt: str, output_path: str) -> bool:
    """Generate an image using Gemini SDK via .venv subprocess, with CLI fallback.

    Uses the skill's .venv Python (which has google-genai installed) to call
    the Gemini image generation API. Falls back to Gemini CLI if SDK fails.
    """
    venv_python = _get_venv_python()

    # Approach 1: google-genai Python SDK via .venv subprocess (temp file for safe escaping)
    import tempfile
    safe_prompt = json.dumps(prompt + ". 9:16 portrait format, clean tech style. Output only the image.")
    safe_output = json.dumps(output_path)
    script_content = f'''import json
from google import genai
from google.genai import types

prompt_text = json.loads({json.dumps(safe_prompt)})
out_path = json.loads({json.dumps(safe_output)})

client = genai.Client()
response = client.models.generate_content(
    model={json.dumps(BROLL_GEMINI_IMAGE_MODEL)},
    contents="Generate a 9:16 portrait illustration about: " + prompt_text,
    config=types.GenerateContentConfig(
        response_modalities=["IMAGE"],
    ),
)
if response.candidates:
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            with open(out_path, "wb") as f:
                f.write(part.inline_data.data)
            print("OK")
            break
'''
    script_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, dir=os.path.dirname(output_path) or '.'
    )
    script_file.write(script_content)
    script_path = script_file.name
    script_file.close()

    try:
        result = subprocess.run(
            [venv_python, script_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            print(f"  Generated image via Gemini SDK: {output_path}")
            return True
        else:
            stderr = result.stderr.strip()
            if stderr:
                print(f"  Gemini SDK image generation failed: {stderr[:200]}")
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"  Gemini SDK image generation error: {e}")
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)

    # Approach 2: OpenAI gpt-image fallback (replaces the old `gemini -p` CLI
    # fallback, which is both policy-prohibited and broken)
    if _generate_image_openai(prompt, output_path):
        return True

    return False


def _resolve_openai_key() -> str:
    """YIIBU_OPENAI_KEY override, then ~/.zshrc's OPENAI_API_KEY, then env."""
    override = os.environ.get("YIIBU_OPENAI_KEY")
    if override:
        return override
    try:
        import re as _re
        with open(os.path.expanduser("~/.zshrc"), encoding="utf-8") as f:
            key = ""
            for line in f:
                m = _re.match(r'\s*export\s+OPENAI_API_KEY=["\']?([^"\'\s]+)', line)
                if m:
                    key = m.group(1)  # last wins
            if key:
                return key
    except OSError:
        pass
    return os.environ.get("OPENAI_API_KEY", "")


def _generate_image_openai(prompt: str, output_path: str) -> bool:
    """Second image fallback: OpenAI images API (model: BROLL_OPENAI_IMAGE_MODEL).

    Request shape mirrors the image-gen skill's openai backend: 9:16 -> 1024x1536,
    quality medium, b64 response decoded to output_path. Fails safe on any error.
    """
    api_key = _resolve_openai_key()
    if not api_key:
        print("  OpenAI image fallback skipped: no API key")
        return False
    try:
        import base64
        import requests
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": BROLL_OPENAI_IMAGE_MODEL,
                  "prompt": prompt + ". 9:16 portrait format, clean tech style.",
                  "n": 1, "size": "1024x1536", "quality": "medium"},
            timeout=300,
        )
        if resp.status_code != 200:
            print(f"  OpenAI image fallback failed: HTTP {resp.status_code}: "
                  f"{resp.text[:200]}")
            return False
        data = resp.json().get("data", [])
        b64 = data[0].get("b64_json") if data else None
        if not b64:
            print("  OpenAI image fallback: empty response")
            return False
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"  Generated image via OpenAI {BROLL_OPENAI_IMAGE_MODEL}: {output_path}")
        return True
    except Exception as e:                                     # noqa: BLE001
        print(f"  OpenAI image fallback error: {e}")
        return False


def _build_timestamped_transcript(words) -> str:
    """Format words into timestamped transcript lines: [M:SS] text."""
    lines = []
    current_line = []
    current_start = 0.0
    for w in words:
        if not current_line:
            current_start = w.start
        current_line.append(w.text)
        # Break at ~80 chars or sentence-ending punctuation
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


def _fetch_tweet_media(username: str, tweet_id: str) -> dict:
    """Fetch media from a tweet via vxtwitter API.

    Returns dict with media_url, media_type ('video'|'image'),
    or empty dict if no media found.
    """
    try:
        vx_url = f"https://api.vxtwitter.com/{username}/status/{tweet_id}"
        resp = requests.get(vx_url, timeout=10)
        if resp.status_code != 200:
            return {}

        data = resp.json()
        media = data.get("media_extended", [])
        if not media:
            return {}

        # Prefer video over image
        for m in media:
            if isinstance(m, dict) and m.get("type") == "video":
                return {"media_url": m["url"], "media_type": "video"}
        for m in media:
            if isinstance(m, dict) and m.get("type") == "image":
                return {"media_url": m["url"], "media_type": "image"}

        return {}
    except Exception as e:
        print(f"    vxtwitter fetch failed: {e}")
        return {}



def auto_generate_broll_items(words_path: str) -> Dict:
    """Extract topics from transcript, then prompt user for source URLs.

    Phase 1: Gemini extracts named products/tools/demos + timing from transcript.
    Phase 2: User provides source URLs (tweet or website) for each topic.
    Items without URLs are skipped (no stock footage fallback).

    Returns dict with 'items' and 'tech_keywords' matching script JSON format.
    """
    words = load_words(words_path)
    transcript = _build_timestamped_transcript(words)

    prompt = f"""Analyze this video transcript and extract key topics that reference specific products, tools, demos, or announcements suitable for B-roll visuals.

Transcript:
{transcript}

IMPORTANT: Only extract topics where a specific named product/tool/demo is mentioned.
Do NOT extract abstract concepts (e.g. "AI future", "multimodal interaction").
We need real, searchable sources — not generic filler.

For each topic, return:
- title: display text for overlay (≤15 chars, 繁體中文)
- search_name: the specific product/tool/person name (English)
- keywords: 2-3 English terms describing the topic
- timing_start: when the topic discussion STARTS, in [Xs] format (e.g. [4s], [1m20s])
- timing_end: when the topic discussion ENDS, in [Xs] format

The B-roll should cover the ENTIRE segment where the topic is discussed, not just a brief moment.

Also extract tech_keywords: list of technical terms mentioned (for subtitle highlighting).

Return ONLY valid JSON in this format:
{{
  "items": [
    {{"title": "...", "search_name": "...", "keywords": ["...", "..."], "timing_start": "[Xs]", "timing_end": "[Xs]"}}
  ],
  "tech_keywords": ["term1", "term2"]
}}"""

    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True, text=True, timeout=90,
        )
        output = result.stdout.strip()
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if not json_match:
            print("  Could not parse Gemini topic extraction result")
            return {"items": [], "tech_keywords": []}

        data = json.loads(json_match.group())
        items = data.get("items", [])
        tech_keywords = data.get("tech_keywords", [])

        print(f"  Extracted {len(items)} topics from transcript:")
        for i, item in enumerate(items):
            print(f"    [{i}] {item.get('title', '?')} — {item.get('search_name', '?')} {item.get('timing_hint', '')}")

        # Phase 2: Prompt user for source URLs
        print("\n  Provide source URLs for each topic (tweet URL or website URL).")
        print("  Press Enter to skip a topic (no B-roll will be shown).\n")

        resolved = []
        for i, item in enumerate(items):
            try:
                url_input = input(f"  [{i}] {item['title']} URL: ").strip()
            except EOFError:
                url_input = ""

            if not url_input:
                print(f"       → Skipped")
                continue

            # Detect if it's a tweet URL
            tweet_match = re.search(r'https?://(?:x|twitter)\.com/(\w+)/status/(\d+)', url_input)
            if tweet_match:
                username = tweet_match.group(1)
                tweet_id = tweet_match.group(2)
                # Fetch media via vxtwitter API
                media = _fetch_tweet_media(username, tweet_id)
                if media:
                    item["broll_type"] = f"tweet_{media['media_type']}"
                    item["media_url"] = media["media_url"]
                    item["tweet_url"] = f"https://x.com/{username}/status/{tweet_id}"
                    print(f"       → Tweet {media['media_type']}: {media['media_url'][:60]}...")
                    resolved.append(item)
                else:
                    print(f"       → No media found in tweet, skipping")
            else:
                # Website URL → screenshot
                item["broll_type"] = "screenshot"
                item["url"] = url_input
                print(f"       → Screenshot: {url_input}")
                resolved.append(item)

        skipped = len(items) - len(resolved)
        if skipped:
            print(f"\n  Result: {len(resolved)} with sources, {skipped} skipped")

        return {"items": resolved, "tech_keywords": tech_keywords}

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Gemini topic extraction failed: {e}")
        return {"items": [], "tech_keywords": []}
    except json.JSONDecodeError as e:
        print(f"  JSON parse error from Gemini: {e}")
        return {"items": [], "tech_keywords": []}


def _build_search_queries(seg: Dict) -> List[str]:
    """Build tiered search queries from specific to broad.

    Strategy:
    1. Original keywords joined (e.g. "vinext framework")
    2. Each keyword individually (e.g. "vinext", then "framework")
    3. Semantic broadening — keywords + context hint (e.g. "framework coding")
    4. Category fallback — generic visual for the domain

    This avoids both extremes: niche terms that return nothing,
    and generic "technology" queries that look the same every time.
    """
    keywords = seg.get("search_terms") or seg.get("keywords", [])
    title = seg.get("title", "")

    # Mapping from domain hints to visually useful broad terms
    DOMAIN_HINTS = {
        "ai": "artificial intelligence neural network",
        "llm": "artificial intelligence language model",
        "agent": "AI robot automation",
        "framework": "software development coding",
        "rust": "programming code rust",
        "database": "database server data",
        "security": "cybersecurity digital lock",
        "cloud": "cloud computing server",
        "mobile": "smartphone app mobile",
        "web": "web development browser",
        "game": "gaming video game controller",
        "design": "UI design interface",
        "api": "software programming interface",
        "startup": "startup business technology",
        "open source": "open source community coding",
    }

    queries = []

    # Tier 1: all keywords together
    if keywords:
        queries.append(" ".join(keywords))

    # Tier 2: individual keywords (skip single-keyword case, already covered)
    if len(keywords) > 1:
        for kw in keywords:
            if kw not in queries:
                queries.append(kw)

    # Tier 3: keyword + domain broadening
    all_text = " ".join(keywords + [title]).lower()
    for domain, broad_term in DOMAIN_HINTS.items():
        if domain in all_text:
            queries.append(broad_term)
            break
    else:
        # Default: add "technology" context to first keyword
        if keywords:
            queries.append(f"{keywords[0]} technology")

    # Tier 4: ultra-generic fallback
    queries.append("technology software coding")

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def validate_asset_relevance(
    asset_path: str,
    context: str,
    threshold: int = BROLL_RELEVANCE_THRESHOLD,
) -> bool:
    """Validate stock asset relevance using Gemini vision.

    Returns True if asset scores >= threshold (0-100).
    Only for stock footage — screenshots are inherently specific.
    Skipped if BROLL_VALIDATE_RELEVANCE is False.
    """
    if not BROLL_VALIDATE_RELEVANCE:
        return True
    if not os.path.exists(asset_path):
        return False

    prompt = (
        f"Rate how well this image/video matches this context on a scale of 0-100.\n"
        f"Context: {context}\n\n"
        f"Reply with ONLY a number (0-100)."
    )

    try:
        result = subprocess.run(
            ["gemini", "-p", prompt, "--file", asset_path],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            return True  # Can't validate → approve
        # Extract first number from response
        match = re.search(r'\d+', output)
        if match:
            score = int(match.group())
            approved = score >= threshold
            print(f"    Relevance: {score}/100 {'✓' if approved else '✗'}")
            return approved
        return True
    except Exception:
        return True  # Validation tool unavailable or error → approve


def _collect_single_segment(i: int, seg: Dict, broll_dir: str) -> Dict:
    """Collect B-roll for a single segment. Returns updated segment dict."""
    acquired = False

    # Try tweet media first (direct video/image from X/Twitter)
    if seg.get("media_url") and seg["source_type"] in ("tweet_video", "tweet_image"):
        is_video = seg["source_type"] == "tweet_video"
        ext = "mp4" if is_video else "png"
        asset_path = os.path.join(broll_dir, f"broll_{i:02d}.{ext}")
        print(f"  [{i}] Downloading tweet {'video' if is_video else 'image'}: {seg['media_url'][:80]}...")
        try:
            resp = requests.get(seg["media_url"], timeout=60)
            if resp.status_code == 200:
                with open(asset_path, "wb") as f:
                    f.write(resp.content)
                seg["asset_path"] = asset_path
                seg["asset_type"] = "video" if is_video else "image"
                acquired = True
                print(f"  [{i}] Downloaded: {os.path.getsize(asset_path) / 1024 / 1024:.1f} MB")
        except Exception as e:
            print(f"  [{i}] Tweet media download failed: {e}")

    # Resolve URL for screenshot/product types that lack a valid URL
    if not acquired and seg["source_type"] in ("screenshot", "product"):
        url = seg.get("url", "")
        if not url or not url.startswith("https://"):
            print(f"  [{i}] No valid URL for screenshot — resolving via web search...")
            resolved = _resolve_product_url(seg)
            if resolved:
                seg["url"] = resolved
                seg["source_type"] = "screenshot"  # Ensure type is screenshot

    # Try screenshot (if URL available and type is screenshot/product)
    if not acquired and seg.get("url") and seg.get("url", "").startswith("https://") and seg["source_type"] in ("screenshot", "product"):
        # Apply URL corrections from term_corrections.json
        seg = _apply_url_correction(seg)

        asset_path = os.path.join(broll_dir, f"broll_{i:02d}.png")
        scroll_y = seg.get("_scroll_offset", 0)
        scroll_info = f" (scroll={scroll_y}px)" if scroll_y else ""
        print(f"  [{i}] Capturing screenshot{scroll_info}: {seg['url']}")
        acquired = capture_screenshot(seg["url"], asset_path, scroll_y=scroll_y)
        if acquired:
            # Validate screenshot content matches expected title
            if _validate_screenshot_content(asset_path, seg.get("title", "")):
                seg["asset_path"] = asset_path
                seg["asset_type"] = "image"
            else:
                print(f"  [{i}] Screenshot content mismatch — falling through to next source")
                os.remove(asset_path)
                acquired = False

    # Veo 3 FIRST — PAID, and deliberately ahead of the free rungs: generated
    # video is matched to this segment's content where stock is only
    # thematically close. Skips itself cleanly when no key is configured.
    if not acquired:
        keywords = seg.get("keywords", [])
        context = seg.get("context", seg.get("title", ""))
        kw_str = ", ".join(keywords) if keywords else ""
        # Build a vivid, scene-first prompt so the video opens with the key visual immediately
        veo_prompt = (
            f"Opening shot immediately shows the main subject. "
            f"Topic: {context}. "
            f"{f'Key elements: {kw_str}. ' if kw_str else ''}"
            f"Show a concrete, recognizable scene that instantly communicates the topic — "
            f"use real-world settings (office, screen, device, workspace) not abstract graphics. "
            f"Camera slowly pushes in. Cinematic lighting, shallow depth of field. "
            f"9:16 portrait format. No text, no words, no Chinese characters, no UI overlays, visual imagery only."
        )
        asset_path = os.path.join(broll_dir, f"broll_{i:02d}_veo.mp4")
        print(f"  [{i}] Generating video via Veo 3: {veo_prompt[:80]}")
        if generate_video_veo(veo_prompt, asset_path, duration=5):
            seg["asset_path"] = asset_path
            seg["asset_type"] = "video"
            acquired = True

    # Fallback: stock video/photo with tiered queries
    # Also allow screenshot/product types to try stock search if screenshot failed
    if not acquired:
        queries = _build_search_queries(seg)
        context_desc = seg.get("context", seg.get("title", ""))
        video_searchers = [
            ("Pexels video", search_pexels_video),
            ("Pixabay video", search_pixabay_video),
        ]
        photo_searchers = [
            ("Pexels photo", search_pexels),
            ("Pixabay photo", search_pixabay),
        ]

        # Phase 1: try each query across video sources
        for query in queries:
            if acquired:
                break
            for label, search_fn in video_searchers:
                asset_path = os.path.join(broll_dir, f"broll_{i:02d}.mp4")
                print(f"  [{i}] {label}: \"{query}\"")
                # A flaky network is a missed rung, never a dead pipeline.
                try:
                    hit = search_fn(query, asset_path)
                except Exception as e:
                    print(f"  [{i}] {label} failed ({e}); falling through")
                    hit = False
                if hit:
                    if validate_asset_relevance(asset_path, context_desc):
                        seg["asset_path"] = asset_path
                        seg["asset_type"] = "video"
                        acquired = True
                        break
                    else:
                        os.remove(asset_path)

        # Phase 2: try each query across photo sources
        if not acquired:
            for query in queries:
                if acquired:
                    break
                for label, search_fn in photo_searchers:
                    asset_path = os.path.join(broll_dir, f"broll_{i:02d}.png")
                    print(f"  [{i}] {label}: \"{query}\"")
                    try:
                        hit = search_fn(query, asset_path)
                    except Exception as e:
                        print(f"  [{i}] {label} failed ({e}); falling through")
                        hit = False
                    if hit:
                        if validate_asset_relevance(asset_path, context_desc):
                            seg["asset_path"] = asset_path
                            seg["asset_type"] = "image"
                            acquired = True
                            break
                        else:
                            os.remove(asset_path)

    # Fallback: Gemini image generation with review
    if not acquired:
        keywords = seg.get("keywords", [])
        for attempt in range(BROLL_REVIEW_MAX_RETRIES + 1):
            asset_path = os.path.join(broll_dir, f"broll_{i:02d}_gen{attempt}.png")
            gen_prompt = (
                f"{seg['title']}. Visual imagery only, absolutely no text, "
                f"no Chinese characters, no words, no labels. "
                f"Style: clean tech illustration, 9:16 portrait."
            ) if attempt == 0 else (
                f"{seg['title']} — {', '.join(keywords)}. "
                f"Visual imagery only, absolutely no text, no Chinese characters, "
                f"no words, no labels. Style: clean tech infographic, 9:16 portrait."
            )
            print(f"  [{i}] Generating image (attempt {attempt + 1}): {gen_prompt[:60]}")
            generated = generate_image(gen_prompt, asset_path)
            if not generated:
                continue

            print(f"  [{i}] Reviewing generated asset...")
            if review_generated_asset(asset_path, seg["title"], keywords):
                final_path = os.path.join(broll_dir, f"broll_{i:02d}.png")
                os.rename(asset_path, final_path)
                seg["asset_path"] = final_path
                seg["asset_type"] = "image"
                acquired = True
                break
            else:
                print(f"  [{i}] Review rejected, {'retrying...' if attempt < BROLL_REVIEW_MAX_RETRIES else 'giving up.'}")
                os.remove(asset_path)

    if not acquired:
        seg["asset_path"] = None
        seg["asset_type"] = None
        print(f"  [{i}] No B-roll found — will stay on selfie footage")

    return seg


def collect_broll(segments: List[Dict], work_dir: str) -> List[Dict]:
    """Collect B-roll assets in parallel with fallback chain:
    screenshot -> Pexels video -> Pexels photo -> Gemini image -> skip.

    Uses ThreadPoolExecutor for parallel collection across segments.
    Stock searches use tiered queries (specific → broad) to maximize
    relevance while ensuring results are found.

    Returns segments list updated with 'asset_path' and 'asset_type' fields.
    asset_type is either "video" or "image".
    """
    broll_dir = os.path.join(work_dir, "broll")
    os.makedirs(broll_dir, exist_ok=True)

    if not segments:
        return segments

    # Pre-compute scroll offsets for duplicate screenshot URLs
    url_counts: Dict[str, int] = {}
    for seg in segments:
        url = seg.get("url", "")
        if url and seg.get("source_type") in ("screenshot", "product"):
            count = url_counts.get(url, 0)
            if count > 0:
                seg["_scroll_offset"] = count * 800  # scroll 800px per dup
            url_counts[url] = count + 1

    print(f"  Collecting {len(segments)} B-roll assets with {BROLL_PARALLEL_WORKERS} workers...")

    with ThreadPoolExecutor(max_workers=BROLL_PARALLEL_WORKERS) as executor:
        futures = {
            executor.submit(_collect_single_segment, i, seg, broll_dir): i
            for i, seg in enumerate(segments)
        }
        results = [None] * len(segments)
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    return results
