import json

import pytest

from modules.pipeline_state import (
    load_json_cache,
    rebind_transcription_words,
    record_transcription_domain,
    validate_transcription_domain,
    write_json_cache,
)


def test_json_cache_reuses_only_matching_inputs(tmp_path):
    source = tmp_path / "source.mp4"
    words = tmp_path / "words.json"
    cache = tmp_path / "auto_script.json"
    source.write_bytes(b"video-v1")
    words.write_text('[{"text":"one"}]', encoding="utf-8")
    inputs = {"source": str(source), "words": str(words)}

    write_json_cache(str(cache), {"items": [{"title": "one"}]}, inputs)

    assert load_json_cache(str(cache), inputs) == {"items": [{"title": "one"}]}
    words.write_text('[{"text":"two"}]', encoding="utf-8")
    assert load_json_cache(str(cache), inputs) is None


def test_json_cache_treats_legacy_artifact_without_fingerprint_as_miss(tmp_path):
    cache = tmp_path / "visual_moments.json"
    cache.write_text(json.dumps([{"start": 1.0}]), encoding="utf-8")

    assert load_json_cache(str(cache), {"config": {"version": 1}}) is None


def test_json_cache_rejects_payload_that_does_not_match_metadata(tmp_path):
    cache = tmp_path / "auto_script.json"
    inputs = {"config": {"version": 1}}
    write_json_cache(str(cache), {"items": ["old"]}, inputs)
    cache.write_text(json.dumps({"items": ["interrupted-new"]}), encoding="utf-8")

    assert load_json_cache(str(cache), inputs) is None


def _write_transcription_inputs(tmp_path):
    media = tmp_path / "trimmed.mp4"
    timeline = tmp_path / "timeline.json"
    words = tmp_path / "words.json"
    media.write_bytes(b"trimmed-v1")
    timeline.write_text(json.dumps({
        "kind": "postprod", "total": 3.0,
        "segments": [{"id": "take-000", "file": "source.mov",
                      "start": 0.0, "dur": 3.0,
                      "source_start": 1.0, "source_end": 4.0}],
    }), encoding="utf-8")
    words.write_text(json.dumps([
        {"text": "原字", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")
    return media, timeline, words


def test_transcription_domain_detects_stale_media_and_timeline(tmp_path):
    media, timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    assert validate_transcription_domain(str(tmp_path))[1] is None

    media.write_bytes(b"trimmed-v2")
    assert "media fingerprint" in validate_transcription_domain(str(tmp_path))[1]
    media.write_bytes(b"trimmed-v1")
    timeline.write_text(timeline.read_text() + "\n", encoding="utf-8")
    assert "timeline fingerprint" in validate_transcription_domain(str(tmp_path))[1]


def test_transcription_domain_must_describe_current_trimmed_media(tmp_path):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    old_media = tmp_path / "old-trimmed.mp4"
    old_media.write_bytes(media.read_bytes())
    record_transcription_domain(str(tmp_path), str(old_media), str(words))

    assert "current trimmed" in validate_transcription_domain(str(tmp_path))[1]


def test_a_work_dir_transcribed_before_asr_receipts_says_how_to_recover(tmp_path):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    domain = tmp_path / "transcription_domain.json"
    evidence = json.loads(domain.read_text(encoding="utf-8"))
    del evidence["asr"]
    domain.write_text(json.dumps(evidence), encoding="utf-8")

    assert "transcribe step" in validate_transcription_domain(str(tmp_path))[1]


def test_proofread_words_can_be_rebound_to_unchanged_media_and_timeline(tmp_path):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    corrected = [{"text": "正字", "start": 0.2, "end": 0.8,
                  "confidence": 0.9}]
    words.write_text(json.dumps(corrected), encoding="utf-8")
    # transcript-proofer's output, saved as it came back
    (tmp_path / "corrections.json").write_text(json.dumps({"verdicts": [
        {"span": [0.0, 1.15], "heard": "原字", "verdict": "fix", "to": "正字",
         "evidence": "re-ran span: 正 p0.93 字 p0.97"},
        {"span": [2.0, 2.6], "heard": "其他", "verdict": "uncertain",
         "evidence": "re-ran span: p0.30"},
    ]}, ensure_ascii=False), encoding="utf-8")

    rebind_transcription_words(str(tmp_path), str(words))

    evidence, error = validate_transcription_domain(str(tmp_path))
    assert error is None
    assert evidence["words_rebound"] is True


def test_rebind_refuses_words_the_asr_never_heard_without_a_declared_correction(tmp_path):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    words.write_text(json.dumps([
        {"text": "正字", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="corrections.json"):
        rebind_transcription_words(str(tmp_path), str(words))


@pytest.mark.parametrize("evidence", [None, "", "   "])
def test_a_correction_without_evidence_declares_nothing(tmp_path, evidence):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    words.write_text(json.dumps([
        {"text": "正字", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")
    (tmp_path / "corrections.json").write_text(json.dumps([
        {"span": [0.0, 1.15], "heard": "原字", "verdict": "fix", "to": "正字",
         "evidence": evidence},
    ], ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="no evidence"):
        rebind_transcription_words(str(tmp_path), str(words))


def test_an_unapplied_fix_without_evidence_is_uncertain_not_an_error(tmp_path):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    # the proofer's JSON saved as it came back; the caller did not apply the
    # evidence-less fix, which is what SKILL.md tells it to do
    (tmp_path / "corrections.json").write_text(json.dumps({"verdicts": [
        {"span": [0.0, 1.15], "heard": "原字", "verdict": "fix", "to": "正字"},
    ]}, ensure_ascii=False), encoding="utf-8")

    rebind_transcription_words(str(tmp_path), str(words))


@pytest.mark.parametrize("span,heard", [
    ([0.0, 1.15], "原字很多"),       # not what the ASR had there
    ([False, True], "原字"),         # a span that is not a time
])
def test_a_declaration_that_does_not_describe_the_asr_there_declares_nothing(
        tmp_path, span, heard):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    words.write_text(json.dumps([
        {"text": "正字", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")
    (tmp_path / "corrections.json").write_text(json.dumps([
        {"span": span, "heard": heard, "verdict": "fix", "to": "正字",
         "evidence": "re-ran span: 正 p0.93"},
    ], ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="does not declare"):
        rebind_transcription_words(str(tmp_path), str(words))


def test_an_edit_sync_would_see_is_an_edit_the_receipt_sees(tmp_path):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    words.write_text(json.dumps([
        {"text": "C++", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")
    record_transcription_domain(str(tmp_path), str(media), str(words))
    words.write_text(json.dumps([
        {"text": "C", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="does not declare"):
        rebind_transcription_words(str(tmp_path), str(words))


@pytest.mark.parametrize("raw", ["{not json", "5", "null", '{"verdicts": null}'])
def test_a_corrections_file_that_is_not_a_verdict_list_names_itself(tmp_path, raw):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    (tmp_path / "corrections.json").write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError, match="corrections.json"):
        rebind_transcription_words(str(tmp_path), str(words))


@pytest.mark.parametrize("bad_start,bad_end", [
    (True, 0.8),
    (0.2, float("nan")),
    (0.8, 0.2),
])
def test_proofread_rebind_rejects_invalid_word_times(tmp_path, bad_start, bad_end):
    media, _timeline, words = _write_transcription_inputs(tmp_path)
    record_transcription_domain(str(tmp_path), str(media), str(words))
    words.write_text(json.dumps([
        {"text": "字", "start": bad_start, "end": bad_end, "confidence": 0.9},
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="outside the current timeline"):
        rebind_transcription_words(str(tmp_path), str(words))
