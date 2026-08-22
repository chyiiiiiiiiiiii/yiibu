# Contributing

The thesis of this repo is that quality lives in checks, not in prose. A
contribution that follows that thesis is easy to merge; one that fights it is
not, however good the code.

## Before you start

```bash
python3 doctor.py        # must end "ready" — it runs both gate suites
python3 -m pytest -q     # the whole suite, script suites bridged in
```

Both must be green on your machine before AND after your change.

## The two rules for adding a gate

Both were learned by getting them wrong here:

1. **No gate without a reproducible threshold.** The first `gate_music_bed`
   used an absolute −40 dBFS line that sat inside AAC coding noise: identical
   settings measured 1.18s of dead tail on one rebuild and 2.93s on the next.
   A gate that flaps gets tuned until it passes — which is the failure it
   exists to prevent. If it cannot be measured stably, make it a code default
   instead (`cover.draw()`, `modules/bgm.py` are the pattern).
2. **No gate without a test that reconstructs the defect.** `tests/test_gates.py`
   and `tests/test_house_style.py` re-seed every defect that ever shipped and
   assert the gate still rejects it. A gate added without one rots silently —
   that has already happened once in this file's history.

A new threshold also needs **provenance**: say in the commit or the comment
what real, reviewed edit it was measured on. Round numbers picked for feel are
how the sync gate got its first false alarm.

## What belongs where

| change | goes in |
|---|---|
| a measurable, stable rule the video must satisfy | `house_style.json` + a gate in `gates.py` + a test |
| the safe way to construct something (encoder, fade, pill) | a code default in `modules/`, ideally a `buildkit.py` primitive |
| a choice only the user can make | `decisions.json` schema (`REQUIRED_DECISIONS` in `gates.py`) |
| a build-script antipattern that produces a fine-looking file slowly | `build_lint.py` |
| judgement (hook choice, pacing, wording) | nowhere — leave it free, that is deliberate |

## If you add a capability

Add its row to the capability map in `SKILL.md`. An undocumented effect does
not exist: several shipped in code for months with zero mention and were
therefore never used.

## Style

- Python, stdlib + Pillow + numpy at the core; anything heavier is optional
  and must skip cleanly when absent (see the fallback chains in `SETUP.md`).
- Match the surrounding code's comment density and naming.
- Docs are part of the change: if a command, flag, gate count, or default in
  a doc becomes wrong because of your diff, fix the doc in the same commit.

## Media

Never commit audio, fonts you have not verified redistribution rights for, or
anything downloaded for a specific project. See `NOTICE.md`.
