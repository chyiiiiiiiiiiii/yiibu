"""Layer three: the deliverable's final name is claimed by a passing gate run.

Layers one and two check after the fact — the build log makes a missing gate
run visible, the Stop hook refuses to end a turn on an ungated render. Both sit
BESIDE the door. This moves the door: the build writes its files into the work
dir under staging names, and the only thing in this toolchain that puts them at
the project's first level under postable names is `gates.py` returning 0.

So the failure mode changes shape. "I forgot to run the gates" no longer
produces an unchecked video; it produces no video, which reports itself.

What it still cannot do, stated here so nobody reads these tests as a proof of
more than they show: anyone with a shell can copy the staged file out by hand.
That is the trust boundary, not a bug — and it is the case the Stop hook was
written for, because a hand-copied file at the first level has no gate run
recorded against its name.
"""

import json
import os
import shlex
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gates  # noqa: E402

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "hooks", "gate_guard.py")


def staged(tmp_path, files=None, dest=".."):
    """A work dir holding a built, declared, not-yet-published delivery."""
    wd = tmp_path / "work"
    wd.mkdir(parents=True, exist_ok=True)
    files = files or {"vp_music.mp4": "recap.mp4",
                      "vp_nomusic.mp4": "recap-nomusic.mp4",
                      "cover.jpg": "cover.jpg"}
    for staged_name in files:
        (wd / staged_name).write_bytes(b"\x00" * 32)
    (wd / "delivery.json").write_text(
        json.dumps({"dir": dest, "files": files}, ensure_ascii=False))
    return str(wd)


def ok(name="Sync"):
    return {"name": name, "pass": True, "deferred": False, "failures": [],
            "details": {}}


def bad(name="Sync"):
    return {"name": name, "pass": False, "deferred": False,
            "failures": ["measured 0.42, threshold 0.25"], "details": {}}


def deferred(name="Captions"):
    return {"name": name, "pass": True, "deferred": True, "failures": [],
            "details": {}}


def run_main(monkeypatch, wd, results, video="vp_music.mp4"):
    """Drive gates.main() over canned gate results — the real wiring, no ffmpeg."""
    monkeypatch.setattr(gates, "run", lambda v, w: results)
    monkeypatch.setattr(sys, "argv",
                        ["gates.py", os.path.join(wd, video), "--work-dir", wd])
    with pytest.raises(SystemExit) as e:
        gates.main()
    return e.value.code


# ── the contract itself ─────────────────────────────────────────────────

def test_no_delivery_json_means_the_old_behaviour(tmp_path):
    wd = tmp_path / "work"
    wd.mkdir()
    assert gates.load_delivery(str(wd)) is None


def test_an_empty_delivery_is_not_a_delivery(tmp_path):
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "delivery.json").write_text('{"dir": "..", "files": {}}')
    assert gates.load_delivery(str(wd)) is None


def test_a_corrupt_delivery_file_does_not_crash_the_gates(tmp_path):
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "delivery.json").write_text("{not json")
    assert gates.load_delivery(str(wd)) is None


# ── publishing happens only on a clean verdict ──────────────────────────

def test_a_clean_run_publishes_under_the_final_names(tmp_path, monkeypatch):
    wd = staged(tmp_path)
    assert run_main(monkeypatch, wd, [ok(), ok("Cover")]) == 0
    assert sorted(os.listdir(tmp_path)) == ["cover.jpg", "recap-nomusic.mp4",
                                            "recap.mp4", "work"]
    assert not os.path.exists(os.path.join(wd, "vp_music.mp4"))


def test_a_shippable_run_hands_over_the_review_of_the_file_it_published(
        tmp_path, monkeypatch, capsys):
    wd = staged(tmp_path)
    assert run_main(monkeypatch, wd, [ok()]) == 0
    review = [line for line in capsys.readouterr().out.splitlines()
              if "review.py" in line]
    assert review and "recap.mp4" in review[-1]

    wd = staged(tmp_path / "blocked")
    run_main(monkeypatch, wd, [bad()])
    assert "review.py" not in capsys.readouterr().out


def test_the_review_command_survives_a_path_with_spaces(tmp_path, monkeypatch, capsys):
    wd = staged(tmp_path / "My Run")
    run_main(monkeypatch, wd, [ok()])
    line = [ln for ln in capsys.readouterr().out.splitlines() if "review.py" in ln][-1]
    argv = shlex.split(line)
    assert argv[argv.index("review.py") + 1] == wd
    assert os.path.exists(argv[argv.index("--output") + 1])


def test_a_blocked_run_publishes_nothing(tmp_path, monkeypatch):
    """THE point of the layer. Exit 1 must leave the first level empty."""
    wd = staged(tmp_path)
    assert run_main(monkeypatch, wd, [ok(), bad("Sync")]) == 1
    assert sorted(os.listdir(tmp_path)) == ["work"]
    assert os.path.exists(os.path.join(wd, "vp_music.mp4"))


def test_a_deferred_run_publishes_nothing_either(tmp_path, monkeypatch):
    """Exit 2 is "nothing is broken AND this is not finished".

    A file sitting at the project's first level says finished. Publishing on a
    deferred run would re-merge the two sentences this repo has spent the most
    effort keeping apart.
    """
    wd = staged(tmp_path)
    assert run_main(monkeypatch, wd, [ok(), deferred()]) == 2
    assert sorted(os.listdir(tmp_path)) == ["work"]


def test_a_declared_file_that_was_never_built_fails_the_run(tmp_path, monkeypatch):
    wd = staged(tmp_path)
    os.remove(os.path.join(wd, "cover.jpg"))
    assert run_main(monkeypatch, wd, [ok()]) == 1


def test_the_build_log_records_the_published_names(tmp_path, monkeypatch):
    """The gated name and the posted name are different by design, so the log
    has to carry both or the Stop hook cannot tell a published delivery from a
    file nobody checked."""
    wd = staged(tmp_path)
    run_main(monkeypatch, wd, [ok()])
    row = json.loads(open(os.path.join(wd, "build_log.jsonl"),
                          encoding="utf-8").readline())
    assert row["published"] == ["cover.jpg", "recap-nomusic.mp4", "recap.mp4"]
    assert row["gates_run"] == 1, "publishing is not a gate and must not be counted"


def test_publishing_is_idempotent_enough_to_re_run(tmp_path, monkeypatch):
    """A second clean run has nothing left to move and says so as a failure —
    which is correct: the staged set is gone, so this run gated something that
    is no longer the delivery."""
    wd = staged(tmp_path)
    assert run_main(monkeypatch, wd, [ok()]) == 0
    assert run_main(monkeypatch, wd, [ok()]) == 1


def test_an_absolute_destination_is_honoured(tmp_path, monkeypatch):
    out = tmp_path / "posted"
    wd = staged(tmp_path, dest=str(out))
    assert run_main(monkeypatch, wd, [ok()]) == 0
    assert (out / "recap.mp4").exists()


# ── the deliverables gate reads the DECLARED set, not the directory ─────

def test_the_deliverables_gate_checks_the_declared_set(tmp_path):
    """In a work dir the old listing check passes for the wrong reason:
    spine.mov and trimmed.mp4 both read as "a music version"."""
    wd = staged(tmp_path, files={"vp_music.mp4": "recap.mp4",
                                 "cover.jpg": "cover.jpg"})
    (os.path.join(wd, "trimmed.mp4"))
    open(os.path.join(wd, "trimmed.mp4"), "wb").write(b"\x00")
    fails, det = gates.gate_deliverables(os.path.join(wd, "vp_music.mp4"), wd)
    assert any("nomusic" in f for f in fails), fails


def test_a_complete_declared_set_passes(tmp_path):
    wd = staged(tmp_path)
    fails, det = gates.gate_deliverables(os.path.join(wd, "vp_music.mp4"), wd)
    assert not fails, fails
    assert det["staged"]["vp_nomusic.mp4"] == "recap-nomusic.mp4"


# ── layer 2 and layer 3 have to agree ───────────────────────────────────

def load_guard():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate_guard_pub", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_stop_hook_accepts_a_published_delivery(tmp_path, monkeypatch):
    """Without this the two layers would fight: gates.py publishes `recap.mp4`,
    the hook looks for a log entry named `recap.mp4`, finds only the staged
    `vp_music.mp4`, and blocks a correct hand-over."""
    wd = staged(tmp_path)
    assert run_main(monkeypatch, wd, [ok()]) == 0
    assert load_guard().judge(str(tmp_path), 0.0) == []


def test_the_stop_hook_accepts_the_nomusic_half_of_a_gated_pair(tmp_path):
    """gates.py reads the no-music version as an INPUT — it subtracts one from
    the other to measure the bed — so it never gets an entry of its own, while
    the house rule says both always ship."""
    guard = load_guard()
    (tmp_path / "recap.mp4").write_bytes(b"\x00")
    (tmp_path / "recap-nomusic.mp4").write_bytes(b"\x00")
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "decisions.json").write_text("{}")
    (wd / "build_log.jsonl").write_text(json.dumps(
        {"attempt": 1, "output": "recap.mp4", "verdict": "shippable"}) + "\n")
    assert guard.judge(str(tmp_path), 0.0) == []


def test_a_hand_copied_file_is_still_caught(tmp_path, monkeypatch):
    """The trust boundary, tested rather than asserted: copying the staged file
    out by hand bypasses layer 3 completely — and lands exactly where layer 2
    is looking."""
    wd = staged(tmp_path)
    import shutil
    shutil.copy(os.path.join(wd, "vp_music.mp4"), str(tmp_path / "recap.mp4"))
    problems = load_guard().judge(str(tmp_path), 0.0)
    assert any("recap.mp4" in p and "never seen" in p for p in problems), problems


def test_the_log_describes_the_file_where_it_now_is(tmp_path, monkeypatch):
    """Found by re-running the real path after the first commit, not by review.

    `append_build_log` ffprobes whatever path it is handed, and `probe()`
    swallows its own errors, so logging the STAGED path after the set had
    already been moved recorded `"video": {}` — silently, and only on the runs
    that passed. The successful runs are exactly the ones whose size, duration
    and bitrate anyone would ever want to look up.
    """
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    wd = staged(tmp_path)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=black:s=1080x1920:r=30:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-y", os.path.join(wd, "vp_music.mp4")],
                   check=True, capture_output=True)

    assert run_main(monkeypatch, wd, [ok()]) == 0
    row = json.loads(open(os.path.join(wd, "build_log.jsonl"),
                          encoding="utf-8").readline())
    assert row["output"] == "recap.mp4", "the log should name what was delivered"
    assert row["video"].get("w") == 1080, row["video"]
