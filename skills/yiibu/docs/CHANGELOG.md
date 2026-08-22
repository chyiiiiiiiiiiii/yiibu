# yiibu — Change Log

Reverse-chronological. Each entry: what changed, why, tests, files.
Full technical + techniques reference: [audio-boundary-fades.md](./audio-boundary-fades.md).

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
