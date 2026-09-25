"""Intake: what plan.py claims, and what it actually puts in front of you.

Both cases here are the same 2026-09-01 defect seen from two sides — a hook was
chosen off a single 300px mid-frame per clip, and the tool that was supposed to
help pointed the other way.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plan as plan_mod  # noqa: E402


def _clip(path, dur, colour):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c={colour}:s=1080x1920:r=30:d={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={dur}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", path],
        check=True, capture_output=True)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    d = tmp_path_factory.mktemp("footage")
    # the shape that broke it: the interesting clip is one of the SHORTEST
    for name, dur, col in [("long_a.mp4", 4.6, "slategray"),
                           ("long_b.mp4", 4.3, "darkgreen"),
                           ("long_c.mp4", 4.2, "sienna"),
                           ("the_hook.mp4", 1.5, "indigo")]:
        _clip(str(d / name), dur, col)
    return str(d)


def test_plan_does_not_call_a_duration_sort_a_hook_suggestion(folder):
    """`hook_candidates` was `sorted(clips, key=-dur)[:3]`, printed under the
    words 「開場那 2 秒要放全資料夾最奇怪的畫面」. Code ranked by length while the
    label promised strangeness.

    On the 0901 folder it returned the three longest clips and the hook the user
    actually chose was 1.49s — 4th shortest of 23 — so no amount of re-ranking
    that list could have surfaced it. The fix is not a better hook metric (face
    area and motion were both measured against a known answer and both failed);
    it is to stop claiming the arithmetic knows.
    """
    p = plan_mod.plan(folder, "reels")
    assert "hook_candidates" not in p, (
        "plan.py is advertising a hook suggestion again — nothing measurable in "
        "this repo predicts a good hook; face area fit one case by luck and "
        "motion ranked the wrong shot higher than the right one")
    assert p["longest_clips"][0] == "long_a.mp4"
    assert "the_hook.mp4" not in p["longest_clips"]


def test_plan_builds_a_filmstrip_per_clip(folder, tmp_path):
    """A botched take is botched in every frame; a single mid-frame hides that.

    The shot picked as the 0901 hook is a neck and an ear in five of its six
    frames, and its one readable frame sits outside the range that was cut. The
    food template had asked for six-frame filmstrips since 2026-08-10 — as prose,
    so it was skipped. plan.py builds them now.
    """
    out = str(tmp_path / "sheets")
    p = plan_mod.plan(folder, "reels", sheets_dir=out)
    sheets = p["sheets"]
    assert sheets and sheets["frames_per_clip"] >= 6
    assert os.path.exists(sheets["contact_sheet"])
    assert len(sheets["filmstrips"]) == 4, "one filmstrip per clip"

    from PIL import Image
    strip = Image.open(sheets["filmstrips"][0])
    # a strip of N frames is much wider than tall; a single frame is portrait,
    # so this is what separates "built a filmstrip" from "saved one frame"
    assert strip.width > strip.height * 3, (
        f"{strip.size} is not a filmstrip — a single 9:16 frame would fail this")


def test_no_sheets_is_available_but_not_the_default(folder):
    """Skipping is allowed; skipping SILENTLY is what happened last time."""
    p = plan_mod.plan(folder, "reels")          # no sheets_dir -> none built
    assert p["sheets"] is None
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "plan.py"), encoding="utf-8").read()
    assert "--no-sheets" in src and "_sheets" in src, (
        "the CLI must default to BUILDING the sheets, with an explicit opt-out")
