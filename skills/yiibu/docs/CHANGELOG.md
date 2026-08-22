# yiibu — Change Log

Reverse-chronological. Each entry: what changed, why, tests, files.
Full technical + techniques reference: [audio-boundary-fades.md](./audio-boundary-fades.md).

---

## 2026-08-22 · Asking the contract whether it still produces judgement

`claude plugin eval` is the right tool for this and it is gated behind early
access on this account — `init` and `eval` both refuse, there is no local
toggle. So this is the version that runs today, and it should be replaced the
moment that gate lifts.

### Why

`AGENTS.md` admits the gates are structurally blind to truth and omission, then
covers the gap with prose. Three of those rules have each already been broken
here by someone who had read them:

- §4 anything you cannot confirm goes in an authored style, never a verbatim one
- §6 a number outside the threshold is a failure EVEN WHEN you can explain it
- §7 say "it passes the gates", never "it is finished"

### What was added

`contract_probe.py` — puts each rule in front of a live session that has the
skill loaded and reports which way it went. **Advisory, and it must not become
a gate**: the answers vary between runs, and CONTRIBUTING is explicit that a
check which flaps gets tuned until it passes. It sits with `coverage.py`, not
with `gates.py`.

Two findings from building it, both recorded in the file:

- The first matcher for §7 scored a model answer of *"It passes all sixteen
  gates … so it isn't finished"* as a FAILURE, because it required "passes the
  gates" adjacent. That is a broken matcher rejecting a correct answer, not a
  threshold being loosened — the distinction is written into the code comment
  so the next reader can tell which kind of edit it was.
- An errored run was being counted as a violation. That conflates "we could not
  ask" with "the contract broke", which is the same silent conflation banned
  elsewhere in this repo today. Errors are now reported separately and count as
  neither.

### Verified

- All three cases held 2/2 on the final run, and §7 held 3/3 on a separate
  sample taken while diagnosing the matcher.
- 259 pass. `test_every_flag_is_documented` caught the three new flags before
  they could ship undocumented, which is the guard working as intended.
- The stale "221 tests" in CLAUDE.md — wrong since before today — is now 258,
  and the pytest line says `-rs` rather than `-q` for the reason recorded above.

---

## 2026-08-23 · ffmpeg 8 breaks single-image output, and the macOS leg found it

The macOS leg ran for the first time in this workflow's history and failed. It
was worth its cost inside ninety seconds.

### What it found

Homebrew now pours **ffmpeg 8.1.2**; this laptop has 7.1.1. Writing one image to
a filename with no `%d` pattern was a WARNING through 7.x —

    The specified filename '...' does not contain an image sequence pattern
    Use ... the -update option (with -frames:v 1 if needed) to write a single image

— and exits 0. On 8.1 it is `Error opening output files: Invalid argument`,
exit 234. Anyone running `brew install ffmpeg` today gets 8.x.

Eight call sites do exactly this. Three are **inside `gates.py`**, and — this is
the part worth reading twice — they do NOT behave the same way, because each sits
under a different exception handler:

| gate | handler | on ffmpeg 8 |
|---|---|---|
| `gate_cover` | `fails.append(f"cover check failed: {e}")` | fails loudly — confusing, but safe |
| `gate_structure` | `fails.append(f"end-card check failed: {e}")` | fails loudly — safe |
| `gate_pill` | `except Exception: continue` | **reports `faded_pills: 0` and PASSES** |

`gate_pill` is the dangerous one. Every pill's frame extraction raises, each is
swallowed by `continue`, and the gate concludes that nothing fades in — on a cut
where every pill might. A gate that cannot measure reports clean. That bare
`continue` is a latent defect on its own, independent of ffmpeg: any reason the
extraction fails turns into a pass. Whatever fixes the ffmpeg argument should
also make that path record that it could not check, the same distinction between
"we could not ask" and "it is fine" that `contract_probe.py` and the test-count
guard were both corrected for this week.

The eight sites:

| where | writes |
|---|---|
| `gates.py:355` | `f1.png` — the cover gate's first frame |
| `gates.py:638` | `pill0.png` — the pill gate, the silent one |
| `gates.py:835` | `last.png` — the structure gate's closing frame |
| `clearance.py:168` | the frame the vision call reads |
| `docs/make_demos.py:130,164` | demo frame and palette |
| `tests/test_buildkit.py:80`, `tests/test_font_resolution.py:150` | test fixtures |

Not affected: anything writing to a pipe (`-f rawvideo -`, `verify.py:642`,
`clearance.py:103`) or to video (`buildkit.py:185`, qtrle) — the image2 muxer is
never involved.

### Fixed here

`-update 1` added to the five outside `gates.py`. Verified backward compatible:
on 7.1.1 it exits 0, writes the file, and silences the warning.

**`gates.py` is deliberately NOT touched.** The working tree carries 125
uncommitted lines in it from other work in progress (a seventeenth gate), and
staging that file would sweep unfinished work into this commit. The three lines
sit at 355/638/835, the WIP is all past 1402, so there is no conflict — the fix
is one argument in three places whenever that work lands.

### Also

`test_libass_substitutes_a_missing_font_instead_of_failing` asserted
`returncode == 0` with the message "ffmpeg errored — the premise of the fix
changed". That covers both "the invocation is wrong on this ffmpeg" and "libass
now rejects a missing font", which call for opposite responses; the CI failure
was the first and the message could not say so. It now reports the exit code and
stderr and states which kind of failure it is not evidence of.

---

## 2026-08-22 · Public — and the two things "Still not verified" said were not

Both entries below that end with an unverified list can now be closed. The
lists are left as written; this is what happened to them.

### CI has been green, and going public is what did it

Every `checks` run from 6537d08 onward ended in 3–4s with "the job was not
started because recent account payments have failed". The workflow was never
wrong — the runners never started, so those thirteen red marks said nothing
about the code. GitHub does not bill standard runners on public repositories,
and re-running the last failed run immediately after the visibility change
started it. **Four consecutive green runs since**, 247 passed / 12 skipped on
both ubuntu legs, matching the local 259-collected exactly.

Its first green run earned its keep inside a minute: a `DeprecationWarning` for
`Image.getdata()`, removed in Pillow 14, in a test written that same morning. It
surfaced only on the py3.12 leg, where pip resolves Pillow 12; the py3.9 floor
gets 11.3 and says nothing. Fixed with numpy.

The same run's Node 20 notice is also closed — `actions/checkout` and
`setup-python` both went to v7 after checking `action.yml` rather than assuming:
`using: node20` at the old pins, `node24` at v7.

### Installing from GitHub works

`marketplace add chyiiiiiiiiiiii/yiibu` → clone → `install` → Skills (1),
Agents (4). A live session quotes `SKILL.md`'s description with its trigger
phrases and resolves all four `yiibu:` agents. Verified anonymously too, with
no token: the API, the web page, the README's images and
`.claude-plugin/marketplace.json` all return 200, so the install path a reader
follows actually resolves.

The daily setup is back on the local directory marketplace afterwards —
in-place, edits live, no second copy.

### Still not verified

The **macOS leg has never executed**, in the entire history of this workflow.
It runs only on schedule or `workflow_dispatch`, and until today CI could not
start at all — so its YAML, including the `-rs` change and the guard that fails
the leg if `h264_videotoolbox` disappears from the runner image, has never run
once. It is also the only place `tests/test_buildkit.py`'s seven tests execute;
they skip on Linux by design. `gh workflow run checks --ref main`, and it is
free now that the repo is public.

---

## 2026-08-22 · The advertised test count now has to be true

CLAUDE.md states how many tests there are. It said **221** for long enough that
nobody remembers when it stopped being true — and the correction to it, written
this morning, was **wrong within the hour** (258 against a real 259, because it
was typed while one test was still failing). A number a human retypes is a
number that rots; that is the whole thesis of this repo, applied to itself.

`test_docs.py::test_the_documented_test_count_is_the_real_one` compares the
comment on CLAUDE.md's pytest line against `len(session.items)`. It skips on a
`-k`, a `-m`, or a named path, because a subset run was never counting the same
thing — asserting there would make the guard fail on `pytest tests/test_gates.py`,
which is a guard people learn to ignore.

Caught the drift on its first real run: "CLAUDE.md says 258 tests, the suite
collects 260". Now 260, and it cannot silently go stale again.

Checked while there and left alone: the "sixteen gates" figure repeated across
README, AGENTS.md and the plugin description is real — `gates.py` defines 16
`gate_` functions and `test_gate_count_in_docs_matches_gates_py` already guards
it.

---

## 2026-08-22 · The doctrine reaches the package

Every gate in this repo judges the video. Today's four defects were all in the
delivery vehicle instead — font provisioning wired to one entry point of two, a
test file absent from CI, a pre-rename env var, a plugin namespace collision —
and not one of them was a thing a gate could see. Writing them down as things
to remember would be the exact failure this repo exists to argue against.

### New guards

`tests/test_plugin.py` (10 tests) — the manifests agree on name and version
(`claude plugin tag` refuses to release when they do not, which finds the drift
mid-publish); the marketplace source resolves; **no two components claim the
same name**, reconstructing the collision that made `SKILL.md` unreachable;
every agent declares the name/description/tools its loader needs, with the
frontmatter name matching the filename that the namespace actually uses; every
agent on disk is named in `AGENTS.md` or `CLAUDE.md`, so a rename cannot
silently break the promise made to a non-Claude driver; and `claude plugin
validate` passes with no warnings wherever the CLI is on PATH.

`test_docs.py::test_no_test_file_can_remove_itself_from_collection` — bans
module-level `importorskip`. It deletes a whole FILE from the run and the only
trace needs `-rs` to show. A per-test skip is counted and named; a module-level
one is a silent cap.

### Verified

- 258 pass with full deps; **258 collected** on a core install (254 pass, 4
  skip) — the parity that was broken this morning holds.
- Both new guards shown red against a reconstruction of the real defect: a
  `commands/yiibu.md` put back beside the skill, and an `importorskip` seeded
  into `test_cutout.py`.

---

## 2026-08-22 · The plugin shipped with its own skill unreachable

Found by installing it. Nothing short of a real `plugin install` could have
surfaced this — the manifests validate, the files are all present, and the
repo's own suite has no opinion about what a plugin namespace does.

### What was wrong

`commands/yiibu.md` and `skills/yiibu/SKILL.md` both claimed the name `yiibu`
inside the plugin's namespace. The command won. Measured on a real install:

- the available-skills listing carried **one** `yiibu` entry, and its
  description was the command's terse one-liner;
- `SKILL.md`'s description — the one carrying every trigger phrase, `剪影片`,
  `後製`, `一步`, `video postprod` — never reached the model, so saying
  "幫我剪影片" would not have fired anything;
- invoking `yiibu:yiibu` loaded the ~1,900-character command file, not the
  49,722-character contract. The command's own text says "**Use the `yiibu`
  skill**", which now resolved back to the command. A loop.

So the plugin installed cleanly, validated cleanly, listed four working
subagents, and could not reach the thing it exists to ship.

### What changed

`commands/yiibu.md` is deleted. It was duplication in the first place: every
line of it — the single required input, the defaults that are stated rather
than interrogated, the privacy boundary being the question worth asking, the
preflight order — is already in `SKILL.md`'s intake section, in more detail.
Per this repo's own rule, a rule copied into two files is a rule that will
disagree with itself; here the copy did worse than disagree, it shadowed the
original.

`/yiibu` survives: with the collision gone the skill answers to it directly.
Verified in a live session — the listing shows the full trigger-phrase
description, and `/yiibu` resolves to `yiibu:yiibu`.

### Verified

- `claude plugin details yiibu` → Skills (1) yiibu, Agents (4). Before the fix
  it read Skills (2) yiibu, yiibu.
- Live session listing quotes `SKILL.md`'s description verbatim, trigger
  phrases included; all four agents resolve as `yiibu:<name>`.
- `claude plugin validate .` passes with no warnings (an unknown
  `metadata.homepage` field was also dropped from `marketplace.json`).
- Install path exercised end to end from a local directory marketplace:
  `marketplace add` → `install` → `details` → `marketplace update`.
- 247 pass, `doctor.py` exit 0.

### Still not verified

Installing from the **GitHub** source rather than a local path — the repo is
private, so `marketplace add chyiiiiiiiiiiii/yiibu` has never been run. And
GitHub Actions has never started a job: every run since 6537d08 ends in 4s with
"the job was not started because recent account payments have failed". CI is
**not** known to be green.

---

## 2026-08-22 · Two checks that were not running, and one that ran on nothing

Pre-public sweep. Nothing here is a new feature; all three are checks that
looked present and were not.

### What was wrong

- **The house font was provisioned by one entry point out of two.**
  `ensure_fonts()` — which puts the bundled 演示斜黑体 where fontconfig can see
  it — had exactly one caller, `postprod.py`. Template mode, the
  folder-of-clips path a fresh clone runs first, never called it. libass does
  not fail on a missing font; it substitutes one and exits 0. Measured: an
  `.ass` naming `ThisFontDoesNotExist12345` rendered legible CJK text with
  ffmpeg returning 0. And `gate_typography` reads the Fontname DECLARED in the
  `.ass`, not the face libass used — so the whole video comes out in the wrong
  typeface with sixteen gates green. This is the exact shape the repo exists to
  prevent: a rule kept as an ordering convention rather than as a check.
- **`tests/test_cutout.py` did not run on CI, and said nothing about it.**
  `modules/cutout.py` imported cv2 and mediapipe at module scope, so
  `importorskip` took all ten tests out of collection on any core install —
  which is the only configuration the every-push Linux leg has. Those ten
  guard `_check_variant`, the argument check added *this week* after two calls
  asking for different variants came back byte-identical. The guard was tested
  nowhere that runs. Worse, the leg's `pytest -q` resolved to `-qq` (pytest.ini
  already sets `-q`), so the log printed neither the count nor the skip.
- **The rename to yiibu left a live env var behind.** `_find_font` read
  `VIDEO_POSTPROD_FONT` while every document advertised `YIIBU_*`, so the
  documented way to point at a font file did nothing. `test_docs.py`'s env
  guard could not see it — it only matches `YIIBU_[A-Z0-9_]+`, and a
  pre-rename leftover is precisely the string that pattern cannot match.

### What changed

- `burn_subtitles()` calls `ensure_fonts()` before ffmpeg. Provisioning now
  sits at the single point every caption burn passes through, per
  CONTRIBUTING's "the safe way to construct something → a code default in
  `modules/`". It is idempotent and a no-op once the font is in place.
- `modules/cutout.py` imports cv2 and mediapipe inside
  `render_cutout_segment`, after the variant guard and the prerendered
  pass-through. Argument handling is now reachable without the heavy stack.
- `VIDEO_POSTPROD_FONT` → `YIIBU_FONT_FILE`, documented in
  `docs/CONFIGURATION.md` and `SETUP.md`. Nothing had it set anywhere.
- CI runs `pytest -rs` on both legs, so every skip is named in the log.

### New guards

- `tests/test_font_resolution.py` — six tests the ladder never had: burning
  captions provisions the font *before* ffmpeg runs, `ensure_fonts` is
  idempotent, `YIIBU_FONT_FILE` beats every other rung, the bundled asset is
  reachable as the last resort, it is openable, and — reconstructing the
  defect — libass substitutes a missing font instead of failing.
- `test_docs.py::test_the_pre_rename_name_is_gone_from_the_code` — the rename
  now lives in a test rather than in a memory. CHANGELOG.md is exempt; it has
  to be able to say the old name.
- `test_documented_env_defaults_match_the_code` now checks only the row that
  DEFINES a variable (first table cell). Matching every mention made an
  ordinary cross-reference read as a drifted default — a guard that punishes
  writing a good doc. Verified it still catches a drifted default.

### Verified

- 247 pass with full deps; **247 collected, 243 pass, 4 skip** on a core
  install (ffmpeg + Pillow + numpy + pytest). Before: 237 collected, 232 pass.
  The ten cutout tests now run on the configuration CI actually uses.
- Every new test shown red against the unfixed code before being accepted.
- End-to-end: a real template-mode build script bootstrapped the documented way
  burned captions through `burn_subtitles` — exit 0, 2.000s, glyphs present.
- Fresh `git clone` + a venv with only pillow/numpy/pytest: `doctor.py` exit 0,
  suite exit 0. This is the CI Linux leg's steps run locally — **not** evidence
  that GitHub Actions is green, which remains unproven.
- `doctor.py` exit 0; `build_lint.py` clean on all five shipped examples.

---

## 2026-08-22 · Ships as a plugin, and the skill directory's work comes home

### What was wrong

- **The repo was not what the author ran.** `~/.claude/skills/video-postprod`
  had diverged in both directions: it carried `gate_audio_policy` — a
  SIXTEENTH gate, for a 48s food 花絮 that shipped with the room's audio under
  all of it because "the ambience IS the soundtrack" was applied to every shot
  — plus `modules/audio_scout.py`, `music_entry.py` and `mixcheck.py`, none of
  which were ever committed. Publishing without them would have shipped the
  author's tool minus one of its gates.
- **Installing meant knowing where to clone.** No plugin manifest, so no
  `/plugin install`, no `/yiibu`, and the four subagents had to be copied by
  hand.
- **The rename to yiibu had only reached the frontmatter.** `doctor.py` still
  printed `video-postprod` as its banner, work products still landed in
  `/tmp/video-postprod`, and five example scripts still named a skill-root
  fallback directory that no longer exists.
- **`docs/CONFIGURATION.md` documented the opposite of the house rule.** It
  said `YIIBU_DELIVERY_BITRATE` defaults to `2400k` and explained why the
  deliverable is capped, after 268d74e had changed the code to `20M` on the
  user's explicit instruction to stop trading picture quality for file size.

### What changed

- The merge was clean — the two sides had touched almost disjoint files — and
  the guards added earlier the same day did the work: the moment `gates.py`
  grew a sixteenth entry, the gate-table guard named `AudioPolicy` as missing
  from all three tables and the count guard listed every stale number.
- Plugin layout, read off the official plugins rather than guessed:
  `.claude-plugin/{plugin,marketplace}.json`, `commands/yiibu.md` for `/yiibu`,
  and the skill under `skills/yiibu/` because that is where a plugin's skills
  must live. `agents/` moves UP to the plugin root, which is functional rather
  than cosmetic — installing the plugin now installs the four subagents.
- `AGENTS.md` and `CLAUDE.md` stay at the REPO root. The first restructure
  buried both inside the skill, which broke the one thing AGENTS.md exists for:
  Codex and the rest look for it at the root, so the portable contract had
  become unreachable by exactly the tools its first line addresses.
- `install.sh` covers what a plugin cannot — ffmpeg, the two core packages,
  optionally the faster-whisper venv — then hands over to `doctor.py`. Both
  READMEs gained a real Install section for all three paths.

### New guards

- `test_documented_env_defaults_match_the_code` — the old env-var guard only
  checked that a NAME appeared on the page, so a default could drift forever.
  It found the delivery bitrate on its first run.
- The flag guard now reads `*.sh`, so renaming `install.sh --full` breaks the
  READMEs here instead of silently.
- `test_translations_link_back_to_their_original`, matched by path because this
  repo has three `README.md` files.

### Verified

246 tests green from the new skill root; `doctor.py` ready. `scripts/` was
NOT adopted — measured at 301 references, about half of them prose using the
filename as a noun, and recorded in ARCHITECTURE as a decision rather than
left as an unexplained deviation.

---

## 2026-08-22 · Pre-release: the core install was never actually tested

### The failures these fix

- **`pytest` was red on the install the README promises.** With ffmpeg, Pillow
  and numpy and nothing else, four tests failed. Two patched an attribute on
  `modules.broll.requests`, which is `None` when the package is absent. One
  imported `modules/cutout.py`, which hard-imports cv2 and mediapipe. The
  fourth is the interesting one: `tests/test_silence_cut.py` probed for
  auto-editor by shelling out to whatever `python3` is first on PATH, while
  `modules/silence_cut.py` checks `find_spec` in the running interpreter. In a
  venv the two disagreed — the code correctly skipped silence removal, the test
  found the system copy, did not skip, and failed on the empty result. A probe
  that asks a different question than the code reports a red suite for a machine
  that is behaving correctly.
- **`tests/test_buildkit.py` had no platform guard.** Its fixture builds a clip
  with `h264_videotoolbox`, so on Linux the whole module errored. A fresh clone
  there ran the suite and got red on its first command — the exact failure
  `conftest.py` exists to prevent, in the file next to it.
- **Nothing ran any of this on a push.** The repo argues that quality lives in
  executable checks and then shipped with no CI, which makes the argument
  decorative.

### What changed

- `.github/workflows/ci.yml` runs `doctor.py` and `pytest` on ubuntu and macOS,
  Python 3.9 and 3.12, installing **only** pillow and numpy — not
  requirements.txt — so the README's headline promise is proved on every push
  rather than assumed.
- Optional dependencies now skip with a reason instead of failing: stock-B-roll
  tests when `requests` is absent, the module-import check when a THIRD-PARTY
  name is missing (an ImportError naming one of our own modules still fails, and
  the source is compiled either way so the syntax half never goes missing), and
  the whole buildkit module when the encoder it locks does not exist.
- `cutout.render_cutout_segment` rejects an unknown variant instead of rendering
  the default. It branched `if variant == "bottom-left-small" ... else`, so the
  BROLL_LAYOUT names produced two identical clips from two different requests.
- `NOTICE.md` covers `docs/gallery/` — the layout tiles carry incidental
  third-party material and one open question about a stock library's terms.

### Verified

Fresh `git clone` to a new path: `doctor.py` ready, 240 tests green. Separate
venv with only pillow, numpy and pytest: green, 5 skips, 0 failures.

---

## 2026-08-18 · Open-source hardening: no bundled audio, portable paths, bridged suites

### The failures these fix

- The repo could not pass its own doctor: the gold-keyword gate (08-17) was
  added without updating two "good" fixtures in `tests/test_house_style.py`,
  and plain `pytest` never noticed because the two gate suites are runnable
  scripts pytest collects zero tests from.
- `modules/broll.py` hardcoded the author's install path for `.env.pexels` /
  `.env.pixabay`, so anyone who cloned elsewhere lost stock B-roll forever
  with only a "key not found" line. Same disease in the example build scripts.
- The bundled Mixkit mp3s were redistribution we had no verified licence for.

### What changed

- **Fixtures now wear the house look** (three gold spans) and
  `tests/test_suite_bridge.py` runs both script suites under pytest — a red
  script suite is now a red `pytest`.
- **Paths resolve relative to the clone**: `SKILL_DIR`-based key loading with
  `PEXELS_API_KEY` / `PIXABAY_API_KEY` env overrides; example scripts find the
  skill root by walking up from their own location (`YIIBU_SKILL_DIR` overrides).
- **No audio ships**: `bgm-library/` and `sfx-library/` gitignore all audio;
  `bgm-library/README.md` documents the two-minute fill; `NOTICE.md` states the
  rule. `config._default_bgm()` and the sfx step already degrade cleanly.
- **Docs synced to code**: 12 gates (not 8) in every gate table; the music
  ladder documented as wired into `postprod.py --music`; ducking documented as
  numpy `duck_gain` (sidechaincompress is a lint-blocked antipattern);
  `SETUP.md` rewritten against the real dependency tiers; `CONTRIBUTING.md`
  extracted the two add-a-gate rules; READMEs gained a reading map and a
  platform statement (buildkit is macOS-only today).

## 2026-08-17/18 · Ladders, decisions, buildkit — quality bar moves out of prose

Compressed from the commit log; each has full detail in `git log`.

- **`resolve_music.py`** (e01a1d4) — the four-rung music ladder that never
  stalls; stand-ins are named `-standin-<mood>`, never as the requested track.
- **`gate_music_bed`** (e01a1d4, tests d6d8717) — the bed must outlive the
  video; measured by subtracting the no-music sibling. Threshold is RELATIVE
  (25 dB under the bed's own median) because a fixed −40 dBFS line sat inside
  AAC coding noise and flapped between rebuilds.
- **Locked cover gold** (e01a1d4) — `cover.subtitle_gold #F6DB66` in
  `house_style.json`; `cover.draw()` defaults to it via `_house_gold()`.
- **Decisions / Deliverables / CoverColour gates + tri-state exit** (2f78946) —
  `decisions.json` required; exit 2 = "nothing broken but NOT finished";
  a deferral must be recorded to take effect. `end_card:off` with a written
  why is terminal, exit 0 (2f8b7a7).
- **numpy ducking** (2f78946) — `sidechaincompress` silently dropped the bed
  ~1.6s before a delivery's end; replaced with `duck_gain()`, gain reduction
  bounded by construction, bed length asserted against speech.
- **`modules/buildkit.py` + `build_lint.py`** (fb30722) — the 1-hour build
  becomes a 15-minute one: proven primitives encode the known ffmpeg traps;
  the linter rejects a build script carrying the slow/hang antipatterns
  before it runs, and buildkit self-lints its caller on import (2e39fcb),
  `YIIBU_SKIP_LINT=1` as the written-reason escape hatch.
- **Gold keyword layer machine-checked** (02ff265) — an all-white caption pass
  shipped and the user caught it, not the gates; `min_spans 3` at the locked
  #F6DB66, plus a per-span font-size state machine in the width check.
- **Capability map** (616b6e0) — every effect gets a row in SKILL.md; an
  undocumented effect does not exist.

---

## 2026-08-15 · The look becomes machine-checked: house_style.json + 3 new gates

### The failure this fixes

A rebuild of an event 花絮 shipped **ASS-drawn square pills and 62pt captions with
a 6px black outline and fades on every line** — instead of the house PIL capsule
and 84pt drop-shadow hard cut. **All five gates were green.** The gates measured
where text sat, never what it looked like, and `gate_pill` returned PASS with
`pills: none` when the artifact was simply absent.

Prose could not have prevented it: the style existed only in the previous
project's `build/` directory, and `references/event-vlog-template.md` described
positions, not typography.

### #1 — `house_style.json` is now the single source of truth

Font, the three caption styles (size / outline / shadow / alignment), pill method
and geometry, cover geometry, hook and end-card requirements, sync thresholds and
bilingual mode. `modules/cover.py` reads `title_max_w_ratio` from it too, so the
cap is not defined in two places that can drift.

`gates.py --preflight` prints it as a build checklist **before** the edit; the
gates read the same file **after**. A project may override any key via
`WORK_DIR/house_style.local.json`, and every active override is printed in the
gate report — an exemption has to be written down, never assumed.

### #2 — three new blocking gates (5 → 8)

- **Typography** — font family, caption sizes, `outline != 0`, `\fad` where the
  house cut is hard, and half-translated bilingual captions.
- **Structure** — a Hook-styled caption inside the first second, an `endcard.png`,
  and the video's last frame actually matching it.
- **Sync** — every `Speech`-styled caption is a *verbatim claim* and is checked
  against `words.json` (timeline time). Three metrics: coverage, head-offset
  (opening on a word the cut removed), and lag back-projected from the **median**
  timestamp of the longest matching run. Plus a systematic-drift check that names
  a stale `words.json` instead of blaming 27 captions.

  Using the matched block's *start* time instead of its median produced a −1.94s
  false alarm on `Gemma`, which ASR splits across a 1.8s pause. Thresholds
  (coverage 0.55, lag 1.0s, median-drift 0.5s) were measured on a reviewed edit
  whose worst legitimate values were 0.67 and 0.56s.

### #3 — closed two "missing artifact = PASS" holes

`gate_pill` now fails when `pills.json` is absent, and distinguishes a PIL capsule
from an ASS box by the alpha at the corners of the pill's own bounding box. It
also decodes each baked pill clip's first frame to catch an alpha fade.

`gate_cover` reads a new `cover_meta.json` sidecar (written by `cover.build`) so
"the subtitle tracks the title width" is measured, not eyeballed.

### #4 — `legibility()` was measuring the background

It scanned for bright rows, so on a cover whose photo is a lit phone screen it
returned **the identical 0.0833 for a 190pt title and a 154pt one**. It now reads
the ink height `cover.draw()` measured from the font, and reports which source it
used. 154pt → 0.0792, 110pt → 0.0568: it tracks the title again.

### Cover geometry

`TITLE_MAX_W` 0.88 → **0.72** of frame width, and the subtitle is sized to match
the **title's rendered width** instead of a fixed cap (`SUB_RANGE` widened to
40–120 to make that reachable). Measured: title 788px, subtitle 787px.

### Tests

`tests/test_house_style.py` — 28 cases, each a real defect re-seeded. `doctor.py`
runs it alongside `test_gates.py` (11). Beyond fixtures, all four sync defects and
all four style defects were re-seeded into a **real work directory** and confirmed
to block, so the claim is "the pipeline rejects this", not "the fixture does".

Files: `house_style.json` (new), `gates.py`, `modules/cover.py`, `modules/title.py`,
`tests/test_house_style.py` (new), `doctor.py`, `SKILL.md`, `README.md`,
`ARCHITECTURE.md`, `references/event-vlog-template.md`.

---

## 2026-07-04 · Fix: A/V drift at scale + parallelize segment encode

### #1 — A/V drift from per-segment AAC concat (correctness)

`render_faded_cut` concatenated AAC-encoded segments with `-c copy`. Each AAC
segment carries encoder priming/padding, so the audio grew ~0.93 ms per
segment relative to video — **measured 23 ms over 25 segments, ~37 ms (>1
frame) over 40**: lip-sync drift by the end of a heavily-cut video.

Fix: segments now hold **PCM audio** in `.mkv` (`-c:a pcm_s16le`); the concat
step copies video losslessly and encodes the *continuous* audio to AAC exactly
once (`-c:v copy -c:a aac`). PCM concat is sample-exact → a single priming at
t=0, **0.0 ms drift over 40 segments** (verified).

### #2 — Parallel segment encode (performance)

Segments were re-encoded one ffmpeg process at a time. They're independent, so
`render_faded_cut` now encodes them across a `ThreadPoolExecutor`
(`min(len, cpu_count)` workers; ffmpeg releases the GIL). Order comes from the
job list (enumerate order), never completion order.

**Measured: 40-segment render 17.9 s → 6.1 s (2.9× on 8 cores).** Full test
suite 21 s → 9 s.

### Tests (TDD)

- `test_render_faded_cut_no_av_drift_many_segments` — 40 segments, drift
  < 10 ms (RED at ~37 ms on old AAC concat).
- `test_render_faded_cut_preserves_segment_order` — reversed keep-ranges
  (900 Hz then 300 Hz); zero-crossing-rate proves output follows keep order,
  guarding the parallel refactor against out-of-order concat.

### Files

- `modules/silence_cut.py` — PCM segments + single final AAC encode;
  `ThreadPoolExecutor` fan-out; `_encode` closure per segment.
- `tests/test_silence_cut.py` — +2 tests (17 in module).

---

## 2026-07-01 · Add: verify.py cut-boundary fade check

### Why

The fade fix (below) is only trustworthy if the shipped artifact is checked.
`verify.py` already audited global audio (clipping, RMS consistency), lip-sync
and subtitles — but nothing looked at the **cut boundaries** themselves.

### What

- `run_silence_cut` now writes `boundaries.json` = the interior join positions
  (output timeline) of the final cut stage, via the new pure helper
  `keep_ranges_to_boundaries(keep_ranges)`.
- New `check_cut_boundaries(work_dir)` in `verify.py`: for each listed
  boundary, extract the voice track (`trimmed.mp4`) RMS at 10 ms resolution and
  confirm a fade **dip** (`center < 0.4 × local median`). A hard cut leaves the
  amplitude near the surrounding level → flagged as "un-faded cut boundary
  (pop risk)". Silence-adjacent joins (`local median < 0.01`) are skipped —
  they can't pop. Registered as check #6 in `run_all_checks`.

### Tests (TDD)

- `tests/test_silence_cut.py::test_keep_ranges_to_boundaries` (pure).
- `tests/test_verify.py` (new, 3): faded boundary passes; constant-amplitude
  (hard-cut) boundary is flagged; missing `boundaries.json` passes.

### Files

- `modules/silence_cut.py` — `keep_ranges_to_boundaries` + `boundaries.json`.
- `verify.py` — `check_cut_boundaries` + registration.
- `tests/test_verify.py` — new.

---

## 2026-07-01 · Fix: silence-cut boundaries were never faded (audio pops)

### The bug

`run_silence_cut` produces cuts from **three** independent stages — clap
removal, auto-editor silence removal, and manual cuts — and each one spliced
audio with a hard cut (`aselect` / auto-editor's own render). The intended
smoothing lived in "Step 5":

```python
# Step 5: Micro-crossfade to smooth audio at cut boundaries
"-af", f"highpass=f=20,afade=t=in:d={crossfade_s}"
```

`afade=t=in` with no `st=` fades **only the first `crossfade_s` of the whole
file**. It never touched a single interior boundary. The variable was named
`SILENCE_CUT_CROSSFADE_MS` and the comment said "smooth audio at cut
boundaries", but the implementation was a no-op for every actual cut →
audible clicks/pops at each join. Intent ≠ implementation.

### The fix

One tested primitive, `render_faded_cut(input, keep_ranges, output, fade_ms)`:
extract each kept range, re-encode with `afade` in/out on **both** edges,
then losslessly `-c copy` concat. This is the only way to fade *interior*
splices (video-use Hard Rules #2 "per-segment extract → lossless concat" and
#3 "30ms fades at every boundary").

All three cut stages now route through it:

| Stage | Before | After |
|-------|--------|-------|
| Clap removal | `aselect` hard cut | `invert_ranges(clap_zones)` → `render_faded_cut` |
| Silence | auto-editor renders (hard cut) | auto-editor `--export v1` **detects only** → `chunks_to_keep_ranges` → `render_faded_cut` |
| Manual cuts | `aselect` hard cut | `invert_ranges(manual_cuts)` → `render_faded_cut` |

The broken Step 5 was deleted. auto-editor is now a **detector**, not a
renderer — we own the encode so we can fade.

### New pure helpers (unit-tested, no ffmpeg)

- `invert_ranges(cut_ranges, total)` — complement of cut zones within
  `[0, total]`; merges overlaps, drops zero-length keeps.
- `chunks_to_keep_ranges(chunks, fps)` — parse auto-editor v1
  `[start_frame, end_frame, speed]`; keep where `speed` is normal (the cut
  sentinel is `99999`).

### Tests (TDD, red→green each)

`tests/test_silence_cut.py` (+8 tests, 10 total pass):
- `render_faded_cut` fades an internal boundary (boundary RMS < 25% of
  mid-segment) and preserves kept duration.
- `invert_ranges` basic / start-touching / overlap-merge / no-cuts.
- `chunks_to_keep_ranges` v1 parsing.
- **End-to-end**: pure-tone clip + `manual_cuts=[(1,2)]` → boundary at output
  `t=1.0` is faded (RED against old wiring: `0.0845 ≈ 0.0857` = hard cut).

### Files

- `modules/silence_cut.py` — new helpers + rewired `run_silence_cut`,
  `remove_clap_segments`; deleted Step 5.
- `tests/test_silence_cut.py` — +8 tests.

### Not touched / known pre-existing (unrelated)

- `tests/test_subtitles.py` collection error (`generate_karaoke_line` absent)
  and `tests/test_broll.py::test_align_broll_multiword_keyword` failure both
  pre-date this change (verified by stashing this diff). Left as-is.
