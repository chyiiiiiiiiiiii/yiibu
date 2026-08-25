#!/usr/bin/env python3
"""Stop hook: refuse to end a turn that produced a video the gates never saw.

WHY THIS EXISTS
---------------
`AGENTS.md` opens with the rule the whole repo is built on:

    Quality lives in the executable checks, never in the agent driving them.
    Anything that depends on an agent remembering, noticing, or being clever
    is not a standard — it is a hope.

Every gate obeyed that rule except the step that RUNS the gates. `gates.py
FINAL.mp4 --work-dir WORK_DIR` was prose in AGENTS.md §6 and SKILL.md, and
prose is exactly what this repo has watched fail twice before. Nothing in the
harness noticed a hand-over that skipped it; the one automatic check was
`verify.py`, which is advisory and used to print "PUBLISH READY".

So this hook is the last of the three holes: it makes ending the turn the
thing that gets refused, rather than the render.

WHAT IT DOES
------------
On Stop, it looks for video files this session touched and asks one question
per file: does a `build_log.jsonl` entry exist for it, written after the file
itself? `gates.py` is the only writer of that log — BUILD_LOG.md says so in
the file it generates: "a run that is not logged did not happen." So the
absence of an entry is not a heuristic, it is the record.

  * no entry, or an entry older than the render  -> the gates never saw THIS cut
  * an entry whose verdict is blocked/incomplete -> the gates saw it and refused

Either way the hook exits 2, which tells Claude Code to keep the turn open and
hands the message back to the model.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It fires only inside a directory that shows evidence of a yiibu edit
(`decisions.json`, `timeline.json`, `words.json`, a caption file, or an
existing build log). Two consequences, and the second is a real hole worth
stating rather than hiding:

  * it stays silent in every unrelated repo that happens to render an mp4;
  * a video produced with NO yiibu artifact at all — a hand-written ffmpeg
    line, start to finish — is invisible to it. `decisions.json` is required
    by the gates themselves, so a real edit cannot avoid leaving one, but a
    fabricated one-liner can.

And the ceiling that no hook can raise: this is Claude Code only. Codex,
Antigravity, a plain script and a human all still reach the standard the way
`AGENTS.md` says they do — by running the commands. The hook is a floor under
one driver, never a replacement for the contract.
"""

import json
import os
import sys
import time

VIDEO_EXT = (".mp4", ".mov", ".m4v")

# Directory names that never hold a delivery, only inputs and machinery.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".pytest_cache", ".mypy_cache", "site-packages", "frames",
             "tests", "footage", "source", "raw"}

# Files that mean "a yiibu edit happened in this tree".
EVIDENCE = ("decisions.json", "timeline.json", "words.json", "subtitles.ass",
            "captions.ass", "build_log.jsonl")

# An intermediate is not a delivery. These are the names the pipeline writes
# on the way to one, and gating them would fire on every render step.
INTERMEDIATE = {"trimmed.mp4", "titled_output.mp4", "concat.mp4", "silent.mp4",
                "composed.mp4", "with_subs.mp4", "broll.mp4", "temp.mp4"}

FALLBACK_WINDOW_S = 4 * 3600


def walk(root, max_depth=5):
    """Yield (dirpath, filenames), pruning machinery and stopping at depth."""
    root = os.path.abspath(root)
    base = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - base >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        yield dirpath, filenames


SCAN_BUDGET_S = 3.0


def looks_like_an_edit(root, budget_s=SCAN_BUDGET_S):
    """Is there any sign of a yiibu edit under here?

    This is the only unbounded scan in the file — it runs before we know
    whether this directory has anything to do with video, and it returns as
    soon as it finds the first marker. Somebody working with their home
    directory as cwd would otherwise pay a full depth-5 walk on every turn,
    against a hook timeout, for a directory that was never going to match.

    Exhausting the budget without finding a marker is treated as "not a yiibu
    project", not as "could not check": a tree that large with no artifact in
    the first three seconds is not one this hook has business blocking.
    """
    deadline = time.time() + budget_s
    for i, (_, filenames) in enumerate(walk(root)):
        if any(name in EVIDENCE for name in filenames):
            return True
        if i % 200 == 199 and time.time() > deadline:
            return False
    return False


def session_floor(payload):
    """Only judge renders from THIS session.

    The transcript file is created when the session starts, so its CREATION
    time is a real anchor rather than a guessed window.

    It has to be `st_birthtime`, not `os.path.getctime`. On macOS — and on
    Linux, differently — `st_ctime` is the inode-change time, and the
    transcript is appended to after every single message. Using it made the
    floor equal to "a few seconds ago", so every render in the session sorted
    BELOW it and the hook silently judged nothing at all. Every test still
    passed, because they all pass an explicit floor. A guard that approves
    everything is indistinguishable from a guard that works, which is the
    exact failure this file exists to prevent, reproduced inside the file
    itself.

    No birthtime (most Linux filesystems through Python's os.stat) falls back
    to a four-hour window: long enough to cover an edit, short enough that
    yesterday's deliveries stay out of it.
    """
    path = payload.get("transcript_path")
    if path and os.path.exists(path):
        try:
            born = getattr(os.stat(path), "st_birthtime", None)
            if born:
                return born
        except OSError:
            pass
    return time.time() - FALLBACK_WINDOW_S


def staged_names(dirpath):
    """The files delivery.json declares in this work dir, or None."""
    p = os.path.join(dirpath, "delivery.json")
    if not os.path.exists(p):
        return None
    try:
        files = json.load(open(p, encoding="utf-8")).get("files")
    except (OSError, ValueError):
        return None
    return set(files) if isinstance(files, dict) and files else None


def collect(root, floor, budget_s=SCAN_BUDGET_S):
    """ONE walk: the videos that claim to be a delivery, and every gate log.

    It used to be three walks — evidence, videos, logs — which measured 5.3s
    against a home directory. A guard that adds five seconds to the end of
    every turn is a guard someone switches off, and a switched-off guard is
    worth less than no guard at all, because everyone still believes it is
    running.

    A work dir is machinery, not a delivery surface: it holds `spine.mov`,
    `base_cat.mp4`, one file per segment. Judging everything under it would
    fire on every correct build. So a directory carrying a yiibu artifact is
    read as a work dir and its videos are skipped — with one exception that
    matters: a file DECLARED in its `delivery.json` and still sitting there at
    the end of the turn was built as a deliverable and never published, which
    is the "I forgot the gates" case seen from the other side.

    The budget stops the walk, not the judgement: whatever was collected is
    still judged. In the case this hook is actually for — cwd IS the project —
    the walk finishes in milliseconds and the budget never applies.
    """
    deadline = time.time() + budget_s
    vids, logs = [], {}
    for i, (dirpath, filenames) in enumerate(walk(root)):
        work_dir = any(name in EVIDENCE for name in filenames)
        declared = staged_names(dirpath) if work_dir else None

        if "build_log.jsonl" in filenames:
            p = os.path.join(dirpath, "build_log.jsonl")
            try:
                with open(p, encoding="utf-8") as f:
                    rows = [json.loads(line) for line in f if line.strip()]
                written = os.path.getmtime(p)
            except (OSError, ValueError):
                rows, written = [], 0
            for row in rows:
                name = row.get("output")
                if not name:
                    continue
                prev = logs.get(name)
                if prev is None or written >= prev[1]:
                    logs[name] = (row, written)

        for name in filenames:
            if not name.lower().endswith(VIDEO_EXT):
                continue
            if work_dir and name not in (declared or ()):
                continue
            if not work_dir and name in INTERMEDIATE:
                continue
            p = os.path.join(dirpath, name)
            try:
                mtime = os.path.getmtime(p)
            except OSError:
                continue
            if mtime >= floor:
                vids.append((p, mtime))

        if i % 200 == 199 and time.time() > deadline:
            break
    return sorted(vids), logs


def covered_by(logs, name):
    """Find the gate run that speaks for this file, under any of its names.

    Three ways a delivery is covered, and all three are the record rather than
    a guess:

      * the run gated this exact basename;
      * the run PUBLISHED it under this name (gates.py stages the build inside
        the work dir and moves the set out itself, so the gated name and the
        posted name are routinely different);
      * it is the `-nomusic` half of a pair whose music version was gated.
        Both versions always ship, and gates.py reads the no-music sibling as
        an INPUT — it subtracts one from the other to measure the bed — so it
        never gets a build-log entry of its own. Without this the house rule
        "always ship both" would make the hook fire on every correct delivery,
        and a check that fires on correct work gets switched off.
    """
    hit = logs.get(name)
    if hit:
        return hit
    for row, written in logs.values():
        if name in (row.get("published") or []):
            return row, written
    stem, dot, ext = name.rpartition(".")
    if stem.endswith("-nomusic"):
        return covered_by(logs, f"{stem[:-len('-nomusic')]}{dot}{ext}")
    return None


def judge(root, floor):
    """Return the list of complaints. Empty means the turn may end."""
    vids, logs = collect(root, floor)
    problems = []
    for path, mtime in vids:
        rel = os.path.relpath(path, root)
        hit = covered_by(logs, os.path.basename(path))
        if hit is None:
            problems.append(
                f"{rel} — no gate run recorded. The gates have never seen this "
                f"file.")
            continue
        row, written = hit
        if written < mtime - 1.0:
            problems.append(
                f"{rel} — the last gate run (attempt #{row.get('attempt')}) is "
                f"older than the file. This cut was re-rendered afterwards and "
                f"has not been checked.")
            continue
        verdict = row.get("verdict")
        if verdict == "blocked":
            problems.append(
                f"{rel} — the gates BLOCKED this render: "
                f"{', '.join(row.get('gates_failed') or []) or 'see BUILD_LOG.md'}.")
        elif verdict == "incomplete":
            problems.append(
                f"{rel} — gates deferred by a recorded decision. Nothing is "
                f"broken, but this is not a finished delivery and the user has "
                f"to be told which parts are outstanding.")
    return problems


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        sys.exit(0)                      # never break a turn over our own input

    # Claude Code sets this when the turn was already continued by a Stop hook.
    # Asking twice would be a loop, and a loop is worse than a missed check —
    # and it is also what keeps the fail-closed branch below survivable.
    if payload.get("stop_hook_active"):
        sys.exit(0)

    root = payload.get("cwd") or os.getcwd()
    if not os.path.isdir(root):
        sys.exit(0)

    try:
        if not looks_like_an_edit(root):
            sys.exit(0)
        problems = judge(root, session_floor(payload))
    except SystemExit:
        raise
    except Exception as e:                                    # noqa: BLE001
        # FAIL CLOSED, exactly once. Any exit code other than 2 is advisory to
        # Claude Code, so a crashing guard would wave every hand-over through
        # while looking like a guard that ran and approved — the same shape as
        # the xfail-with-a-plausible-sentence this repo has already been bitten
        # by. Blocking once costs one extra turn; the loop guard above means a
        # broken guard cannot trap the session.
        print(f"The gate guard could not check this turn ({type(e).__name__}: "
              f"{e}). It cannot tell you the render was gated, so treat it as "
              f"not gated: run `python3 gates.py FINAL.mp4 --work-dir WORK_DIR` "
              f"and say what it returned.", file=sys.stderr)
        sys.exit(2)

    if not problems:
        sys.exit(0)

    lines = ["A video was produced in this session that the shipping gates did "
             "not clear:", ""]
    lines += [f"  - {p}" for p in problems]
    lines += ["",
              "Run the blocking check before handing anything over:",
              "",
              "    cd skills/yiibu && python3 gates.py FINAL.mp4 --work-dir WORK_DIR",
              "",
              "Exit 0 shippable, 1 broken (loop back to the EDIT, never to the "
              "encoder settings), 2 deferred by a recorded decision — which is "
              "not finished, and you say which parts are outstanding.",
              "If a gate is genuinely wrong for this project, the exemption is "
              "written into WORK_DIR/house_style.local.json, where it is "
              "visible. It is never argued in prose."]
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
