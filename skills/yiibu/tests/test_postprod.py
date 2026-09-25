import json
from types import SimpleNamespace

import pytest

import postprod
from modules.pipeline_state import input_fingerprint
from modules.pipeline_state import record_transcription_domain, write_json_cache
from postprod import analysis_cache_inputs


def test_analysis_cache_inputs_track_source_script_digest_and_timeline(tmp_path):
    source = tmp_path / "source.mp4"
    words = tmp_path / "words.json"
    script = tmp_path / "script.json"
    digest = tmp_path / "digest.md"
    timeline = tmp_path / "timeline.json"
    source.write_bytes(b"source-v1")
    words.write_text("[]", encoding="utf-8")
    script.write_text('{"items": []}', encoding="utf-8")
    digest.write_text("digest-v1", encoding="utf-8")
    timeline.write_text('{"kind":"postprod","total":1}', encoding="utf-8")

    inputs = analysis_cache_inputs(
        str(source), str(words), str(script), str(digest), str(timeline),
    )
    original = input_fingerprint(inputs)
    source.write_bytes(b"source-v2")
    changed = analysis_cache_inputs(
        str(source), str(words), str(script), str(digest), str(timeline),
    )

    assert input_fingerprint(changed) != original


def _broll_args(source, work):
    return SimpleNamespace(
        input=str(source), script=None, output=str(work / "final.mp4"),
        step="broll", cuts=None, bgm=None, music=None, sfx=None,
        no_bgm=True, no_broll=False, no_sfx=True, top_title=None,
        top_title_pct=0.23, top_title_mode="persistent",
        top_title_start_dur=7.5, digest=None, title=None,
        card_subtitle=None, cta_image=None, english=None,
        work_dir=str(work),
    )


def _postprod_artifacts(source, work):
    work.mkdir()
    trimmed = work / "trimmed.mp4"
    words = work / "words.json"
    timeline = work / "timeline.json"
    trimmed.write_bytes(b"trimmed-v1")
    words.write_text(json.dumps([
        {"text": "測試", "start": 0.2, "end": 0.8, "confidence": 0.9},
    ]), encoding="utf-8")
    timeline.write_text(json.dumps({
        "kind": "postprod", "total": 2.0,
        "segments": [{"id": "take-000", "file": str(source),
                      "start": 0.0, "dur": 2.0,
                      "source_start": 0.0, "source_end": 2.0}],
    }), encoding="utf-8")
    record_transcription_domain(str(work), str(trimmed), str(words))
    return trimmed, words, timeline


def _patch_main_shell(monkeypatch, args):
    import modules.llm
    import modules.title
    monkeypatch.setattr(postprod, "parse_args", lambda: args)
    monkeypatch.setattr(modules.llm, "resolve_gemini_key", lambda: None)
    monkeypatch.setattr(modules.title, "ensure_fonts", lambda: None)
    monkeypatch.setattr(postprod, "collect_broll", lambda segments, _work: segments)


def test_broll_step_rejects_stale_media_before_expensive_analysis(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    trimmed, _words, _timeline = _postprod_artifacts(source, work)
    trimmed.write_bytes(b"trimmed-v2")
    args = _broll_args(source, work)
    _patch_main_shell(monkeypatch, args)
    monkeypatch.setattr(
        postprod, "auto_generate_broll_items",
        lambda *_a, **_k: pytest.fail("auto script ran before evidence validation"),
    )
    monkeypatch.setattr(
        postprod, "analyze_transcript_for_visuals",
        lambda *_a, **_k: pytest.fail("visual analysis ran before evidence validation"),
    )

    with pytest.raises(SystemExit) as stopped:
        postprod.main()

    assert stopped.value.code == 1


def test_broll_step_reuses_valid_fingerprinted_caches(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    _trimmed, words, timeline = _postprod_artifacts(source, work)
    args = _broll_args(source, work)
    _patch_main_shell(monkeypatch, args)
    common = analysis_cache_inputs(
        str(source), str(words), timeline_path=str(timeline),
    )
    auto_inputs = {**common, "stage": "auto_script-v1"}
    write_json_cache(
        str(work / "auto_script.json"),
        {"items": [], "tech_keywords": []}, auto_inputs,
    )
    visual_inputs = {**common, "stage": "visual_moments-v1", "items": []}
    write_json_cache(str(work / "visual_moments.json"), [], visual_inputs)
    monkeypatch.setattr(
        postprod, "auto_generate_broll_items",
        lambda *_a, **_k: pytest.fail("valid auto script cache was ignored"),
    )
    monkeypatch.setattr(
        postprod, "analyze_transcript_for_visuals",
        lambda *_a, **_k: pytest.fail("valid visual cache was ignored"),
    )

    postprod.main()

    assert json.loads((work / "broll_plan.json").read_text()) == []
