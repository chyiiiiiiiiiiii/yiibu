# Setup — from clone to first gated video

The design goal: **a fresh clone works with ffmpeg and two Python packages.**
Everything else unlocks one extra feature and is skipped cleanly when absent.
`python3 doctor.py` is the authority on what this machine has — run it first,
run it after any install, and believe it over this file.

```bash
python3 doctor.py
```

## Tier 0 — required (every render, every gate)

| what | why | install |
|---|---|---|
| Python 3.9+ | everything | pre-installed on macOS; `apt install python3` elsewhere |
| ffmpeg + ffprobe | every cut, mix, encode and probe | `brew install ffmpeg` / `apt install ffmpeg` |
| Pillow | pills, covers, title cards | `pip3 install pillow` |
| numpy | audio measurement, ducking, gates | `pip3 install numpy` |

The caption font (演示斜黑体) is **bundled** in `assets/fonts/` and is the
primary house font — nothing to install. `modules/title.py _find_font()`
locates it; `YIIBU_FONT_NAME` overrides.

**Platform note.** The talking-head pipeline (`postprod.py`) is portable:
`modules/compose.py` picks `h264_videotoolbox` on macOS and falls back to
software encoding elsewhere. The template-mode helper `modules/buildkit.py`
currently hardcodes `h264_videotoolbox`, so agent-assembled template builds are
**macOS-only today** — on Linux, write the final encode step yourself with
`libx264` (and know that `build_lint.py` flags `libx264` because on macOS it is
the classic 20-minute-encode mistake, not because it is wrong on Linux).

## Tier 1 — speech captions (faster-whisper, in a venv)

ASR runs through the skill's own venv so its heavy dependencies never touch
your system Python. The Gemini/OpenAI SDK calls run through the same venv
(`.venv/bin/python3` subprocess), so this one venv serves both:

```bash
cd <skill root>
python3 -m venv .venv
.venv/bin/pip install faster-whisper opencc google-genai requests auto-editor
```

- first transcription downloads the Whisper model (~3 GB for `large-v3`);
  drop to `medium` in `config.py` if RAM is tight
- no venv → `postprod.py` still runs; speech-caption features are skipped

## Tier 2 — API keys (each key unlocks one feature, none required)

Key files are **one line, the bare key, no quotes, no `KEY=` prefix**, saved at
the **skill root** (wherever you cloned it — paths are resolved relative to the
code, not to a fixed install location):

```bash
echo "YOUR_PEXELS_KEY"  > .env.pexels     # stock B-roll (video+photo) — free, pexels.com/api
echo "YOUR_PIXABAY_KEY" > .env.pixabay    # stock B-roll fallback — free, pixabay.com/api/docs
```

Environment variables `PEXELS_API_KEY` / `PIXABAY_API_KEY` override the files.
Both are gitignored (`.env.*`) — never commit a key.

**Gemini** (Veo B-roll generation, image fallback, LLM caption segmentation,
bilingual line, emphasis captions). Resolution order, from
`modules/llm.py resolve_gemini_key()`:

1. `YIIBU_GEMINI_KEY` env var
2. an `export GEMINI_API_KEY=...` or `export GOOGLE_API_KEY=...` line in `~/.zshrc`
3. `GEMINI_API_KEY` / `GOOGLE_API_KEY` in the process environment

**OpenAI** (last-rung image generation): `YIIBU_OPENAI_KEY`, then
`export OPENAI_API_KEY=...` in `~/.zshrc`, then the process environment.

**Gemini CLI** (`npm install -g @google/gemini-cli`, browser auth on first run).
Five call sites, all of which fall back cleanly without it:

| module | function | what it does |
|---|---|---|
| `modules/broll.py` | `_resolve_product_url` | web search for a product's official URL |
| `modules/broll.py` | `_validate_screenshot_content` | vision check that a screenshot matches the title |
| `modules/broll.py` | `review_generated_asset` | vision review of a generated image |
| `modules/broll.py` | `auto_generate_broll_items` | plan B-roll items from the transcript |
| `modules/bgm.py` | `analyze_mood` | pick a music mood from the transcript |

Note that `modules/llm.py` calls the google-genai SDK directly for caption
segmentation and translation, and its docstring describes the CLI as replaced.
That migration covered the text-segmentation path only; the five above still
shell out. Two of them pass `--file` for vision, which `llm.gemini_generate` has
no equivalent for yet. If you would rather not install the CLI at all, every one
of these degrades to its documented fallback.

## Tier 3 — website-screenshot B-roll

```bash
pip3 install playwright && playwright install chromium
```

Used when the script mentions a product/URL; without it, the chain falls
through to stock footage.

## Verify

```bash
python3 doctor.py                 # environment + runs both gate test suites
python3 gates.py --preflight      # prints the house style the gates will enforce
python3 -m pytest -q              # full test suite (script suites bridged in)
```

## Agent definitions (subagents)

`agents/` holds the four subagent definitions the SKILL.md workflow calls
for: `footage-scout`, `transcript-proofer` (required before captions),
`slide-reader`, `edit-critic`. On Claude Code, install them with:

```bash
cp agents/*.md ~/.claude/agents/
```

On other harnesses the frontmatter won't be read, but the bodies are plain
instructions — reuse each prompt in whatever subagent mechanism you have.

## The two fallback chains (nothing here can stall a build)

B-roll, per item type — each rung needs one thing and falls through cleanly:

```
screenshot/product:  URL resolve (gemini CLI) → Playwright screenshot
                     → Veo video  ← PAID, needs your own Gemini key
                     → stock video/photo → Gemini image → OpenAI image
                     → skip (stay on selfie)
stock:               Veo video  ← PAID, first on purpose
                     → Pexels video → Pixabay video
                     → Pexels photo → Pixabay photo
                     → Gemini image → OpenAI image → skip
tweet URL:           vxtwitter media (video → image) → then the tail above
```

**The paid rung is first, and that is deliberate**: generated video is matched to
what the segment is actually about, where stock is at best thematically close.
Everything below Veo is free. With no Gemini key resolvable it skips itself, says
so once per run, and the ladder continues at the free rungs — a run with no paid
key is a normal run, not a degraded one. `YIIBU_VEO_ENABLED=0` skips the paid
rung while keeping the rest.

Music — `resolve_music.py` always terminates and reports which rung answered:

```
explicit path → PROJECT_DIR/music/ drop-in → filename match in bgm-library/
→ mood-matched stand-in (deliverable is renamed -standin-<mood>, never
  labelled as the requested track)
```

In the talking-head pipeline there is one more rung below the ladder: if no
library track matches the segment's mood, `modules/bgm.py` generates an
ambient synth pad with FFmpeg — the music step never returns empty-handed.

`bgm-library/` ships empty in the public repo (music licensing is per-user —
see `NOTICE.md` and `bgm-library/README.md` for how to fill it). Any audio
file you drop into `bgm-library/<mood>/` or `PROJECT_DIR/music/` is picked up.

## Layout — what each top-level file is

```
SKILL.md             the agent contract — intake, defaults, gates, templates
house_style.json     THE spec; gates.py --preflight prints it, the gates read it
config.py            every tunable, env-overridable (YIIBU_* variables)
doctor.py            environment check + runs both gate test suites
plan.py              length + selection maths, before cutting
postprod.py          talking-head pipeline entry point
resolve_music.py     the music ladder (never stalls)
build_lint.py        static lint for hand-written build scripts (run BEFORE executing)
agents/              subagent definitions — install per the section above
verify.py            advisory quality report
gates.py             14 blocking shipping gates (exit 0/1/2)
modules/             silence_cut, transcribe, subtitles, broll, bgm, compose,
                     positioning, cover, title, cutout, buildkit, llm,
                     transcript_analyzer, types
tests/               regression suites — every gate seeded with its shipped defect
references/          locked templates + worked example build scripts
docs/                CONFIGURATION, WALKTHROUGH, CHANGELOG, deep dives
```

Work products land in `/tmp/video-postprod/<timestamp>/` (`YIIBU_WORK_DIR_PREFIX`
overrides); deliverables always land at the project root (see SKILL.md).

## Key configuration (config.py — all env-overridable)

| parameter | default | note |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | smaller = faster, less accurate |
| `WHISPER_LANGUAGE` | `zh` | |
| `OUTPUT_WIDTH×HEIGHT` | `1080×1920` | 9:16 |
| `OUTPUT_FPS` | `30` | |
| `BROLL_REVIEW_MODEL` | `gemini-2.5-flash` | vision review of generated assets |
| `BROLL_VEO_MODEL` | `veo-3.1-fast-generate-preview` | `YIIBU_VEO_MODEL` overrides |
| `BROLL_GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | `YIIBU_GEMINI_IMAGE_MODEL` |
| `BROLL_OPENAI_IMAGE_MODEL` | `gpt-image-2` | `YIIBU_OPENAI_IMAGE_MODEL` |
| `BGM_VOLUME` | `0.3` | bed gain before ducking |
| `FONT_NAME` | `演示斜黑体` | bundled; `YIIBU_FONT_NAME` overrides |

Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `doctor.py` says a REQUIRED row is ❌ | missing tool/package | run the install command it prints |
| `ModuleNotFoundError: faster_whisper` | venv not created | Tier 1 above |
| stock B-roll always "API key not found" | no `.env.pexels` at the skill root | Tier 2 above (file sits next to SKILL.md, wherever cloned) |
| captions have no English line | no Gemini key resolved | Tier 2; the step skips cleanly by design |
| Whisper OOM on `large-v3` | RAM | set `WHISPER_MODEL = "medium"` |
| wrong caption font in output | system font override | the bundled 演示斜黑体 is the house font; check `YIIBU_FONT_NAME` |
| a final encode takes 20+ min | wrong encoder / graph antipattern | run `build_lint.py` on the build script; see SKILL.md "15-minute budget" |
| gates exit 2 | a decision deferred work | not an error — the video is NOT finished; the report names what is outstanding |
