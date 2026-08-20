# Conference / event 花絮 — locked template

> **Build with `modules/buildkit.py`** (it self-lints the build script on
> import), record the user's calls in `WORK_DIR/decisions.json`, and gate with
> `gates.py` — all three are BLOCKING as of 2026-08-18. This template's recipe
> is unchanged; only the construction tooling moved into code.


Derived from the 2026-08-13 Google I/O Connect 上海 Day 1 edit (2:02, 9:16,
39 segments). It took **eleven versions** to reach the standard below. Everything
here is the answer to a defect that shipped, so build to it first and only tune
what the user asks for.

**When this applies:** a folder of phone clips from one event — booths, sessions,
walking around. Several different people talk (booth staff, session speakers,
the user), the rooms are noisy, and the audience did not attend, so the video has
to *explain* as well as show.

| | talking-head | food 花絮 | **this** |
|---|---|---|---|
| payload | what the speaker says | the food/process | the tech, explained |
| captions | transcribed speech | authored narration | **both, separated by layer** |
| audio | speech is content | ambience is texture | **speech is content, ambience is noise** |

## 0. Plan first, and cut without music

Run `plan.py` on the source folder and tell the user the recommended length
before cutting. For this material it says 1:47; the accepted edit came in at
2:02, so treat it as a floor to argue up from, not a target to pad to.

Cut and review the **no-music** version first. Music hides pacing problems: a
shot that is 2s too long reads as fine over a chorus and as dead air without it.
Ship both versions at the end.

## 1. Intake and fact discipline

Contact sheet first (see food-vlog-template #1). Then, before writing any caption:

- **Read the booth board at full resolution.** Every claim in the finished video
  came off a signboard, a slide, or a transcript. "三個場館" and "重量比想像中輕"
  were both invented in v1 and had to be pulled — nobody in the footage says them.
- **Cross-check ASR against on-screen text.** Conference screens carry the
  speaker's own subtitles. They corrected 任何細節→**全部細節** and 減少了→**節省了**
  after Whisper scored the wrong word at 1.00 confidence. When your caption and
  the screen behind it disagree, the viewer sees a typo.
- **Product names must be read, not inferred.** The Web AI booth was captioned
  from the exhibitor's own copy (`LiteRT-LM.js`), not from a guess — a blurry
  wordmark reading `Lite…js` could equally have been `LiteRT.js`, a different
  product. If you cannot read it, ask; do not pick the plausible one.

## 2. Caption layers

Two layers, never mixed:

| layer | position | carries |
|---|---|---|
| **pill** | 18% height, rounded, `modules/title.py` | the NAME of the thing |
| **caption** | **70% baseline**, centred | the explanation, or verbatim speech |

### 2.1 The locked look — copy this, do not re-derive it

The geometry, rendered from the spec itself (`python3 docs/make_diagrams.py`):

<p align="center"><img src="../docs/diagrams/caption-geometry.png" alt="pill 18% / caption 70% geometry" width="320"></p>

Everything above this line is *position*. This is *style*, and it is the part
that gets reinvented: a rebuild from the prose above produced ASS-boxed pills and
62pt outlined captions, and **every gate still passed**, because `gates.py` does
not check typography. Paste these:

```
Style: Speech,演示斜黑体,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1
Style: Note,  演示斜黑体,76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1
Style: Hook,  演示斜黑体,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,7,5,60,60,0,1
```

- `Speech` = verbatim, `Note` = authored, `Hook` = the opening line. Outline **0**,
  Shadow **5–7** — a drop shadow, *never* a black outline.
- Every line: `{\an5\pos(540,1344)}`, Layer 4 (Hook 5). Keywords gold
  `&H0000D7FF` in ONE regex pass.
- **Pills are NOT drawn in ASS.** ASS opaque-box comes out a coarse rectangle.
  Use `title.render_title_png(text, png, pct=0.23, font_size=56)` — PIL
  antialiased capsule, width hugging the text — shrinking 2pt at a time while the
  rendered capsule is wider than 880px. Bake each to a **finite** qtrle alpha
  clip before overlaying: `-loop 1 -i pill.png` straight into `overlay` never
  EOFs and hangs ffmpeg forever (delivery-traps #6).
- **Hard cut everywhere. No `\fad` on captions, no alpha fade on pills.** A label
  that dissolves reads as a rendering glitch on a feed cut. (`SUBTITLE_FADE_IN_MS`
  is 0 for the same reason.)
- Composite captions + pills + cover in **one** `filter_complex` so the picture
  encodes once and AAC runs once (delivery-traps #3).

Reference implementation: `references/examples/event-vlog/` (the accepted I/O Connect Day-1 build). On the author's machine the live copy is the most recent event build directory.

- 70%, not the bottom edge: the Reels/Shorts UI eats the bottom.
- Every caption style needs an explicit `\pos`. A style with no `\pos` silently
  falls back to its alignment default — in v2 that put *every* caption at 50%
  for a whole version before anyone noticed. `gates.py` now fails on this.
- Verbatim speech only where ASR is actually confident. In this edit that was
  the keynote (0.84–1.00); booth audio ran 0.2–0.7 and flipped between takes, so
  those segments got authored info lines instead of invented quotes.
- Highlight keywords in **one regex pass**. A per-keyword replace loop re-tags
  text it already tagged (`LiteRT` inside `LiteRT-LM.js`) and libass renders the
  nested override wrong.
- Check every line's rendered width against the safe area **after every text
  edit**. Editing a caption and not re-running the width check shipped an
  overflowing line in v4.

## 3. B-roll for gear you cannot film

When the user tries hardware, the interesting half is invisible. Official footage
fixes that, but a full-frame cutaway throws away the user's own reaction.

**Use a split frame instead:** official B-roll in a 16:9 panel on top, the user's
own footage below, their audio running continuously underneath both. A 96px band
above the panel carries the label, the source credit sits inside the panel's
lower edge. This turned a 22s static booth shot into the strongest section.

Credit the source on screen. Also: check the clip still downloads — one of the
two official videos went DRM-protected between v2 and v3 and 403'd on the latest
yt-dlp, so the shot had to be re-sourced.

## 4. Audio — original only where someone talks

The default from the other templates ("leave the ambience alone") is **wrong
here**. Expo ambience under a music bed is just noise.

- **Gate the original per segment**: full level where someone we want to hear is
  talking, muted elsewhere. Keep the opening shot on real venue sound.
- **Do not try to do this with a sidechain compressor.** The band-limited key
  sits at 0.044 RMS even in the quietest fifth of this material, so the
  compressor either pins on for the whole runtime or never fires. Measured, not
  assumed.
- **Silero VAD does not separate it either** — it scored 82% of this video as
  speech because it hears crowd babble. The segment list is an editorial
  decision; write it down and let the reviewer correct it.
- Build the envelopes in numpy with raised-cosine ramps (~300ms) and apply with
  `amultiply`. Deterministic, and every level is inspectable.

**Music:**
- Enter on the **chorus**, timed to the first cut after the hook.
- Find the chorus by **transcribing the lyrics**. A modern master is too
  compressed for an energy profile to show structure — the RMS was flat within
  3 dB across an entire song.
- **Derive, do not type, anything that depends on another value.** Three
  constants in this edit were really dependencies in disguise, and each one
  shipped a defect when the thing it depended on changed:

  | looked like a constant | actually depends on | what it shipped |
  |---|---|---|
  | music tail fade | the closing shot's duration | closing card in silence |
  | track's audible end | the track file | music ran out 7s early |
  | caption width check | the caption text | a line 216px past the safe area |

  Measure the track's audible end instead of passing it in; derive the fade from
  the closing segment; run the width check *inside* caption generation so an
  overflowing `.ass` cannot exist on disk. Gates catch these at the end — an
  edge means they never happen.
- Two decoder inputs, not `asplit`, when looping: `asplit` cannot feed two
  different time ranges and yields a **zero-length stream without erroring**.

## 5. Cover — see `modules/cover.py`

Mandatory, and it is frame 1. Max two lines, auto-sized, product names in the
subtitle (you wear glasses, not a platform). Burn it as an **overlay on frame 1**,
never as a prepended segment — prepending shifts every caption by a frame.

## 6. Before shipping — both gates, no exceptions

```bash
python3 verify.py WORK_DIR --output FINAL.mp4
python3 gates.py FINAL.mp4 --work-dir WORK_DIR
```

`gates.py` exits non-zero and blocks. **Do not reason about whether a number is
acceptable.** The silent ending shipped twice; both times the level was measured,
seen, and explained away ("that's the song's own outro", "that's the tail fade").
A number outside the threshold is a failure even when you can explain it.
