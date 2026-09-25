import json
import os
import subprocess
import time

import asr_scan
import pytest


def _make_media(tmp_path, names=("a.mov", "b.mov")):
    source = tmp_path / "source"
    source.mkdir()
    for name in names:
        (source / name).write_bytes((name + "-content").encode())
    return source


def _worker_script(counter_path, fail_after=None, delay=0):
    return f'''
import json, os, sys, time
paths = json.load(open(sys.argv[1]))
counter_path = {str(counter_path)!r}
out = {{}}
for index, path in enumerate(paths, 1):
    counts = json.load(open(counter_path)) if os.path.exists(counter_path) else {{}}
    name = os.path.basename(path)
    counts[name] = counts.get(name, 0) + 1
    json.dump(counts, open(counter_path, "w"))
    time.sleep({delay!r})
    rows = [{{
        "start": 0.0, "end": 0.4, "text": "今天",
        "avg_logprob": -0.1, "no_speech_prob": 0.1,
        "words": [{{"text": "今天", "start": 0.0, "end": 0.4,
                   "probability": 0.95}}],
    }}]
    out[path] = rows
    if len(sys.argv) <= 3:
        print(json.dumps({{"path": path, "rows": rows}}, ensure_ascii=False),
              flush=True)
    if {fail_after!r} == index:
        sys.exit(7)
if len(sys.argv) > 3:
    json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False)
'''


def test_scan_reuses_completed_clip_cache_without_loading_worker(
    tmp_path, monkeypatch,
):
    source = _make_media(tmp_path)
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))

    first = asr_scan.scan(str(source), str(work), model="test-model")
    second = asr_scan.scan(str(source), str(work), model="test-model")

    assert first == second
    assert json.loads(counter.read_text()) == {"a.mov": 1, "b.mov": 1}
    assert set(json.loads((work / "asr_scan.json").read_text())) == {
        "a.mov", "b.mov",
    }


def test_scan_invalidates_cache_when_source_model_or_settings_change(
    tmp_path, monkeypatch,
):
    source = _make_media(tmp_path)
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))

    asr_scan.scan(str(source), str(work), model="model-a")
    (source / "a.mov").write_bytes(b"changed source bytes")
    asr_scan.scan(str(source), str(work), model="model-a")
    assert json.loads(counter.read_text()) == {"a.mov": 2, "b.mov": 1}

    asr_scan.scan(str(source), str(work), model="model-b")
    assert json.loads(counter.read_text()) == {"a.mov": 3, "b.mov": 2}

    asr_scan.scan(str(source), str(work), model="model-b", quiet_db=-24.0)
    assert json.loads(counter.read_text()) == {"a.mov": 4, "b.mov": 3}


def test_scan_keeps_completed_clips_after_worker_failure_and_removes_stale_manifest(
    tmp_path, monkeypatch,
):
    source = _make_media(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    counter = tmp_path / "counts.json"
    (work / "asr_scan.json").write_text(
        json.dumps({
            "a.mov": {
                "speech": True,
                "captioned": False,
                "why": "editor reviewed this line",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(
        asr_scan, "_WORKER", _worker_script(counter, fail_after=1),
    )

    with pytest.raises(SystemExit, match="exit code 7"):
        asr_scan.scan(str(source), str(work), model="test-model")

    assert not (work / "asr_scan.json").exists()
    backups = list(work.glob("asr_scan.previous-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["a.mov"]["captioned"] is False
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    result = asr_scan.scan(str(source), str(work), model="test-model")
    assert set(result) == {"a.mov", "b.mov"}
    assert json.loads(counter.read_text()) == {"a.mov": 1, "b.mov": 1}


def test_scan_times_out_model_startup_or_one_clip_without_publishing_manifest(
    tmp_path, monkeypatch,
):
    source = _make_media(tmp_path, names=("slow.mov",))
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(
        asr_scan, "_WORKER", _worker_script(counter, delay=1.0),
    )

    with pytest.raises(SystemExit, match=r"timed out after 0\.1s"):
        asr_scan.scan(
            str(source), str(work), model="test-model", timeout=0.1,
        )

    assert not (work / "asr_scan.json").exists()


def test_cached_scan_preserves_manual_caption_decision(tmp_path, monkeypatch):
    source = _make_media(tmp_path, names=("a.mov",))
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    asr_scan.scan(str(source), str(work), model="test-model")
    manifest = json.loads((work / "asr_scan.json").read_text())
    manifest["a.mov"]["captioned"] = False
    manifest["a.mov"]["why"] = "editor reviewed this line"
    (work / "asr_scan.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = asr_scan.scan(str(source), str(work), model="test-model")

    assert result["a.mov"]["captioned"] is False
    assert result["a.mov"]["why"] == "editor reviewed this line"
    assert json.loads(counter.read_text()) == {"a.mov": 1}


def test_interrupted_resume_preserves_review_for_the_same_fingerprint(
    tmp_path, monkeypatch,
):
    source = _make_media(tmp_path)
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    asr_scan.scan(str(source), str(work), model="test-model")
    manifest = json.loads((work / "asr_scan.json").read_text())
    manifest["a.mov"]["captioned"] = False
    manifest["a.mov"]["why"] = "editor reviewed this line"
    (work / "asr_scan.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "b.mov").write_bytes(b"changed b source")
    monkeypatch.setattr(
        asr_scan, "_WORKER", _worker_script(counter, fail_after=1),
    )

    with pytest.raises(SystemExit, match="exit code 7"):
        asr_scan.scan(str(source), str(work), model="test-model")

    assert not (work / "asr_scan.json").exists()
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    resumed = asr_scan.scan(str(source), str(work), model="test-model")
    assert resumed["a.mov"]["captioned"] is False
    assert resumed["a.mov"]["why"] == "editor reviewed this line"
    assert json.loads(counter.read_text()) == {"a.mov": 1, "b.mov": 2}


def test_non_object_cache_is_a_miss_and_is_recomputed(tmp_path, monkeypatch):
    source = _make_media(tmp_path, names=("a.mov",))
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    asr_scan.scan(str(source), str(work), model="test-model")
    cache_file = next((work / "_asr_scan_cache").glob("*.json"))
    cache_file.write_text("[]", encoding="utf-8")

    result = asr_scan.scan(str(source), str(work), model="test-model")

    assert result["a.mov"]["speech"] is True
    assert json.loads(counter.read_text()) == {"a.mov": 2}


def test_cache_with_incomplete_result_is_a_miss(tmp_path, monkeypatch):
    source = _make_media(tmp_path, names=("a.mov",))
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    asr_scan.scan(str(source), str(work), model="test-model")
    cache_file = next((work / "_asr_scan_cache").glob("*.json"))
    cache = json.loads(cache_file.read_text())
    cache["result"] = {}
    cache_file.write_text(json.dumps(cache), encoding="utf-8")

    asr_scan.scan(str(source), str(work), model="test-model")

    assert json.loads(counter.read_text()) == {"a.mov": 2}


def test_review_is_not_reused_after_source_fingerprint_changes(
    tmp_path, monkeypatch,
):
    source = _make_media(tmp_path, names=("a.mov",))
    work = tmp_path / "work"
    counter = tmp_path / "counts.json"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", _worker_script(counter))
    asr_scan.scan(str(source), str(work), model="test-model")
    manifest = json.loads((work / "asr_scan.json").read_text())
    manifest["a.mov"]["captioned"] = False
    manifest["a.mov"]["why"] = "decision for the original source"
    (work / "asr_scan.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "a.mov").write_bytes(b"replacement source")

    result = asr_scan.scan(str(source), str(work), model="test-model")

    assert "captioned" not in result["a.mov"]
    assert result["a.mov"].get("why") != "decision for the original source"
    assert list(work.glob("asr_scan.previous-*.json"))


def test_quiet_clip_verdict_is_cached_before_loading_a_model(tmp_path, monkeypatch):
    source = _make_media(tmp_path, names=("quiet.mov",))
    work = tmp_path / "work"
    volume_checks = []

    def quiet(path, _timeout):
        volume_checks.append(path)
        return -40.0

    monkeypatch.setattr(asr_scan, "_max_volume_db", quiet)
    asr_scan.scan(str(source), str(work), model="test-model")
    asr_scan.scan(str(source), str(work), model="test-model")

    assert len(volume_checks) == 1


def test_scan_timeout_bounds_unterminated_worker_output(tmp_path, monkeypatch):
    source = _make_media(tmp_path, names=("slow.mov",))
    work = tmp_path / "work"
    monkeypatch.setattr(asr_scan, "_max_volume_db", lambda _path, _timeout: 0.0)
    monkeypatch.setattr(asr_scan, "_WORKER", '''
import json, sys, time
path = json.load(open(sys.argv[1]))[0]
rows = [{"start": 0.0, "end": 0.4, "text": "今天",
         "avg_logprob": -0.1, "no_speech_prob": 0.1,
         "words": [{"text": "今天", "start": 0.0, "end": 0.4,
                    "probability": 0.95}]}]
sys.stdout.write(json.dumps({"path": path, "rows": rows}))
sys.stdout.flush()
time.sleep(1)
''')

    started = time.monotonic()
    with pytest.raises(SystemExit, match=r"timed out after 0\.1s"):
        asr_scan.scan(str(source), str(work), timeout=0.1)

    assert time.monotonic() - started < 0.7
    assert not (work / "asr_scan.json").exists()


def test_scan_timeout_also_bounds_volume_probe(tmp_path, monkeypatch):
    source = _make_media(tmp_path, names=("broken.mov",))
    work = tmp_path / "work"

    def timeout(_path, timeout):
        raise subprocess.TimeoutExpired("ffmpeg", timeout)

    monkeypatch.setattr(asr_scan, "_max_volume_db", timeout)

    with pytest.raises(SystemExit, match=r"volume probe timed out after 0\.1s"):
        asr_scan.scan(str(source), str(work), timeout=0.1)

    assert not (work / "asr_scan.json").exists()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_scan_rejects_an_unbounded_timeout(tmp_path, timeout):
    source = _make_media(tmp_path, names=("a.mov",))

    with pytest.raises(SystemExit, match="finite number greater than zero"):
        asr_scan.scan(str(source), str(tmp_path / "work"), timeout=timeout)
