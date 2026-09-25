# yiibu — the portable contract

**Read this if you are not Claude Code.** Codex, Antigravity, another model, a
plain script, a human: this file is the whole standard, and every rule in it is
a command you can run rather than advice you have to remember.

It sits at the repo root because that is where your tool looks for it. The
commands, however, run from the skill itself — start with:

```bash
cd skills/yiibu
```

The design rule behind that:

> **Quality lives in the executable checks, never in the agent driving them.**
> Anything that depends on an agent remembering, noticing, or being clever is
> not a standard — it is a hope. If a rule matters, it is a gate.

The proof is in the repo's own history: the same defects came back after being
documented in prose twice, and stopped only once code refused to proceed. So a
different model must be able to reach the same standard by running the same
commands — that is the bar this file exists to hold.

---

## 0. Check the machine once

```bash
python3 doctor.py
```

Needs `ffmpeg`, Pillow and numpy. The caption font is bundled. Hardware
encoding (`h264_videotoolbox`) is used when present and falls back to libx264
automatically, so a Linux clone works — slower, same output spec.

## 1. Read the standard BEFORE authoring anything

```bash
python3 gates.py --preflight
```

Prints the locked spec — font, caption sizes and minimum dwell, pill geometry,
cover rules, the hook and end-card requirements — straight out of
`house_style.json`, **which is the single source of truth**. Prose in SKILL.md
explains it; it does not define it. A project may override any key by writing
`WORK_DIR/house_style.local.json`, and every active override is printed, so an
exemption is visible instead of assumed.

## 2. Plan the length before cutting

```bash
python3 plan.py SOURCE_DIR --platform reels
```

Say the recommended number to the user before you cut. Length comes from
retention structure, not from how much footage exists.

It also writes `SOURCE_DIR_sheets/` — a contact sheet plus a **6-frame filmstrip
per clip**. Look at the filmstrips, not the contact sheet, before choosing any
shot: a botched take is botched in all six frames and invisible in one.

**Ask the user which moment was the best, and open on that.** This is the single
exception to "the user shoots, you select". It was tested rather than assumed on
2026-09-01: against a hook the user had already picked, face area matched it only
by luck (and would drag every future hook toward a face, which is wrong for food),
while motion and event-spike ranked the WRONG shot higher — pixel motion measures
the camera panning, not the content. Nothing computable here predicts a hook. The
person who was in the room knows which moment was good; ask them.

## 3. Record the user's decisions — never default them

`WORK_DIR/decisions.json` is REQUIRED; gates fail without it.

```jsonc
{
  "loudness": {"value": "original", "why": "..."},   // or -14LUFS, needs a why
  "captions": "on",                                  // or deferred, needs a why
  "end_card": {"value": "on"}                        // off needs a why
}
```

## 4. Transcribe EVERY clip, then PROOF-READ

```bash
python3 asr_scan.py SOURCE_DIR --work-dir WORK_DIR   # every clip, BLOCKING via gate_transcription
python3 proofread.py WORK_DIR/words.json --media CLIP.mp4
```

The first command is not optional and it is not just for the obvious talking
clip. On 2026-08-29 a folder was cut twice, both builds green, with only the
long selfie recording ever transcribed — two running clips carried the split
calls 「1K 4 分 28 秒」 and 「4K 4 分 43 秒」 and shipped as silent B-roll with
invented pills over them. `asr_scan.py` writes `asr_scan.json`; `gate_transcription`
fails if a clip in the cut is missing from it, if silence is declared with no
`no_speech_prob` and no `why`, or if speech that WAS found reaches no caption.

Reading its output needs one guard, which is why the artifact records the number
rather than the words: on silent outdoor clips Whisper returns YouTube end-plate
boilerplate (`中文字幕志愿者 …`, `感谢观看`) at an ordinary-looking `avg_logprob`.
**`no_speech_prob` is the discriminator** — ten silent clips measured 0.59-0.84
there while the two real ones produced word timings that held across three decode
temperatures. And re-run any line you intend to caption **on its own**: a
full-clip pass read 「1KM」 with `M` at p0.06; three isolated re-runs said 「1K」.

Exit 1 means do not caption from this transcript. Two failures it catches that
nothing downstream can:

- **Prompt echo** — on noisy audio Whisper returns your `initial_prompt` as the
  transcript, at ordinary-looking probabilities. It would ship as a quote the
  person never said. **Do not pass an `initial_prompt`.**
- **Decoder loop** — a phrase repeating forever on near-silent audio.

Then: a caption that QUOTES speech must match the audio under it word for word.
Anything you cannot confirm goes in an authored style (`Note`), never a verbatim
one (`Speech`). Tightening a quote to read better is fabrication.

## 5. Build with the proven primitives

```bash
python3 build_lint.py YOUR_BUILD.py     # before running it, and after editing it
```

Compose `modules/buildkit.py` (`prep_segment`, `concat`, `overlay_pills`,
`burn_subtitles`, `duck_mix`, `final_encode`, …). Each function encodes a trap
that has cost real build time. Writing a raw ffmpeg graph for something
buildkit covers is the known failure mode. Importing buildkit self-lints the
calling script, so an antipattern refuses to start rather than stalling later.

**Let the gate claim the final name.** Build into the work dir, declare the
set, and a passing gate run is what puts it at the project's first level:

```python
bk.stage_delivery(WORK, {"vp_music.mp4":   "devjam-recap.mp4",
                         "vp_nomusic.mp4": "devjam-recap-nomusic.mp4",
                         "cover.jpg":      "cover.jpg"})
```

`gates.py` publishes that set **only on exit 0** — 1 and 2 both leave every file
where it is. This is the one rule here that does not depend on you remembering
anything: forgetting to gate produces no video rather than an unchecked one.
Declare nothing and the old behaviour is unchanged.

Two that matter for hand-off:

- `final_encode(..., delivery=True)` is the default and uses a delivery
  bitrate. At the intermediate bitrate a 90-second reel came out **211 MiB**.
- `duck_mix(..., speech_spans=[(start, end), …])` when speakers sit at
  different distances from the mic. The automatic mode derives its threshold
  from the material, but an explicit list is deterministic and inspectable.

## 6. Ship BOTH versions, and gate every render

```bash
python3 verify.py WORK_DIR --output FINAL.mp4    # advisory
python3 gates.py  FINAL.mp4 --work-dir WORK_DIR  # BLOCKING
```

A music version and a `-nomusic` version always ship, plus `cover.jpg`, at the
project's first level.

| exit | meaning | what to say |
|---|---|---|
| `0` | shippable — and a declared delivery is now published | it passes the gates |
| `1` | something is broken | what failed; do not hand over |
| `2` | nothing broken, gates **deferred** by a recorded decision | it is **not finished**, and which parts are outstanding |

**The rule that outranks every threshold:**

> Do not reason about whether a measurement is acceptable.
> A number outside the threshold is a failure **even when you can explain it**.

A silent ending shipped twice; both times the level was measured, seen, and
talked away. Explaining a number is not checking it.

Every run appends to `WORK_DIR/build_log.jsonl` and rewrites `BUILD_LOG.md`,
including how many attempts it took and which gates rejected which one. That log
is written by `gates.py` and by nothing else, which makes the one failure prose
cannot catch — *the gates were never run at all* — visible after the fact, in one
command:

```bash
ls -l WORK_DIR/build_log.jsonl    # missing, or older than the render = not checked
```

`postprod.py` now runs both checkers itself as step 7 and **exits with the gate's
own code**, so the automatic step is the one that can refuse. Template mode has
no such driver: there, §6 is yours to type.

## 7. Look at what the gates cannot see

```bash
python3 coverage.py WORK_DIR      # also printed under every gates.py run
```

Gates check for **defects**. They are structurally blind to:

- **truth** — a caption can be perfectly placed, perfectly timed, and say
  something nobody said and no slide shows;
- **omission** — a build passed every gate while half its subjects had
  two shots and the rest four.

> **All gates green does not mean the video is good.** It means you did not trip
> a known landmine. Say "it passes the gates", never "it is finished", until
> someone has watched it.

---

## What is Claude-Code-specific (and therefore optional)

`agents/*.md` (at the plugin root, one level above this skill) are sub-agent
definitions for Claude Code. They are
**accelerators, not dependencies** — every standard above is reachable with the
commands in this file alone:

| agent | the portable equivalent |
|---|---|
| `transcript-proofer` | `python3 proofread.py` (§4) |
| `footage-scout` | `python3 plan.py` + `ffprobe`; check `side_data_list` rotation, because ffprobe reports CODED dimensions and a rotated clip reads landscape while displaying portrait |
| `slide-reader` | extract stills at FULL resolution and read them yourself; never judge on-screen text off a downscaled contact sheet |
| `edit-critic` | **`python3 review.py WORK_DIR --output FINAL.mp4`** — contact sheet of frame 1, every caption moment and the last frame, plus the shape of the cut; then `coverage.py`. It grades nothing: it makes not looking difficult |

`hooks/hooks.json` registers one more Claude-Code-only thing: a `Stop` hook
(`hooks/gate_guard.py`) that refuses to end a turn which produced a video no
gate run recorded — or one the gates blocked, or one re-rendered after the last
run. It reads `build_log.jsonl` and nothing else, so it makes no judgement of
its own; it just makes forgetting §6 impossible **in this driver**. It stays
silent in a directory with no yiibu artifacts in it, and it cannot see a video
built by hand with no artifacts at all. Every other driver reaches the same
standard the same way it always did: by running the command.

What the agents genuinely add is judgement a script cannot have: which domain
noun is wrong, what a slide actually says, whether a claim is supported. If your
driver has no sub-agent mechanism, do that work yourself — do not skip it.

**Do not put the edit itself behind an agent, in any driver.** Choosing which
shots earn a place, in what order, where the hook lands and how long it runs
requires holding the whole folder in mind at once. That IS the edit.
