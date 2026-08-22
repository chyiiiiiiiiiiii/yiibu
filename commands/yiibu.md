---
description: "Edit a folder of phone clips into a gated 9:16 short"
argument-hint: "FOOTAGE_DIR [event: ...] [platform: ...] [music: ...] [note: ...]"
---

# yiibu — 一步

Edit the footage the user just named into a publish-ready 9:16 short.

**Use the `yiibu` skill.** It is the contract for this work: intake, the locked
templates, the sixteen blocking gates, and the rules about what you may and may
not claim in a caption. Read it before doing anything else — the skill root is
the directory containing its `SKILL.md`, and every command in it runs from
there.

Arguments the user gave: `$ARGUMENTS`

If they gave only a folder, that is enough — everything else has a default and
you announce your plan before cutting. If they also gave context (what the
event was, the platform and length, a music direction, or a boundary like
"don't show the unreleased slides"), fold it in: the last kind is the highest
value, because privacy and must-include shots are things no amount of footage
analysis can discover.

If they gave no folder at all, ask for one. It is the single required input.

Before you cut, and in this order:

1. `python3 doctor.py` if this machine has never run the skill.
2. `python3 gates.py --preflight` — the house style, as a build checklist.
3. `python3 plan.py FOOTAGE_DIR --platform reels` — say the recommended length
   to the user before cutting anything. Length comes from retention structure,
   not from how much footage exists.

Before you hand anything over: `python3 gates.py FINAL.mp4 --work-dir WORK_DIR`
must exit 0. Exit 2 means nothing is broken but the delivery is **not
finished**, and you say which parts are outstanding. A number outside a
threshold is a failure even when you can explain it.
