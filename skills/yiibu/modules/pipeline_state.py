"""Fingerprints for reusable pipeline artifacts."""
import difflib
import hashlib
import json
import math
import os
import re
import shutil
from typing import Any, Dict, Optional


TRANSCRIPTION_DOMAIN = "transcription_domain.json"
ASR_WORDS = "words.asr.json"
CORRECTIONS = "corrections.json"
# the characters gate_sync ignores when it compares a caption with the audio;
# anything it would see as a change, the receipt has to see too
_UNSPOKEN = re.compile(r"[，、。．.！!？?；;：:「」『』（）()\s\u3000]")


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, str) and os.path.isfile(value):
        return {"path": os.path.abspath(value), "sha256": file_sha256(value)}
    if isinstance(value, dict):
        return {key: _fingerprint_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    return value


def input_fingerprint(inputs: Dict[str, Any]) -> str:
    encoded = json.dumps(
        _fingerprint_value(inputs), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metadata_path(path: str) -> str:
    return f"{path}.meta.json"


def load_json_cache(path: str, inputs: Dict[str, Any]) -> Optional[Any]:
    metadata_path = _metadata_path(path)
    if not os.path.exists(path) or not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
        if metadata.get("input_fingerprint") != input_fingerprint(inputs):
            return None
        if metadata.get("payload_sha256") != file_sha256(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def write_json_cache(path: str, value: Any, inputs: Dict[str, Any]) -> None:
    metadata_path = _metadata_path(path)
    payload_tmp = f"{path}.tmp"
    metadata_tmp = f"{metadata_path}.tmp"
    with open(payload_tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
    with open(metadata_tmp, "w", encoding="utf-8") as f:
        json.dump({
            "input_fingerprint": input_fingerprint(inputs),
            "payload_sha256": file_sha256(payload_tmp),
        }, f, indent=2)
    os.replace(payload_tmp, path)
    os.replace(metadata_tmp, metadata_path)


def _write_json_atomic(path: str, value: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def record_transcription_domain(
    work_dir: str,
    media_path: str,
    words_path: str,
    words_rebound: bool = False,
) -> str:
    timeline_path = os.path.join(work_dir, "timeline.json")
    with open(timeline_path, encoding="utf-8") as f:
        timeline = json.load(f)
    if timeline.get("kind") != "postprod":
        raise ValueError("timeline.json is not a postprod timeline")
    asr_path = os.path.join(work_dir, ASR_WORDS)
    shutil.copyfile(words_path, asr_path)
    evidence = {
        "schema": 1,
        "kind": "postprod",
        "media": {"path": os.path.abspath(media_path),
                  "sha256": file_sha256(media_path)},
        "timeline": {"path": os.path.abspath(timeline_path),
                     "sha256": file_sha256(timeline_path)},
        "words": {"path": os.path.abspath(words_path),
                  "sha256": file_sha256(words_path)},
        "asr": {"path": os.path.abspath(asr_path),
                "sha256": file_sha256(asr_path)},
        "caption_styles": ["Default"],
        "words_rebound": words_rebound,
    }
    path = os.path.join(work_dir, TRANSCRIPTION_DOMAIN)
    _write_json_atomic(path, evidence)
    return path


def _spoken(text: Any) -> str:
    return _UNSPOKEN.sub("", str(text or "")).lower()


def _timed_chars(words):
    chars, times = [], []
    for word in words:
        for ch in _spoken(word.get("text") or word.get("word")):
            chars.append(ch)
            times.append((float(word["start"]), float(word["end"])))
    return "".join(chars), times


def _corrections(work_dir: str):
    """transcript-proofer's verdicts, as returned or as a bare list; only
    `fix` and `missing` change a word."""
    path = os.path.join(work_dir, CORRECTIONS)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"{CORRECTIONS} does not parse: {e}") from e
    entries = raw.get("verdicts") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(f"{CORRECTIONS} must be a list of verdicts, or the "
                         f"proofer's {{\"verdicts\": [...]}} as returned")
    return [c for c in entries if isinstance(c, dict)
            and c.get("verdict", "fix") in ("fix", "missing")]


def _span(correction):
    span = correction.get("span")
    if (isinstance(span, list) and len(span) == 2
            and all(isinstance(t, (int, float)) and not isinstance(t, bool)
                    for t in span)):
        return span
    return None


def _declares(span, correction, old, new, start, end) -> bool:
    if span[0] > end or span[1] < start:
        return False
    return old in _spoken(correction.get("heard")) and new in _spoken(correction.get("to"))


def undeclared_edits(work_dir: str) -> Optional[str]:
    """Every word that differs from what the ASR heard must be declared.

    words.json is both what the proof-reader edits and what gate_sync treats as
    the audio. An edit nobody declared turns the evidence into the claim.
    """
    with open(os.path.join(work_dir, ASR_WORDS), encoding="utf-8") as f:
        heard, heard_times = _timed_chars(json.load(f))
    with open(os.path.join(work_dir, "words.json"), encoding="utf-8") as f:
        kept, kept_times = _timed_chars(json.load(f))
    corrections, unmeasured = [], 0
    for c in _corrections(work_dir):
        if not str(c.get("evidence") or "").strip():
            # a fix nobody measured is a guess: the proofer's own rule is that
            # the caller treats it as uncertain, so it declares nothing
            unmeasured += 1
            continue
        span = _span(c)
        if span is None:
            continue
        # it has to describe what the ASR had in that span, or it is a
        # declaration about some other transcript
        there = "".join(ch for ch, (s, e) in zip(heard, heard_times)
                        if s <= span[1] and e >= span[0])
        if _spoken(c.get("heard")) in there:
            corrections.append((span, c))
    edits = []
    matcher = difflib.SequenceMatcher(None, heard, kept, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        times = heard_times[i1:i2] + kept_times[j1:j2]
        start, end = min(s for s, _ in times), max(e for _, e in times)
        old, new = heard[i1:i2], kept[j1:j2]
        if any(_declares(span, c, old, new, start, end) for span, c in corrections):
            continue
        edits.append(f"{start:.2f}s 「{old}」→「{new}」")
    if not edits:
        return None
    return (f"words.json differs from what the ASR heard and {CORRECTIONS} does not "
            f"declare it: {'; '.join(edits[:3])}"
            + (f" (+{len(edits) - 3} more)" if len(edits) > 3 else "")
            + (f" — {unmeasured} correction(s) there carry no evidence and count "
               f"as uncertain" if unmeasured else ""))


def validate_transcription_domain(
    work_dir: str,
    check_words: bool = True,
):
    path = os.path.join(work_dir, TRANSCRIPTION_DOMAIN)
    if not os.path.exists(path):
        return None, f"no {TRANSCRIPTION_DOMAIN}"
    try:
        with open(path, encoding="utf-8") as f:
            evidence = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"{TRANSCRIPTION_DOMAIN} does not parse: {e}"
    if evidence.get("schema") != 1 or evidence.get("kind") != "postprod":
        return None, f"unsupported {TRANSCRIPTION_DOMAIN} schema"
    if "Default" not in evidence.get("caption_styles", []):
        return None, f"{TRANSCRIPTION_DOMAIN} has no postprod caption style"
    if "asr" not in evidence:
        return None, (f"{TRANSCRIPTION_DOMAIN} predates {ASR_WORDS}, so nothing "
                      f"records what the ASR heard — re-run the transcribe step")
    names = ["media", "timeline", "asr"] + (["words"] if check_words else [])
    for name in names:
        item = evidence.get(name)
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            return None, f"{TRANSCRIPTION_DOMAIN} has no {name} fingerprint"
        if not os.path.exists(item["path"]):
            return None, f"{TRANSCRIPTION_DOMAIN} {name} is missing"
        if file_sha256(item["path"]) != item["sha256"]:
            return None, f"{TRANSCRIPTION_DOMAIN} {name} fingerprint is stale"
    expected_timeline = os.path.abspath(os.path.join(work_dir, "timeline.json"))
    expected_words = os.path.abspath(os.path.join(work_dir, "words.json"))
    expected_media = os.path.abspath(os.path.join(work_dir, "trimmed.mp4"))
    if os.path.abspath(evidence["media"]["path"]) != expected_media:
        return None, f"{TRANSCRIPTION_DOMAIN} does not describe the current trimmed media"
    if os.path.abspath(evidence["timeline"]["path"]) != expected_timeline:
        return None, f"{TRANSCRIPTION_DOMAIN} points at another timeline"
    if check_words and os.path.abspath(evidence["words"]["path"]) != expected_words:
        return None, f"{TRANSCRIPTION_DOMAIN} points at another words file"
    if os.path.abspath(evidence["asr"]["path"]) != os.path.abspath(
            os.path.join(work_dir, ASR_WORDS)):
        return None, f"{TRANSCRIPTION_DOMAIN} points at another ASR record"
    if check_words:
        try:
            error = undeclared_edits(work_dir)
        except ValueError as e:
            error = str(e)
        if error:
            return None, error
    return evidence, None


def rebind_transcription_words(work_dir: str, words_path: str) -> str:
    """Bind edited words to unchanged media/timeline.

    Every word that differs from the ASR must be declared in corrections.json;
    whether a declaration's evidence holds is edit-critic's question, not this one.
    """
    evidence, error = validate_transcription_domain(work_dir, check_words=False)
    if error:
        raise ValueError(error)
    expected_words = os.path.abspath(os.path.join(work_dir, "words.json"))
    if os.path.abspath(words_path) != expected_words:
        raise ValueError("words path is not the current work directory words.json")
    with open(words_path, encoding="utf-8") as f:
        words = json.load(f)
    if not isinstance(words, list) or not words:
        raise ValueError("words.json has no words; silence has not been proven")
    from modules.transcribe import asr_sanity
    bad = asr_sanity(words)
    if bad:
        raise ValueError(f"words.json failed ASR sanity: {bad}")
    with open(os.path.join(work_dir, "timeline.json"), encoding="utf-8") as f:
        total = float(json.load(f).get("total") or 0)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("timeline.json has no finite positive total")
    for word in words:
        if not isinstance(word, dict):
            raise ValueError("words.json contains a non-object word")
        start = word.get("start")
        end = word.get("end")
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end > total + 0.15):
            raise ValueError("words.json contains a word outside the current timeline")
    error = undeclared_edits(work_dir)
    if error:
        raise ValueError(error)
    evidence["words"] = {
        "path": os.path.abspath(words_path),
        "sha256": file_sha256(words_path),
    }
    evidence["words_rebound"] = True
    path = os.path.join(work_dir, TRANSCRIPTION_DOMAIN)
    _write_json_atomic(path, evidence)
    return path
