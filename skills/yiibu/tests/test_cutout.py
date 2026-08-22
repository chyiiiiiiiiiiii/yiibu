"""The cutout variant name is checked now, because it used to not be.

`render_cutout_segment` branches on one variant and treats everything else as
the other:

    if variant == "bottom-left-small": ...
    else: ...                          # center-large

So passing "cutout-large" — the BROLL_LAYOUT name rather than the variant name
— rendered the center-large composite and returned success. Two calls asking
for two different variants came back byte-identical, no exception, no warning.
It cost a doc tile that claimed to show two layouts and showed one twice.

These tests exercise the guard directly rather than the renderer: a real call
would download the segmenter model and composite video, and a test that needs
the network to prove an argument check is a test people learn to skip.
"""
import re

import pytest

pytest.importorskip("cv2", reason="cutout needs opencv-python")
pytest.importorskip("mediapipe", reason="cutout needs mediapipe")

from modules import cutout  # noqa: E402


def test_variants_are_the_two_the_renderer_actually_branches_on():
    """If someone adds a third variant, the branch has to grow with the tuple."""
    src = (cutout.__file__).replace(".pyc", ".py")
    body = open(src, encoding="utf-8").read()
    assert set(cutout.VARIANTS) == {"center-large", "bottom-left-small"}
    for v in cutout.VARIANTS:
        assert f'"{v}"' in body


@pytest.mark.parametrize("bad", [
    "cutout-large",       # the BROLL_LAYOUT name — the mistake that shipped
    "cutout-small",
    "center_large",       # underscore instead of hyphen
    "CENTER-LARGE",       # case
    "",
])
def test_a_variant_the_renderer_cannot_draw_raises(bad):
    with pytest.raises(ValueError) as e:
        cutout._check_variant(bad)
    msg = str(e.value)
    assert repr(bad) in msg, "the rejected value has to appear in the message"
    for v in cutout.VARIANTS:
        assert v in msg, "the message has to name what IS accepted"


@pytest.mark.parametrize("good", ["center-large", "bottom-left-small"])
def test_the_variants_the_pipeline_uses_get_through(good):
    assert cutout._check_variant(good) == good


def test_the_renderer_itself_rejects_before_it_touches_anything(tmp_path):
    """Testing the helper alone would stay green if the call site were deleted.

    The check sits ahead of _ensure_model() and the pre-rendered early return,
    so this raises on the argument without a model download or a file read —
    the paths below do not exist and never get opened.
    """
    with pytest.raises(ValueError, match="unknown cutout variant"):
        cutout.render_cutout_segment(
            selfie_path=str(tmp_path / "no-such-selfie.mp4"),
            broll_path=str(tmp_path / "no-such-broll.mp4"),
            broll_is_image=False,
            start_time=0.0,
            duration=1.0,
            variant="cutout-large",
            output_path=str(tmp_path / "out.mp4"),
        )


def test_compose_only_ever_passes_a_variant_cutout_accepts():
    """Closes the loop: the guard is worthless if the one caller drifts.

    compose._prerender_cutout_segments builds the variant from the layout name;
    that expression is where a typo would land.
    """
    src = open("modules/compose.py", encoding="utf-8").read()
    block = re.search(r'variant = ([^\n]+)', src)
    assert block, "compose no longer assigns `variant` — re-point this test"
    # The assignment is a ternary on the LAYOUT name:
    #     variant = "center-large" if layout == "cutout-large" else "bottom-left-small"
    # so drop the comparison operands first. Without this the test reads the
    # layout it is switching on as a variant it passes, and fails on correct code.
    assigned = re.sub(r'==\s*"[^"]*"', "", block.group(1))
    used = set(re.findall(r'"([a-z-]+)"', assigned))
    assert used, f"no variant literals found in: {block.group(1)}"
    assert used <= set(cutout.VARIANTS), (
        f"compose passes {sorted(used - set(cutout.VARIANTS))}, which "
        f"cutout.render_cutout_segment will now reject"
    )
