"""Shared data types used across all modules."""
import json
from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class VisualMoment:
    """A visual moment identified by LLM analysis of the transcript."""
    start: float              # seconds
    end: float                # seconds
    category: str             # "product" | "concept" | "comparison" | "data"
    source_type: str          # "screenshot" | "stock_footage" | "generated"
    title: str                # display text (<=15 chars)
    search_terms: list = field(default_factory=list)  # English search terms
    context: str = ""         # Why this visual matters (for validation)
    priority: int = 2         # 1=essential, 2=helpful, 3=nice-to-have
    url_hint: str = ""        # URL if LLM identifies one (e.g. GitHub repo)
    selfie_preferred: bool = False  # True = speaker face more impactful here
    scroll_offset: int = 0    # Scroll offset in pixels for screenshot variety


@dataclass
class Word:
    """A single word with timing and confidence from ASR."""
    text: str
    start: float   # seconds
    end: float     # seconds
    confidence: float


def save_words(words: List[Word], output_path: str):
    """Save word list to JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([asdict(w) for w in words], f, ensure_ascii=False, indent=2)


def load_words(input_path: str) -> List[Word]:
    """Load word list from JSON."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Word(**d) for d in data]
