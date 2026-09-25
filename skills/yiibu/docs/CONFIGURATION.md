# Configuration

What you can change, where, and what you should think twice about. Layers, from
most to least frequently touched:

```
per-project   WORK_DIR/house_style.local.json   style overrides for ONE video
per-machine   YIIBU_* environment variables         paths, keys, personal assets
per-fork      house_style.json / config.py       your house taste, forked once
```

## 1. Per-project: `house_style.local.json`

Any key in `house_style.json` can be overridden for a single project by writing
`WORK_DIR/house_style.local.json`. `gates.py` prints every active override, so a
reviewer sees what was exempted instead of guessing.

```json
{"bilingual": {"required": true}}
```

Typical uses: turn bilingual captions on for one video, relax a structure rule
for an experiment. The override file travels with the build directory.

## 2. Per-machine: `YIIBU_*` environment variables

All optional; every default works when they are unset.

| variable | default | what it does |
|---|---|---|
| `YIIBU_SCOUT_JSON` | unset | Path for `modules/audio_scout.py` to dump its per-segment measurements as JSON (dBFS, voiced fraction, sizzle, event rate). Evidence for the audio policy; the build reads it, a person makes the call. |
| `YIIBU_OUTPUT_DIR` | `~/Desktop` | fallback output dir (deliverables normally go to the project root — see SKILL.md) |
| `YIIBU_WORK_DIR_PREFIX` | `/tmp/yiibu` | where intermediate work dirs are created |
| `YIIBU_FONT_NAME` | `演示斜黑体` | caption font, matched by fontconfig NAME; missing → degrades to PingFang/Songti/Noto |
| `YIIBU_FONT_FILE` | unset | a font FILE to use instead, bypassing name matching entirely — the first rung of the ladder in `modules/title.py`. Takes precedence over `YIIBU_FONT_NAME`; ignored if the path does not exist |
| `YIIBU_BGM_TRACK` | first track in `bgm-library/chill/` | default music bed |
| `YIIBU_CTA_IMAGE` | `assets/substack.png` (gitignored) | closing CTA overlay; the step skips cleanly when absent |
| `YIIBU_GEMINI_KEY` | see order → | Gemini API key for the optional LLM steps (translation, B-roll planning, Veo). Resolution: this var → an `export GEMINI_API_KEY=...` or `GOOGLE_API_KEY=...` line in `~/.zshrc` → the process env. No key → those steps skip, never error |
| `YIIBU_VEO_MODEL` | `veo-3.1-fast-generate-preview` | video model for generated B-roll; a bad name falls through the chain, never errors |
| `YIIBU_GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | primary image model for the B-roll image fallback |
| `YIIBU_OPENAI_IMAGE_MODEL` | `gpt-image-2` | second image fallback via the OpenAI images API |
| `YIIBU_OPENAI_KEY` | see order → | OpenAI key for the image fallback. Resolution: this var → an `export OPENAI_API_KEY=...` line in `~/.zshrc` → the process env; none → that rung skips |
| `YIIBU_VEO_ENABLED` | `1` | set to `0` to skip the PAID Veo rung and start the B-roll ladder at the free stock sources. With no Gemini key the rung skips itself anyway |
| `YIIBU_DELIVERY_BITRATE` | `20M` | delivery encode bitrate. House rule (2026-08-21): keep the picture the user shot — file size is THEIR call and is not traded away uninvited. Set this lower when a smaller file genuinely matters more than the image |
| `YIIBU_SKILL_DIR` | the skill's own directory | where the skill's assets and `.venv` live; set it when running the code from somewhere else |
| `YIIBU_SKIP_LINT` | unset | `1` disables `build_lint`'s self-check when `buildkit` is imported. An escape hatch — write down why in the build script if you use it |
| `YIIBU_TIMING_LOG` | unset | append subprocess timing JSONL from `modules.buildkit` to this path; records command kind, elapsed seconds and outcome, without command arguments. Leave unset to disable |
| `YIIBU_CLEARANCE_MODEL` | `gemini-2.5-flash` | vision model `clearance.py` uses to read a frame; `--no-deep` skips the call entirely |

## 3. Your house taste: fork `house_style.json`

`house_style.json` is the machine-readable style contract — font, caption sizes,
pill geometry, hook/end-card requirements, fade policy. **It is what `gates.py`
actually enforces**; the markdown files only explain it.

To make this skill produce *your* look instead of ours: edit `house_style.json`
once, in your fork, and keep it under version control. The gates then hold every
future edit to your values with the same rigor. The shipped values are not
arbitrary defaults — each one is the survivor of a real shipped defect (see
`ARCHITECTURE.md`), so read the comment trail before loosening one.

Also forkable:

- **`config.py`** — audio levels (`VOICE_VOLUME`, `BGM_VOLUME`), subtitle sizes
  and colours, B-roll layout (`BROLL_LAYOUT`: `fullscreen` / `split` / `mixed`),
  bilingual default (`SUBTITLE_BILINGUAL`), emphasis-caption knobs.
- **`keyword_bank.json`** — terms that get gold-highlighted in captions
  (`brand` / `tech` / `concept` tiers). Grows over time; add your product names.
- **`term_corrections.json`** — known ASR mishearings and URL fixes; also grows
  with use.
- **`bgm-library/<mood>/`** — drop tracks into mood folders (`chill`,
  `energetic`, `dramatic`, `inspiring`); the bgm step picks by transcript mood.

## 5. Command-line surface

Every entry point, so a flag never has to be discovered by reading `argparse`.

| script | what it is for | flags |
|---|---|---|
| `plan.py FOOTAGE_DIR` | recommend a length before cutting | `--platform`, `--payloads`, `--json` |
| `gates.py FINAL.mp4` | the 20 blocking gates | `--work-dir`, `--preflight`, `--json` |
| `verify.py WORK_DIR` | advisory report, not a gate | `--output`, `--fix`, `--json` |
| `proofread.py WORDS.json` | check an ASR transcript before captions | `--media`, `--model`, `--prompt`, `--max-spans`, `--json` |
| `asr_scan.py SOURCE_DIR` | ask EVERY clip whether anybody is talking in it; writes `asr_scan.json` for `gate_transcription` | `--work-dir`, `--model`, `--skip`, `--timeout`, `--json` |
| `build_lint.py SCRIPT.py` | reject slow/hang antipatterns in a build script | — |
| `clearance.py FOOTAGE_DIR` | who may publish this? — filename triage + a model reading one frame per clip | `--work-dir`, `--json`, `--no-deep` |
| `doctor.py` | environment check | — |
| `resolve_music.py "TEXT" PROJECT_DIR` | the music ladder | — |
| `postprod.py INPUT_VIDEO` | the voiceover pipeline | see the option list in SKILL.md |
| `references/speech_gaps.py MEDIA` | find speech gaps for silence trimming | `--min-gap`, `--pad` |
| `references/duck_check.py MUSIC NOMUSIC WORK_DIR` | per-segment duck report — which shots the bed stepped back for | `--duck-threshold` |

`--json` means machine-readable output on stdout, for wiring a step into another
script. `verify.py --fix` rewrites subtitle timings to match the word timestamps;
it edits your work dir, so read the report first.

### Resuming a folder transcription

Re-run the same `asr_scan.py` command after an interruption. Completed clips are
cached in `_asr_scan_cache/`; source content, model or scan-setting changes
invalidate the affected cache entries. A failed run does not publish a current
`asr_scan.json`, so partial progress cannot masquerade as a complete scan.
`--timeout` sets the wait limit in seconds (default 900); increase it for a model
load or clip that legitimately needs longer. This does not skip failed clips or
declare them silent.

### Measuring build commands

Set `YIIBU_TIMING_LOG` to a file in an existing work directory before running a
build script. Each `modules.buildkit` command appends one JSONL record with
`command_kind`, `elapsed_seconds`, `outcome` and `returncode`. It excludes command
arguments and does not alter the render or gate thresholds. This measures only
commands run through buildkit, not total agent time or every postprod stage.
Compare identical inputs and settings before drawing a speed conclusion.

### Resuming the spoken-video pipeline

The silence-cut step writes a `timeline.json` mapping retained intervals back to
the original source, including clap, silence and manual cuts. After transcription,
`transcription_domain.json` binds the words to the current trimmed media and that
timeline. Editing the words and resuming the subtitle step revalidates the media
and word times before rebinding the corrected transcript, and refuses any word
that differs from `words.asr.json` (the ASR as heard, written at transcription)
unless `corrections.json` declares it with evidence. Changed media or cuts
require a new transcription; missing evidence is not treated as proven silence.

`auto_script.json` and `visual_moments.json` use companion `.meta.json` files to
check their inputs and payloads. A legacy cache without metadata is regenerated.
Keep the work directory together when resuming; copying just the transcript does
not provide evidence for a different cut. The gate recognizes postprod's
`Default` speech captions only with valid transcription evidence; authored
captions in other workflows retain their existing meaning.

## 4. What to leave alone (until you disagree on purpose)

- **`gates.py` thresholds** — dead-air limit, silent-ending floor, clipping
  ceiling, caption safe-area. Every threshold encodes a defect that actually
  shipped. Loosening one because a measurement "is explainable" is the exact
  failure mode the gates exist to stop.
- **`tests/`** — several tests reconstruct shipped defects and assert the gates
  reject them. If you change a gate, change its test with it, deliberately.
