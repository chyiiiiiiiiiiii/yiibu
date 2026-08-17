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
| `YIIBU_OUTPUT_DIR` | `~/Desktop` | fallback output dir (deliverables normally go to the project root — see SKILL.md) |
| `YIIBU_WORK_DIR_PREFIX` | `/tmp/video-postprod` | where intermediate work dirs are created |
| `YIIBU_FONT_NAME` | `演示斜黑体` | caption font, matched by fontconfig NAME; missing → degrades to PingFang/Songti/Noto |
| `YIIBU_BGM_TRACK` | first track in `bgm-library/chill/` | default music bed |
| `YIIBU_CTA_IMAGE` | `assets/substack.png` (gitignored) | closing CTA overlay; the step skips cleanly when absent |
| `YIIBU_GEMINI_KEY` | see order → | Gemini API key for the optional LLM steps (translation, B-roll planning, Veo). Resolution: this var → an `export GEMINI_API_KEY=...` or `GOOGLE_API_KEY=...` line in `~/.zshrc` → the process env. No key → those steps skip, never error |
| `YIIBU_VEO_MODEL` | `veo-3.1-fast-generate-preview` | video model for generated B-roll; a bad name falls through the chain, never errors |
| `YIIBU_GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | primary image model for the B-roll image fallback |
| `YIIBU_OPENAI_IMAGE_MODEL` | `gpt-image-2` | second image fallback via the OpenAI images API |
| `YIIBU_OPENAI_KEY` | see order → | OpenAI key for the image fallback. Resolution: this var → an `export OPENAI_API_KEY=...` line in `~/.zshrc` → the process env; none → that rung skips |

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

## 4. What to leave alone (until you disagree on purpose)

- **`gates.py` thresholds** — dead-air limit, silent-ending floor, clipping
  ceiling, caption safe-area. Every threshold encodes a defect that actually
  shipped. Loosening one because a measurement "is explainable" is the exact
  failure mode the gates exist to stop.
- **`tests/`** — several tests reconstruct shipped defects and assert the gates
  reject them. If you change a gate, change its test with it, deliberately.
