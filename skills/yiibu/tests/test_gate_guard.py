"""The Stop hook is a gate, so it gets the same treatment as one: a test that
reconstructs each defect it exists to catch.

The defect it was built for is not a broken render — it is a CLEAN one that
nobody checked. That failure leaves no trace in the video, only an absence in
`build_log.jsonl`, which is why it survived so long: every artifact on disk
looks exactly the same whether the gates ran or not.
"""

import json
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # skills/yiibu
PLUGIN = os.path.dirname(os.path.dirname(ROOT))                        # repo root
HOOK = os.path.join(PLUGIN, "hooks", "gate_guard.py")


def load_hook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = load_hook()


def project(tmp_path, *, video="FINAL.mp4", log=None, log_age=0.0,
            evidence=True):
    """A directory shaped like a finished yiibu project.

    log=None means gates.py never ran. log={...} writes one build_log.jsonl
    entry; log_age pushes the log's mtime BACKWARDS in seconds, which is how a
    re-render after a passing gate run looks on disk.
    """
    wd = tmp_path / "work"
    wd.mkdir(parents=True, exist_ok=True)
    if evidence:
        (wd / "decisions.json").write_text(json.dumps(
            {"loudness": {"value": "original", "why": "spoken room"},
             "captions": "on", "end_card": {"value": "on"}}))
    if video:
        (tmp_path / video).write_bytes(b"\x00" * 16)
    if log is not None:
        p = wd / "build_log.jsonl"
        p.write_text(json.dumps(log, ensure_ascii=False) + "\n")
        if log_age:
            t = time.time() - log_age
            os.utime(p, (t, t))
    return str(tmp_path)


def entry(**kw):
    row = {"attempt": 1, "output": "FINAL.mp4", "verdict": "shippable",
           "gates_run": 19, "gates_failed": [], "failures": {}}
    row.update(kw)
    return row


FLOOR = 0.0        # every file in a fresh tmp_path counts as "this session"


def test_a_gated_render_lets_the_turn_end(tmp_path):
    root = project(tmp_path, log=entry())
    assert guard.judge(root, FLOOR) == []


def test_an_ungated_render_is_caught(tmp_path):
    """THE defect. Every file present, every one of them fine, no gate run."""
    root = project(tmp_path, log=None)
    problems = guard.judge(root, FLOOR)
    assert len(problems) == 1
    assert "FINAL.mp4" in problems[0]
    assert "never seen" in problems[0]


def test_a_render_made_after_the_gate_run_is_caught(tmp_path):
    """The subtle one: gates passed, then somebody rendered again.

    This is the shape of the silent ending that shipped twice — the check was
    real, it just described an earlier file.
    """
    root = project(tmp_path, log=entry(), log_age=600)
    problems = guard.judge(root, FLOOR)
    assert len(problems) == 1
    assert "re-rendered" in problems[0]


def test_a_blocked_verdict_is_caught_and_names_the_gates(tmp_path):
    root = project(tmp_path, log=entry(verdict="blocked",
                                       gates_failed=["Sync", "Cover"]))
    problems = guard.judge(root, FLOOR)
    assert len(problems) == 1
    assert "Sync" in problems[0] and "Cover" in problems[0]


def test_a_deferred_verdict_is_not_silently_finished(tmp_path):
    """Exit 2 from gates.py means nothing is broken and it is NOT finished.

    A turn that ends there without saying so is the exact hand-over AGENTS.md
    forbids, and it is the one an agent is most likely to make: the report is
    green apart from a pause icon.
    """
    root = project(tmp_path, log=entry(verdict="incomplete"))
    problems = guard.judge(root, FLOOR)
    assert len(problems) == 1
    assert "outstanding" in problems[0]


def test_intermediates_are_not_deliveries(tmp_path):
    """trimmed.mp4 is written by step 1. Gating it would fire on every run and
    a check that cries wolf gets turned off."""
    root = project(tmp_path, video=None, log=None)
    (tmp_path / "work" / "trimmed.mp4").write_bytes(b"\x00")
    assert guard.judge(root, FLOOR) == []


def test_a_render_from_before_this_session_is_left_alone(tmp_path):
    root = project(tmp_path, log=None)
    assert guard.judge(root, time.time() + 60) == []


def test_a_directory_with_no_yiibu_artifacts_is_none_of_our_business(tmp_path):
    (tmp_path / "holiday.mp4").write_bytes(b"\x00")
    assert not guard.looks_like_an_edit(str(tmp_path))


def test_a_work_dir_makes_it_our_business(tmp_path):
    project(tmp_path, log=None)
    assert guard.looks_like_an_edit(str(tmp_path))


def run_hook(payload):
    import subprocess
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True)


def test_exit_2_and_the_message_names_the_command(tmp_path):
    root = project(tmp_path, log=None)
    r = run_hook({"cwd": root, "hook_event_name": "Stop"})
    assert r.returncode == 2, r.stderr
    assert "gates.py FINAL.mp4 --work-dir WORK_DIR" in r.stderr
    assert "house_style.local.json" in r.stderr      # the exemption is written down


def test_a_clean_project_exits_0(tmp_path):
    root = project(tmp_path, log=entry())
    assert run_hook({"cwd": root, "hook_event_name": "Stop"}).returncode == 0


def test_it_never_asks_twice(tmp_path):
    """stop_hook_active means the turn was already continued by this hook.
    Asking again is a loop, and a loop is worse than a missed check."""
    root = project(tmp_path, log=None)
    r = run_hook({"cwd": root, "stop_hook_active": True})
    assert r.returncode == 0


def test_garbage_on_stdin_never_breaks_a_turn(tmp_path):
    import subprocess
    r = subprocess.run([sys.executable, HOOK], input="not json",
                       capture_output=True, text=True)
    assert r.returncode == 0


@pytest.mark.skipif(not os.path.exists(os.path.join(PLUGIN, "hooks/hooks.json")),
                    reason="no hooks.json")
def test_the_manifest_points_at_a_file_that_exists():
    """A hook registered under a path that does not resolve fails silently —
    which is indistinguishable from a hook that ran and approved."""
    manifest = json.load(open(os.path.join(PLUGIN, "hooks", "hooks.json")))
    cmds = [h["command"] for group in manifest["hooks"]["Stop"]
            for h in group["hooks"]]
    assert cmds, "the Stop event is registered with no command"
    for c in cmds:
        rel = c.split("${CLAUDE_PLUGIN_ROOT}/")[1].rstrip('"')
        assert os.path.exists(os.path.join(PLUGIN, rel)), c


def test_a_crash_blocks_instead_of_waving_it_through(tmp_path):
    """A guard that crashes must not look like a guard that approved.

    Claude Code treats every exit code except 2 as advisory, so an exception
    anywhere in the walk would let the hand-over through with a traceback in
    the log nobody reads. That is worse than having no hook at all: it is a
    green light produced by a failure. The loop guard (`stop_hook_active`)
    means failing closed costs one turn and cannot trap the session.
    """
    import subprocess
    root = project(tmp_path, log=entry())
    # the faithful reproduction: a copy of the real hook with judge() raising
    src = open(HOOK, encoding="utf-8").read().replace(
        "def judge(root, floor):", "def judge(root, floor):\n    raise RuntimeError('boom')")
    hurt = tmp_path / "hurt_guard.py"
    hurt.write_text(src)
    r = subprocess.run([sys.executable, str(hurt)],
                       input=json.dumps({"cwd": root}), capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "could not check" in r.stderr


def test_a_crash_does_not_ask_twice(tmp_path):
    import subprocess
    root = project(tmp_path, log=entry())
    src = open(HOOK, encoding="utf-8").read().replace(
        "def judge(root, floor):", "def judge(root, floor):\n    raise RuntimeError('boom')")
    hurt = tmp_path / "hurt_guard.py"
    hurt.write_text(src)
    r = subprocess.run([sys.executable, str(hurt)],
                       input=json.dumps({"cwd": root, "stop_hook_active": True}),
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_work_dir_machinery_is_not_a_delivery(tmp_path):
    """A work dir holds spine.mov, base_cat.mp4, one file per segment. Judging
    those would fire on every correct build, and a guard that cries wolf on
    correct work is a guard someone switches off."""
    root = project(tmp_path, video=None, log=None)
    for name in ("spine.mov", "base_cat.mp4", "seg01.mov"):
        (tmp_path / "work" / name).write_bytes(b"\x00")
    assert guard.judge(root, FLOOR) == []


def test_a_staged_delivery_that_was_never_gated_is_caught(tmp_path):
    """The other side of layer three: the build declared its delivery and the
    gates never ran, so the files are still sitting in the work dir. Without
    this the turn ends quietly and the user is left with no video and no
    reason — the failure would report itself only when someone went looking."""
    root = project(tmp_path, video=None, log=None)
    (tmp_path / "work" / "vp_music.mp4").write_bytes(b"\x00")
    (tmp_path / "work" / "delivery.json").write_text(json.dumps(
        {"dir": "..", "files": {"vp_music.mp4": "recap.mp4"}}))
    problems = guard.judge(root, FLOOR)
    assert len(problems) == 1 and "vp_music.mp4" in problems[0]
