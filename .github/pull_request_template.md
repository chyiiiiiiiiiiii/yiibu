<!--
Keep this short. The point is evidence, not ceremony — a box ticked without a
command run is worse than an empty template, because it looks like coverage.
Delete any section that does not apply to your change.
-->

## What this changes, and what broke to cause it

<!-- One or two sentences. If a defect prompted it, say what shipped wrong. -->

## Both suites, before and after

```
python3 doctor.py        # must end "ready" — it runs both gate suites
python3 -m pytest -q     # the whole suite, script suites bridged in
```

<!-- Paste the last line of each. If either was already red before your change,
     say so — that is a finding, not a reason to skip. -->

- [ ] Green on my machine before and after
- [ ] The core install still works: ffmpeg + Pillow + numpy only, no extras.
      CI proves this on every push; if you touched a test that imports an
      optional package, check it skips rather than fails.

## If you added a gate

Both rules exist because they were learned by getting them wrong here
(`CONTRIBUTING.md`):

- [ ] The threshold is **reproducible** — it does not flap between identical
      rebuilds. If it cannot be measured stably, make it a code default instead.
- [ ] There is a test that **reconstructs the defect** and proves the gate
      rejects it. A gate added without one rots silently.
- [ ] The number carries **provenance**: say here what real, reviewed edit it
      was measured on. Round numbers picked for feel are how the sync gate got
      its first false alarm.

## If you changed a threshold that already existed

- [ ] It is not being changed to make today's build pass. Say what you measured.

## If you added a capability

- [ ] Its row is in the capability map in `SKILL.md`. An undocumented effect
      does not exist — several shipped in code for months and were never used.

## Docs are part of the change

- [ ] No command, flag, gate count, or default in any doc became wrong because
      of this diff. `tests/test_docs.py` checks most of this and will tell you.
- [ ] No media committed — no mp4/mov/wav/mp3, no fonts without verified
      redistribution rights, nothing downloaded for a specific project
      (`NOTICE.md`).

## What you did NOT check

<!-- The most useful section. Gates find defects and are blind to truth and to
     omission: a caption can be perfectly placed and say something nobody said.
     If you did not watch the output, say that here rather than implying you did. -->
