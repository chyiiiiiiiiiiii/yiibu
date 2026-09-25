import json

import gates
from modules.pipeline_state import record_transcription_domain


def _postprod_work(tmp_path, pieces=1):
    media = tmp_path / "trimmed.mp4"
    words = tmp_path / "words.json"
    timeline = tmp_path / "timeline.json"
    media.write_bytes(b"trimmed")
    segments = []
    start = 0.0
    for i in range(pieces):
        segments.append({
            "id": f"take-{i:03d}", "file": "source.mov",
            "start": start, "dur": 2.0,
            "source_start": start, "source_end": start + 2.0,
        })
        start += 2.0
    timeline.write_text(json.dumps({
        "kind": "postprod", "total": start, "segments": segments,
    }), encoding="utf-8")
    words.write_text(json.dumps([
        {"text": "今天", "start": 0.4, "end": 1.0, "confidence": 0.9},
    ]), encoding="utf-8")
    (tmp_path / "subtitles.ass").write_text(
        "Dialogue: 0,0:00:00.20,0:00:%05.2f,Default,,0,0,0,,今天\n" % start,
        encoding="utf-8",
    )
    record_transcription_domain(str(tmp_path), str(media), str(words), words_rebound=True)
    return media, words, timeline


def test_valid_postprod_evidence_makes_default_captions_verbatim(tmp_path):
    _postprod_work(tmp_path)

    sync_fails, sync = gates.gate_sync(str(tmp_path))
    transcription_fails, transcription = gates.gate_transcription(str(tmp_path))

    assert sync_fails == []
    assert sync["verbatim_captions"] == 1
    assert transcription_fails == []
    assert transcription["domain"] == "trimmed timeline output"


def test_postprod_default_captions_activate_monologue_gate(tmp_path):
    _postprod_work(tmp_path, pieces=7)

    fails, details = gates.gate_monologue(str(tmp_path))

    assert details["takes"]["source.mov"]["pieces"] == 7
    assert any("7 pieces" in failure for failure in fails)


def test_stale_or_missing_postprod_timeline_cannot_fall_back_to_skip(tmp_path):
    _media, _words, timeline = _postprod_work(tmp_path)
    timeline.write_text(timeline.read_text() + "\n", encoding="utf-8")
    fails, _details = gates.gate_transcription(str(tmp_path))
    assert any("timeline fingerprint is stale" in failure for failure in fails)

    timeline.unlink()
    timeline_fails, _ = gates.gate_timeline(str(tmp_path))
    transcription_fails, _ = gates.gate_transcription(str(tmp_path))
    assert any("postprod" in failure for failure in timeline_fails)
    assert any("timeline is missing" in failure for failure in transcription_fails)
