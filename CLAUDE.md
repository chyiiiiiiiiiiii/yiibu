# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The standard is AGENTS.md — imported, never restated

The next line inlines the portable contract verbatim at load time. It is the
single source of truth for *making a video*: if a rule belongs to it, change it
**there**, not here. A rule copied into two files is a rule that will disagree
with itself.

@AGENTS.md

Everything below is the deliberate remainder — what `AGENTS.md` leaves out
because it is not portable: the doc map, working on the skill's own code, and
the Claude-Code-specific parts.

## Which doc for which job

Two distinct jobs happen in this repo, and they read different docs.

| you are | read |
|---|---|
| **editing a video** with the skill | the contract above, then `skills/yiibu/SKILL.md` (intake, capability map, sub-agent rules) and the matching `skills/yiibu/references/*-template.md` |
| **changing the skill's code** | `skills/yiibu/ARCHITECTURE.md` (why it is shaped this way) and `skills/yiibu/CONTRIBUTING.md` (the "what belongs where" table — consult it *before* adding a rule; wrong layer is the common mistake) |
| installing / API keys / fallback chains | `skills/yiibu/SETUP.md`, `skills/yiibu/docs/CONFIGURATION.md` |
| seeing a worked edit, gate failures included | `skills/yiibu/docs/WALKTHROUGH.md` |

## Commands the contract does not cover

```bash
cd skills/yiibu        # every command below runs from the skill root
python3 -m pytest -q                              # 221 tests; script suites bridged in
python3 -m pytest tests/test_gates.py -q          # one file
python3 -m pytest tests/test_gates.py -k sync -q  # one test
python3 tests/test_gates.py                       # script-style runner (what doctor.py calls)
python3 tests/test_house_style.py                 # re-seeds defects into a real work dir

python3 clearance.py FOOTAGE_DIR      # faces / third-party footage scan, before publishing
python3 resolve_music.py              # name -> an actual file, via a ladder that always terminates
```

Most scripts accept `--json`.

## Architecture, in one paragraph

`house_style.json` is the single source of truth for the spec (font, caption
sizes and dwell, pill geometry, cover, structure, sync, bilingual, delivery). It
is read by `gates.py --preflight` *before* the edit and by the 16 gate functions
in `gates.py` *after* it — the instruction and the judgement are literally the
same file, so they cannot drift; a project overrides a key with
`WORK_DIR/house_style.local.json`, and every override is printed. `gates.py` is
the only edge to "ship", so a gate failure is a statement about the cut and
loops back to the edit, never to a patch of the encoder settings. Two entry
points share `modules/` but not a driver: `postprod.py` (one long selfie
recording, automatic cutting, ASR captions) and template mode (a folder of
clips, authored segment list, a `skills/yiibu/references/*-template.md` recipe plus a small
per-project build script composed from `modules/buildkit.py`). Node contracts
are declared as artifacts a gate can read, not conventions — `layout.json`
(each caption style declared `caption`/`pill`/`free`), `cover_meta.json`,
`pills.json` + `pills/*.png`, `words.json`, `decisions.json` — each added after
a defect that was invisible precisely because the contract was implicit.

## Changing the code

- **Derive values from what they depend on; do not hard-code them.** The worst
  bug in this repo's history was `TAIL_FADE = 3.0`, chosen for a closing shot
  that was later shortened — the fade then swallowed the whole payoff card.
  Prefer an edge (`min(1.0, closing_dur * 0.5)`) and let the gate be the second
  line of defence, not the only one.
- **No gate without a reproducible threshold**, and **no gate without a test
  that reconstructs the defect** (`tests/test_gates.py`,
  `tests/test_house_style.py`). A new threshold needs provenance: say in the
  commit what real, reviewed edit it was measured on.
- **Docs are part of the diff.** `tests/test_docs.py` globs every `*.md` and
  asserts documented flags exist, every flag is documented, prose numbers match
  `house_style.json`, every gate has a test, and the `references/examples/`
  build scripts still pass `build_lint`. A stale doc is a red test, not a
  politeness.
- **Never leave a test as `xfail` with a plausible sentence** — it is
  indistinguishable from a test marked stale because the code is broken. That
  already hid a real bug here. Fix it, rewrite it against the current API, or
  delete it.
- New capability → add its row to the capability map in `skills/yiibu/SKILL.md`. Several
  effects shipped in code for months with zero mention and were never used.
- Python, stdlib + Pillow + numpy at the core; anything heavier is optional and
  must skip cleanly when absent.
- **Never commit media** — no mp4/mov/wav/mp3, no fonts without verified
  redistribution rights, nothing downloaded for a specific project. See
  `.gitignore` and `NOTICE.md`.

## Sub-agents

The plugin root's `agents/*.md` (`footage-scout`, `slide-reader`, `transcript-proofer`,
`edit-critic`) are accelerators, not dependencies — the contract above lists the
portable command behind each. Delegate **evidence**, never **judgement**: the
edit itself and caption wording stay in the main context, because choosing which
shots earn a place, in what order, and where the hook lands requires holding the
whole folder in mind at once.
