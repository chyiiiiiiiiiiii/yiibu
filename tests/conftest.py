"""Test-wide guards.

`pytest` used to reach the open internet and spend money doing it. Every run of
`tests/test_broll.py` attempted a live Veo 3 generation, and the only reason it
was silent is that the API key's spend cap was already exhausted — the failure
scrolled past as an ordinary fallback message:

    [0] Generating video via Veo 3: Opening shot immediately shows the main …
    Veo 3 generation failed: … 'status': 'RESOURCE_EXHAUSTED'

The tests were not careless about it. They patch five of the six rungs in the
B-roll acquisition ladder (`search_pexels_video`, `search_pixabay_video`,
`search_pexels`, `search_pixabay`, `generate_image`). `generate_video_veo` was
added to the ladder later and no mock list grew to match — the same drift that
left three tests in that file marked "stale: written against an older fallback
chain".

So this guard blocks the two CHANNELS rather than enumerating the rungs. A new
rung added tomorrow has to reach the network through one of them, and it will be
blocked without anyone remembering to update a list:

  1. `requests` in-process — Pexels/Pixabay search and every asset download.
  2. The `.venv` subprocess launcher — how the google-genai SDK calls (Veo,
     Gemini image) get made. Patching `requests` in the parent does nothing
     about these, because the network call happens in a child interpreter.

Local subprocesses are deliberately left alone: ffmpeg, ffprobe and the rest of
the toolchain are what most of these tests legitimately exercise.

Opting in, for a test that genuinely needs the network:

    @pytest.mark.allow_network
    def test_against_the_live_api():
        ...

Nothing in the suite uses it today, and a new one should have to explain itself
in review rather than appear by accident.
"""
import pytest


class NetworkBlockedInTests(RuntimeError):
    """Raised when a test reaches for the network without opting in."""


_MESSAGE = (
    "outbound network call from a test ({what}). Tests must not depend on a "
    "remote service, and the B-roll ladder in particular costs money per call. "
    "Mock the rung you are exercising, or mark the test "
    "@pytest.mark.allow_network if it truly needs the live service."
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: this test may make real outbound calls (needs a reason)",
    )


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("allow_network"):
        return

    def blocked(what):
        def _raise(*_a, **_kw):
            raise NetworkBlockedInTests(_MESSAGE.format(what=what))
        return _raise

    # ── channel 1: requests, used by every search and download rung ──
    try:
        import requests
    except ImportError:                                   # pragma: no cover
        pass
    else:
        for verb in ("get", "post", "put", "delete", "head", "patch", "request"):
            if hasattr(requests, verb):
                monkeypatch.setattr(requests, verb, blocked(f"requests.{verb}"),
                                    raising=False)
        monkeypatch.setattr(requests.Session, "request",
                            blocked("requests.Session.request"), raising=False)

    # ── channel 2: the .venv launcher behind every google-genai SDK call ──
    # generate_video_veo and generate_image shell out to the skill's .venv
    # because google-genai is only installed there. Blocking the launcher stops
    # the child interpreter from ever starting, which is the only place the
    # parent process can still intervene.
    try:
        from modules import broll
    except ImportError:                                   # pragma: no cover
        pass
    else:
        monkeypatch.setattr(
            broll, "_get_venv_python",
            blocked("modules.broll._get_venv_python — an SDK subprocess "
                    "(Veo / Gemini image) was about to be launched"),
            raising=False,
        )
