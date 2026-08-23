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
python3 -m pytest -rs                             # 262 tests; script suites bridged in
                                                  # -rs not -q: pytest.ini already sets -q,
                                                  # and -qq hides the count and the skips
python3 -m pytest tests/test_gates.py -q          # one file
python3 -m pytest tests/test_gates.py -k sync -q  # one test
python3 tests/test_gates.py                       # script-style runner (what doctor.py calls)
python3 tests/test_house_style.py                 # re-seeds defects into a real work dir

python3 clearance.py FOOTAGE_DIR      # faces / third-party footage scan, before publishing
python3 resolve_music.py              # name -> an actual file, via a ladder that always terminates

python3 bench.py stage DEST --source FOOTAGE --agents a,b,c [--music TRACK]
                                      # one CLEAN input dir per driver, plus one shared
                                      # prompt. Copies footage only and PRINTS what it
                                      # refused — on 2026-08-22 a previous edit's config
                                      # sat in the source folder and one agent reused its
                                      # hook, its closing caption and its music
python3 bench.py finish DEST --agent NAME [--model TEXT] [--tokens-in N] [--tokens-out N]
                                      # nobody types the cost. Wall clock is measured
                                      # here; token counts and the model name are READ
                                      # from the driver's own session transcript when it
                                      # exposes one (Claude Code does, via
                                      # CLAUDE_CODE_SESSION_ID). The flags are the
                                      # fallback for a driver that cannot be read, and
                                      # what they record stays labelled `said` not `read`
python3 bench.py remusic DEST --music TRACK
                                      # swap the track AFTER staging. One command
                                      # because it is three edits — the file in every
                                      # <agent>/music/, the line in every PROMPT.md, and
                                      # bench.json — and the last two get forgotten
python3 bench.py report DEST          # one table across every driver

python3 contract_probe.py             # do the PROSE rules still produce the right judgement?
python3 contract_probe.py --runs 3    # more samples; --case NAME filters, --json for the data
python3 contract_probe.py --strict    # exit 1 on any case that did not hold every run
```

Most scripts accept `--json`.

`contract_probe.py` is **advisory and must not become a gate** — its answers
come from a live session, so they vary, and a check that flaps gets tuned
until it passes. It exists because `AGENTS.md` admits the gates are blind to
truth and omission and then covers the gap with four prose rules, each of
which has already been broken here by someone who had read it. The probe puts
three of them in front of a session that has the skill loaded and reports
which way it went. An errored run is reported separately and counts as
neither held nor broken. When `claude plugin eval` leaves early access, these
cases port to it directly and it should be preferred — it judges properly and
runs a no-plugin ablation arm; this one only greps.

## Architecture, in one paragraph

`house_style.json` is the single source of truth for the spec (font, caption
sizes and dwell, pill geometry, cover, structure, sync, bilingual, delivery). It
is read by `gates.py --preflight` *before* the edit and by the 17 gate functions
in `gates.py` *after* it — the instruction and the judgement are literally the
same file, so they cannot drift; a project overrides a key with
`WORK_DIR/house_style.local.json`, and every override is printed. `gates.py` is
the only edge to "ship", so a gate failure is a statement about the cut and
loops back to the edit, never to a patch of the encoder settings. Two entry
points share `modules/` but not a driver: `postprod.py` (one long selfie
recording, automatic cutting, ASR captions) and template mode (a folder of
clips, authored segment list, a `skills/yiibu/references/*-template.md` recipe plus a small
per-project build script composed from `modules/buildkit.py`). Node contracts
are declared as artifacts a gate can read, not conventions — `timeline.json`
(the cut itself: `id`, source `file`, `dur`; three checks read it and a
renamed key silently empties all three), `layout.json`
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
