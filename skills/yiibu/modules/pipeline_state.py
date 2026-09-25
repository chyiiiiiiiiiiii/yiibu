"""Fingerprints for reusable pipeline artifacts."""
import hashlib
import json
import math
import os
from typing import Any, Dict, Optional


TRANSCRIPTION_DOMAIN = "transcription_domain.json"


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
    evidence = {
        "schema": 1,
        "kind": "postprod",
        "media": {"path": os.path.abspath(media_path),
                  "sha256": file_sha256(media_path)},
        "timeline": {"path": os.path.abspath(timeline_path),
                     "sha256": file_sha256(timeline_path)},
        "words": {"path": os.path.abspath(words_path),
                  "sha256": file_sha256(words_path)},
        "caption_styles": ["Default"],
        "words_rebound": words_rebound,
    }
    path = os.path.join(work_dir, TRANSCRIPTION_DOMAIN)
    _write_json_atomic(path, evidence)
    return path


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
    names = ["media", "timeline"] + (["words"] if check_words else [])
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
    return evidence, None


def rebind_transcription_words(work_dir: str, words_path: str) -> str:
    """Bind edited words to unchanged media/timeline; does not verify wording."""
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
    evidence["words"] = {
        "path": os.path.abspath(words_path),
        "sha256": file_sha256(words_path),
    }
    evidence["words_rebound"] = True
    path = os.path.join(work_dir, TRANSCRIPTION_DOMAIN)
    _write_json_atomic(path, evidence)
    return path
