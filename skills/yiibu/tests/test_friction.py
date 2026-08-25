"""friction.py reads the bill the gates have been running up.

Every gate here can name the shipped defect it was born from; none of them
could say what it has cost since. `build_log.jsonl` has held the answer since
the beginning — which gates were red, on which attempt, with which exact
message — and nothing ever read it back across projects.

The tests below are built on the shapes that actually appear in this repo's
own logs (76 gate runs across six projects, 2026-08-25), including the one the
tool was written to find: the same gate red twice in a row with a word-for-word
identical message, which is a render that measured the same thing and changed
nothing.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import friction  # noqa: E402
import gates  # noqa: E402


def log(tmp_path, name, rows):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "build_log.jsonl", "w", encoding="utf-8") as f:
        for i, (verdict, failures) in enumerate(rows, 1):
            f.write(json.dumps({"attempt": i, "verdict": verdict,
                                "gates_failed": sorted(failures),
                                "failures": failures}) + "\n")
    return d


DUCK = ["the music only drops 1.60 dB under speech"]
DUCK2 = ["the music only drops 1.70 dB under speech"]


def test_nothing_to_read_is_said_plainly(tmp_path):
    rep = friction.report([str(tmp_path)])
    assert rep["logs"] == 0
    assert "nothing has been gated here yet" in friction.render(rep)


def test_an_identical_repeat_is_counted(tmp_path):
    """THE signal. Two renders, same measurement, same words: the second one
    bought nothing, and that is a property of the gate's message or threshold,
    not of the person re-rendering."""
    log(tmp_path, "p", [("blocked", {"Duck": DUCK}),
                        ("blocked", {"Duck": DUCK}),
                        ("shippable", {})])
    rep = friction.report([str(tmp_path)])
    duck = next(g for g in rep["gates"] if g["gate"] == "Duck")
    assert duck["red"] == 2 and duck["repeats"] == 1


def test_a_changed_measurement_is_not_a_repeat(tmp_path):
    """Red twice with DIFFERENT numbers means the fix moved something. That is
    the gate working, and counting it as friction would push the tool towards
    recommending that real gates be loosened."""
    log(tmp_path, "p", [("blocked", {"Duck": DUCK}),
                        ("blocked", {"Duck": DUCK2})])
    duck = next(g for g in friction.report([str(tmp_path)])["gates"]
                if g["gate"] == "Duck")
    assert duck["red"] == 2 and duck["repeats"] == 0


def test_a_streak_broken_by_a_green_run_starts_over(tmp_path):
    log(tmp_path, "p", [("blocked", {"Duck": DUCK}),
                        ("shippable", {}),
                        ("blocked", {"Duck": DUCK})])
    duck = next(g for g in friction.report([str(tmp_path)])["gates"]
                if g["gate"] == "Duck")
    assert duck["repeats"] == 0, "a green run in between means the build changed"
    assert duck["worst_streak"] == 1


def test_gates_red_on_the_final_attempt_are_flagged(tmp_path):
    """Either the project was abandoned there, or it shipped by a route that
    did not go through the gate. Both are worth seeing."""
    log(tmp_path, "p", [("blocked", {"Cover": ["no cover"]})])
    cover = next(g for g in friction.report([str(tmp_path)])["gates"]
                 if g["gate"] == "Cover")
    assert cover["red_on_last_attempt"] == 1


def test_projects_are_summarised_with_attempts_to_first_green(tmp_path):
    log(tmp_path, "slow", [("blocked", {"Duck": DUCK}),
                           ("blocked", {"Duck": DUCK2}),
                           ("shippable", {})])
    log(tmp_path, "clean", [("shippable", {})])
    rep = friction.report([str(tmp_path)])
    by = {p["project"]: p for p in rep["projects"]}
    assert by["slow"]["first_green_at"] == 3 and by["slow"]["wasted"] == 2
    assert by["clean"]["first_green_at"] == 1 and by["clean"]["wasted"] == 0


def test_several_projects_are_read_at_once(tmp_path):
    log(tmp_path, "a", [("blocked", {"Duck": DUCK})])
    log(tmp_path, "b", [("blocked", {"Duck": DUCK})])
    duck = next(g for g in friction.report([str(tmp_path)])["gates"]
                if g["gate"] == "Duck")
    assert duck["projects"] == 2 and duck["repeats"] == 0, \
        "a repeat is consecutive WITHIN one project, not across two"


def test_a_corrupt_log_is_skipped_not_fatal(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "build_log.jsonl").write_text("{not json\n")
    log(tmp_path, "fine", [("shippable", {})])
    assert friction.report([str(tmp_path)])["runs"] == 1


def test_the_report_is_ordered_by_repeats_first(tmp_path):
    """Totals mislead: a gate that fires often may be guarding the thing people
    get wrong most. Wasted renders do not have that defence."""
    log(tmp_path, "p", [("blocked", {"Audio": ["a"], "Duck": DUCK}),
                        ("blocked", {"Audio": ["b"], "Duck": DUCK}),
                        ("blocked", {"Audio": ["c"]})])
    order = [g["gate"] for g in friction.report([str(tmp_path)])["gates"]]
    assert order[0] == "Duck", order


# ── what the first real run of this tool found ──────────────────────────

def test_a_near_miss_does_not_print_as_the_threshold_itself():
    """`{drop:.1f}` printed the measurement at the SAME precision as the
    threshold, so 3.96 came out as "only drops 4.0 dB (house minimum 4.0 dB)"
    — a sentence that says you met the bar while blocking you. Two projects
    each spent a render on it."""
    msg = gates._duck_message(3.96, 4.0)
    assert "4.0 dB under speech" not in msg
    assert "3.96" in msg and "short by 0.04" in msg


def test_a_bed_that_gets_louder_says_so():
    """Reported as "only drops -1.6 dB", which reads like a rounding quibble.
    It is the opposite failure: the bed is competing with the speech."""
    msg = gates._duck_message(-1.6, 4.0)
    assert "LOUDER" in msg and "-1.6" not in msg


def test_the_ordinary_case_still_names_the_fix():
    msg = gates._duck_message(1.6, 4.0)
    assert "speech_spans" in msg and "1.60 dB" in msg
