# Walkthrough — one real edit, start to gates

This follows an actual project: `dev-jam-2026`, a student hackathon demo day
(43 phone clips, 996s of footage → a 90.15s bilingual short over 29 segments).
Six teams pitch, judges question them, and the speakers sit at wildly different
distances from the camera — which is what makes it a useful teaching case, and
what broke two things badly enough that both are now blocking gates.

Every failure below really happened in that edit. Where a lesson comes from a
different build, it says so. Commands assume the skill directory is on your
`PATH` or referenced by full path.

## 0. Is this machine ready?

```bash
python3 doctor.py            # ffmpeg / Pillow / numpy — everything else degrades
python3 gates.py --preflight # prints THE house style you are about to build to
```

Read the preflight before cutting anything. It is `house_style.json` rendered as
a checklist — font, caption sizes, pill geometry, hook/end-card requirements.
The markdown docs explain the rules; that file *is* the rules.

## 1. Plan the length before cutting

```bash
python3 plan.py ~/Downloads/dev_jam_2026 --platform reels
```

```
素材：43 個檔案 / 996 秒（使用者拍好的，接下來是二次選擇）

★ 建議長度 1:56（116s）
  由留存推導：6 個 payload → 68–116s
  平台慣例區間 75–150s（reels）

結構 = hook 2-3s + payload×6 各 8-14s + 過場 25% + 結尾 4-6s

預計用 22 段，約 21 個素材不會用到 — 這是正常的
```

**Tell the user the number now.** A length is something they can argue with in
one line; discovering it after eleven versions is not.

Note what happened next: the finished edit is **90s, not 116s** — and it used
29 segments where the plan expected 22. The recommendation is a ceiling derived
from payload count, not a target to fill. Six teams really are six payloads, but
each one earned about 10s rather than the 14s the upper bound allows, and the
result is tighter for it. Coming in under the number is a good sign. Overrunning
it because footage exists is not: 996s of source became 90s, and the 906s that
did not make it *is* the edit.

## 2. Intake — research, don't guess

Three passes over the folder, before writing a single caption:

1. **Contact sheet** — one mid-frame per clip, tiled. Ten minutes here decides
   the story order. With 43 clips this is not optional.
2. **Slides at full resolution.** This edit is the cleanest possible argument
   for it: the pills name the teams — 醫路通, City-Mu, SUBTERRAT, 大台北即時轉乘
   — and **not one of those names appears anywhere in the ASR**. Nobody said
   them out loud; they existed only on the title slides. Caption from the
   transcript alone and every team in the video is anonymous.
3. **Per-clip ASR survey** (faster-whisper, `language=None`). Two traps, both
   hit here:
   - **Never pass `initial_prompt` on noisy room audio.** A descriptive prompt
     came back *verbatim* as the transcript of a 6s clip. Fix domain nouns in
     the proof-read pass instead; do not prime the decoder.
   - **`large-v3` loops forever on near-silent audio.** Guard with
     `condition_on_previous_text=False` plus `no_speech_threshold`, skip clips
     whose `max_volume` is under about −25 dB, and run each clip in a subprocess
     under a wall-clock cap. One bad clip should not stall a 43-clip batch.

The survey is also where the payload turns up. Here it was the judges: their
questions score far higher than the room-distance pitch audio, and the sharpest
one — a judge asking a team how they stop prompt injection from feeding the
model unrelated content — became a caption.

## 3. Cut — the build script (`vp_build.py`) writes `timeline.json`

A segment list is code, not clicks: `(id, file, start, end, note)` tuples, cut
to 1080×1920/30fps with tiny audio fades. Compose `modules/buildkit.py`
primitives rather than hand-writing ffmpeg graphs, and run
`build_lint.py your_build.py` before executing it — that check reads the
*construction*, which gates never see.

Three traps this structure exists to catch:

- **Still photos and end cards need an audio track.** A photo segment cut with
  `anullsrc` ships digital silence, and the Audio gate's dead-air check (max
  0.8s) catches it. Carry a neighbouring clip's ambience under every still.
- **Quiet sources need measured gain, not guessed gain.** Set gains from
  measured peaks, then *re-measure the render*: the delivery gate downmixes to
  mono, and correlated stereo gains about +3 dB there. Target ≈ −4 dBFS stereo
  peak and check again.
- **`buildkit.overlay_pills` bakes `int(d * FPS)` frames**, so a one-frame span
  (0.0333 × 30 = 0.999) yields ZERO frames and ffmpeg reports "matches no
  streams". Use `2 / FPS` for a cover overlay.

## 4. Captions — two layers, width-checked at birth

- The **pill** (18% height, PIL capsule via `modules/title.py`) NAMES the
  section. Here it counts the teams through: `Google DevJam 2026`,
  `第 1 組・醫路通`, … `評審的筆記`. Eight pills, one per act.
- The **caption** (70% baseline) EXPLAINS it, authored from what the slides and
  transcript actually say. Verbatim `Speech` style is reserved for ASR that
  scores high — it gets sync-checked against `words.json`.

Every style must be declared in `layout.json`, or the Captions gate fails:

```json
{"Speech": "caption", "Note": "caption", "Hook": "caption"}
```

Run the width check **inside** caption generation, so an overflowing `.ass`
cannot exist on disk:

```
caption layout rejected:
  - 1 caption line(s) wider than the safe area: 那如果他 prompt 給不相關的內 (1162>960)
```

That rejection is the system working. Shorten the line, regenerate.

**A caption also has to stay on screen long enough to read.** `MIN_CAPTION_S =
1.8` had lived in `plan.py` as advice from the beginning and nothing enforced
it — so this edit shipped a **0.75s caption with every gate green**. That is
what the Dwell gate now exists to stop, and why advice that matters gets moved
into `house_style.json` where a number can block a hand-over.

## 5. Cover and end card

`modules/cover.py`: max two lines, the big line says the *experience*, product
names go in the subtitle, burned as an **overlay on frame 1** — prepending a
cover segment shifts every caption by one frame. The end card is a PNG in the
work dir; the Structure gate checks the video actually ends on it, and the Audio
gate checks that ending is not silent.

## 6. Mix — editorial speech gate, both versions

Sidechain compressors and VAD both fail on venue ambience (measured: the key
never drops below threshold; VAD scores crowd babble as 82% speech). So the gate
is **editorial**: a written-down set of segment ids where someone worth hearing
talks — original audio full there, music leads elsewhere. numpy envelopes with
raised-cosine ramps, applied with `amultiply`.

**This is the build that proved amplitude detection cannot do it.**
`buildkit.duck_mix` triggered on an absolute peak (`env > 0.12`), calibrated for
one person on a close mic. Differencing the music render against its no-music
sibling — `references/duck_check.py` in this repo does exactly that — showed:

| | absolute-amplitude duck | editorial envelope |
|---|---|---|
| close mic (judge asking) | −7 to −9 dB | −9 to −10 dB |
| room-distance speakers | **−1.9 to −3.0 dB** | −7.5 to −10.7 dB |
| paper-rustle shot, nobody talking | **−8.5 dB** | −0.6 dB |

It missed the quiet speakers *and* pumped on non-speech transients, and twelve
gates were green the whole time. The Duck gate now measures this the same way.

Two more rules the mix has to respect:

- **Keep the original audio at ONE level and move only the music.** The gates
  recover the bed as `music render − no-music render`. Pull the original down in
  the music version only and that subtraction leaves −0.9× of the room inside
  what the gate measures as "bed" — loudest exactly where the room is loud. A
  later edit read as a 1.6 dB duck against the 4.0 dB floor for precisely this
  reason; the mix was wrong, not the gate.
- **Per-segment ambience gating is a music-version decision that silently breaks
  the no-music deliverable.** Gating b-roll to 0.05–0.35 here put 11.25s under
  the −45 dBFS floor — inaudible in the music version, obviously broken in the
  other. In a quiet auditorium keep every segment at its original level and let
  the duck carry the music version.

Always render **both** `NAME-<track>.mp4` and `NAME-nomusic.mp4`, and gate both.

## 7. Gates — the argument you are not allowed to win

```bash
python3 verify.py WORK_DIR --output FINAL.mp4
python3 gates.py  FINAL.mp4 --work-dir WORK_DIR   # exit 1 = do not ship
```

Sixteen blocking gates. Treat a non-zero exit as the answer to "is this
finished", not as an obstacle to argue with — and re-run on **every** render,
because a version that passed yesterday is not evidence about today's file.

> Do not reason about whether a measurement is acceptable.
> A number outside the threshold is a failure **even when you can explain it**.

Two gate mechanics worth knowing before they confuse you:

- **Duck and MusicBed need the no-music sibling, and they pick it as the first
  `*-nomusic.*` in the directory, alphabetically.** Leave an older cut in the
  project root and the gate differences your new render against a *different
  video* — the symptom is a duck depth that will not move no matter what you
  change. Keep exactly one music/no-music pair at the project's first level and
  archive older versions into a subfolder.
- **Clipping is usually one transient, not the whole mix.** Locate it before
  touching any global gain: decode both renders, take a per-10ms max, and print
  the hottest frames with the segment id they land in. Attenuating one shot
  beats lowering the bed everywhere.

## 8. The human-eye pass gates cannot do

Gates check position, not style, and they cannot check meaning at all. Extract a
frame at every caption moment, tile them, and *look*:

- is anything covering a face; is the pill a proper capsule
- **does each caption describe what is actually on screen under it?** This is
  the failure mode no gate reaches. In a later edit three captions passed all
  sixteen gates while describing things the footage did not show — a queue of
  people that was not in frame, a departure that was really a dash for a flight,
  a logo read as an event brand it was not. Each was written by inference from
  the image instead of from evidence. If a line states something you cannot read
  off the frame, verify it or ask the person who was there.

In this skill's history a rebuild also shipped wrong typography with every gate
green — which is why the templates say "copy the previous build's style block,
do not re-derive it".

## 9. Ship

Deliverables land in the **project root** — `NAME-<track>.mp4`,
`NAME-nomusic.mp4`, `cover.jpg` — with everything else in `build/`. Same three
files, every project.

`decisions.json` ships with them, and it is the record of what only the user
could decide. This edit's, in full:

```json
{
  "loudness": {
    "value": "original",
    "why": "the user asked for an edit, not a delivery level. Levels differ
            wildly between the room-distance phone shots and the close mic, so
            segments are gain-balanced against each other and a limiter prevents
            clipping, but no -14 LUFS normalisation is applied."
  },
  "captions": "on",
  "end_card": "on"
}
```

A value that departs from the documented default needs a `why` the user actually
agreed to — not a rationalisation written afterwards.
