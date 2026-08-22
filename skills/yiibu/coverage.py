#!/usr/bin/env python3
"""Editorial coverage: how much screen time did each topic actually get?

This is not a gate and must not become one — how long a subject deserves is a
judgement, and a threshold would just be argued with. It exists because the
gates check for DEFECTS and are blind to OMISSION: on 2026-08-19 a build passed
all twelve gates while three of six teams had two shots and the other three had
four, and a person had to notice. A number on screen is enough to notice.

    python3 coverage.py WORK_DIR

Topic comes from a segment's explicit "topic", else from the leading token of
its source filename (team1_..., team2_...), else "misc".
"""
import json
import os
import re
import sys

MISC = {"img", "misc", "countdown", "final", "judge", "offcial", "official"}


def topic_of(seg):
    if seg.get("topic"):
        return seg["topic"]
    stem = os.path.splitext(os.path.basename(seg.get("file", "")))[0].lower()
    head = re.split(r"[_\-.]", stem)[0]
    if not head or head in MISC or head.startswith("img"):
        return "—"
    return head


def report(work_dir):
    tl_path = os.path.join(work_dir or ".", "timeline.json")
    if not os.path.exists(tl_path):
        return None
    tl = json.load(open(tl_path, encoding="utf-8"))
    segs = tl.get("segments", [])
    if not segs:
        return None

    groups = {}
    for s in segs:
        t = topic_of(s)
        g = groups.setdefault(t, {"shots": 0, "seconds": 0.0, "ids": []})
        g["shots"] += 1
        g["seconds"] += float(s.get("dur", 0))
        g["ids"].append(s.get("id"))

    subjects = {k: v for k, v in groups.items() if k != "—"}
    out = {"total_s": round(float(tl.get("total", 0)), 2),
           "topics": {k: {"shots": v["shots"], "seconds": round(v["seconds"], 2)}
                      for k, v in sorted(groups.items())},
           "thin": []}
    if len(subjects) >= 3:
        shots = sorted(v["shots"] for v in subjects.values())
        median = shots[len(shots) // 2]
        for k, v in sorted(subjects.items()):
            if v["shots"] < median:
                out["thin"].append(
                    {"topic": k, "shots": v["shots"], "median": median,
                     "seconds": round(v["seconds"], 2)})
    return out


def render(rep):
    if not rep:
        return ""
    L = ["", "  " + "-" * 58, "  COVERAGE (advisory — not a gate)", ""]
    for k, v in rep["topics"].items():
        share = v["seconds"] / rep["total_s"] * 100 if rep["total_s"] else 0
        bar = "█" * max(int(share / 2), 0)
        L.append(f"    {k:10s} {v['shots']:2d} shot(s)  {v['seconds']:6.2f}s "
                 f"{share:4.1f}%  {bar}")
    if rep["thin"]:
        names = ", ".join(f"{t['topic']} ({t['shots']})" for t in rep["thin"])
        L += ["",
              f"    ⚠  thinner than the others: {names} — the rest get "
              f"{rep['thin'][0]['median']}.",
              "       Not a failure. But if a subject is worth including it is "
              "usually worth",
              "       the same coverage as its neighbours; check you did not "
              "just run out of footage."]
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    wd = sys.argv[1] if len(sys.argv) > 1 else "."
    r = report(wd)
    if not r:
        print(f"no timeline.json in {wd} — nothing to report")
        sys.exit(0)
    print(render(r))
