#!/usr/bin/env python3
"""What the gates cost — read out of build logs that already exist.

    python3 friction.py [PATH ...] [--json]

Every gate in this repo can name the shipped defect it was born from. None of
them can say what it has cost since. That asymmetry is how a threshold set on
one project quietly becomes a tax on every later one: the gate keeps firing,
somebody keeps re-rendering, and because each individual failure looks like the
gate doing its job, nobody adds up the bill.

`gates.py` has been writing everything needed to add it up since the beginning
— `WORK_DIR/build_log.jsonl` records, per attempt, which gates were red and
with which exact messages. This reads them back across every project it can
find and reports three things:

  * **red runs** — how many gate runs each gate rejected. On its own this means
    nothing: a gate that fires often may simply be guarding the thing people
    get wrong most.
  * **repeats** — the same gate red with a WORD-FOR-WORD identical message on
    consecutive attempts. This is the signal that matters. It means a render
    was spent and the measurement did not move, which is either a message that
    does not say what to change, or a threshold nothing in the build can reach.
  * **creep** — the same gate red on three or more consecutive attempts with a
    number in its message walking MONOTONICALLY toward the threshold, and then
    green. That is not a build being fixed; it is a threshold being crept up on.
    `repeats` cannot see it, because the message changes every time. Measured on
    2026-08-29: `gate_duck` read 0.38 → 1.66 → 1.94 → 3.82 dB against a 4.0 dB
    minimum, then passed at 4.9 — four renders in which the duck depth was
    raised until the number cleared, rather than the mix being fixed. Three of
    those renders bought nothing a listener would notice.

  * **last-attempt reds** — gates still red on the final logged attempt of a
    project. Either the project was abandoned there, or it shipped anyway by a
    route that did not go through the gate.

It grades nothing and it is **advisory, never a gate** — for the same reason
`contract_probe.py` is: a measurement of your own process, turned into a
threshold, gets tuned until it passes.
"""

import argparse
import json
import os
import re
import sys

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
CREEP_MIN_RUN = 3          # three consecutive reds before a walk is a walk


def _first_number(msgs):
    """The measurement a gate message leads with, or None."""
    if not msgs:
        return None
    m = _NUM.search(str(msgs[0]))
    return float(m.group(0)) if m else None


def _creeps(seq):
    """How many maximal runs of >= CREEP_MIN_RUN strictly monotonic values.

    Deliberately blunt: it does not know where the threshold is, only that the
    same gate kept firing while its own number marched one way. A build that is
    actually being fixed moves the number once and passes.
    """
    n, i = 0, 0
    while i < len(seq):
        j = i + 1
        while j < len(seq) and seq[j] != seq[j - 1] and (
                (seq[j] > seq[j - 1]) == (seq[i + 1] > seq[i]) if j > i + 1 else True):
            j += 1
        if j - i >= CREEP_MIN_RUN:
            n += 1
        i = max(j, i + 1)
    return n


def find_logs(paths):
    """Every build_log.jsonl at or under the given paths."""
    out = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            out.append(p)
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "node_modules", "__pycache__")]
            if "build_log.jsonl" in filenames:
                out.append(os.path.join(dirpath, "build_log.jsonl"))
    return sorted(set(out))


def read(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, ValueError):
        return []
    return sorted(rows, key=lambda r: r.get("attempt", 0))


def report(paths):
    logs = find_logs(paths)
    gates, projects = {}, []

    def g(name):
        return gates.setdefault(name, {"red": 0, "repeats": 0, "projects": set(),
                                       "last_attempt": 0, "worst_streak": 0,
                                       "creeps": 0})

    for path in logs:
        rows = read(path)
        if not rows:
            continue
        name = os.path.basename(os.path.dirname(path)) or path
        verdicts = [r.get("verdict") for r in rows]
        first_green = next((r["attempt"] for r in rows
                            if r.get("verdict") == "shippable"), None)
        projects.append({
            "project": name,
            "runs": len(rows),
            "first_green_at": first_green,
            "ended": verdicts[-1],
            "wasted": sum(1 for v in verdicts if v == "blocked"),
        })

        prev, streak, walk = {}, {}, {}
        for r in rows:
            failures = r.get("failures") or {}
            for gate, msgs in failures.items():
                e = g(gate)
                e["red"] += 1
                e["projects"].add(name)
                if prev.get(gate) == msgs:
                    e["repeats"] += 1
                    streak[gate] = streak.get(gate, 1) + 1
                else:
                    streak[gate] = 1
                e["worst_streak"] = max(e["worst_streak"], streak[gate])
                num = _first_number(msgs)
                if num is not None:
                    walk.setdefault(gate, []).append(num)
            for gate in list(streak):
                if gate not in failures:
                    streak[gate] = 0
                    # the run ended; a walk only counts once it has stopped
                    g(gate)["creeps"] += _creeps(walk.pop(gate, []))
            prev = failures
        for gate, seq in walk.items():
            g(gate)["creeps"] += _creeps(seq)
        for gate in rows[-1].get("gates_failed") or []:
            g(gate)["last_attempt"] += 1

    total = sum(p["runs"] for p in projects)
    rows = [{"gate": k, "red": v["red"],
             "red_rate": round(v["red"] / total, 3) if total else 0.0,
             "repeats": v["repeats"], "creeps": v["creeps"],
             "worst_streak": v["worst_streak"],
             "projects": len(v["projects"]),
             "red_on_last_attempt": v["last_attempt"]}
            for k, v in gates.items()]
    rows.sort(key=lambda r: (-r["repeats"] - r["creeps"], -r["red"]))
    return {"logs": len(logs), "runs": total, "projects": projects, "gates": rows}


def render(rep):
    if not rep["logs"]:
        return ("no build_log.jsonl anywhere under the given path — nothing has "
                "been gated here yet, or you are pointing at the wrong tree.\n")
    out = ["", "=" * 68,
           f"  GATE FRICTION — {rep['runs']} gate run(s) across "
           f"{rep['logs']} project(s)", "=" * 68, "",
           f"  {'gate':<14}{'red':>5}{'rate':>7}{'repeat':>8}{'creep':>7}"
           f"{'streak':>8}{'projs':>7}{'last':>6}"]
    for r in rep["gates"]:
        out.append(f"  {r['gate']:<14}{r['red']:>5}{r['red_rate']:>7.0%}"
                   f"{r['repeats']:>8}{r['creeps']:>7}{r['worst_streak']:>8}"
                   f"{r['projects']:>7}{r['red_on_last_attempt']:>6}")
    out += ["",
            "  repeat = red again with a WORD-FOR-WORD identical message. Each one",
            "  is a render that changed nothing — a message that does not say what",
            "  to change, or a threshold the build cannot reach.",
            "  creep  = three or more consecutive reds whose leading NUMBER walks",
            "  one way. The message changes each time, so `repeat` cannot see it —",
            "  but the threshold is being crept up on, not the build fixed.",
            "  last   = still red on the project's final logged attempt.", ""]
    out += [f"  {'project':<24}{'runs':>6}{'1st green':>11}{'blocked':>9}  ended"]
    for p in rep["projects"]:
        out.append(f"  {p['project'][:24]:<24}{p['runs']:>6}"
                   f"{(p['first_green_at'] or '—'):>11}{p['wasted']:>9}  {p['ended']}")
    out += ["", "  Advisory. A gate that fires a lot may be guarding the thing",
            "  people get wrong most — read the repeats, not the totals.", ""]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=["."],
                    help="work dirs, project roots, or build_log.jsonl files")
    ap.add_argument("--json", action="store_true", help="print the data instead")
    args = ap.parse_args()
    rep = report(args.paths or ["."])
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=list)
          if args.json else render(rep), end="" if not args.json else "\n")


if __name__ == "__main__":
    main()
