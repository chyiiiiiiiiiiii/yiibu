# Walkthrough — one real edit, start to gates

This follows an actual project: a one-day conference 花絮 (the 2026 APAC GDE
Summit, 20 phone clips, 195s of footage → a 93.6s bilingual short). Every gate
failure below really happened in that edit. Commands assume the skill directory
is on your `PATH` or referenced by full path.

## 0. Is this machine ready?

```bash
python3 doctor.py            # ffmpeg / Pillow / numpy — everything else degrades
python3 gates.py --preflight # prints THE house style you are about to build to
```

Read the preflight before cutting anything. It is `house_style.json` rendered as
a checklist — font, caption sizes, pill geometry, hook/end-card requirements.
The markdown docs explain the rules; this file *is* the rules.

## 1. Plan the length before cutting

```bash
python3 plan.py ~/Downloads/0814_shanghai --platform reels
```

```
★ 建議長度 1:04（64s）
  由留存推導：3 個 payload → 38–64s
結構 = hook 2-3s + payload×3 各 8-14s + 過場 25% + 結尾 4-6s
```

**Tell the user the number now.** A length is something they can argue with in
one line; discovering it after eleven versions is not. (This edit later grew to
93s — because the user asked for more coverage, not because footage existed.)

## 2. Intake — research, don't guess

Three passes over the folder, before writing a single caption:

1. **Contact sheet** — one mid-frame per clip, tiled. Ten minutes here decides
   the story order.
2. **Slides/signage at full resolution.** In this edit a slide read "What's new
   with **Gemma 4**" while ASR heard *"Java 4"* at 0.84 confidence. On-screen
   evidence wins over ASR, always — a caption that disagrees with the screen
   behind it reads as a typo.
3. **Per-clip ASR survey** (faster-whisper, `language=None`, no initial prompt —
   a prompt's words leak into whatever it can't hear). The survey found the
   payload: a panel answer scoring 0.92–1.00 that became the video's quotable.

## 3. Cut — the build script (`vp_build.py`) writes `timeline.json`

A segment list is code, not clicks: `(id, file, start, end, note)` tuples, cut
to 1080×1920/30fps with tiny audio fades. Two traps this file structure exists
to catch:

- **Still photos and end cards need an audio track.** A photo segment cut with
  `anullsrc` shipped 2.2s of digital silence — the Audio gate's dead-air check
  (max 0.8s) caught it. Carry a neighbouring clip's ambience under every still.
- **Quiet sources need measured gain, not guessed gain.** PA-distant clips sat
  10–19dB low. Gains were set from measured peaks — then still clipped the
  delivery gate at 0.97–1.02, because the gate downmixes to mono and correlated
  stereo gains +3dB there. Target ≈ −4dBFS stereo peak, then re-measure.

## 4. Captions — two layers, width-checked at birth

- The **pill** (23% height, PIL capsule via `modules/title.py`) NAMES the
  section: `GDE Lightning Talks`, `官方 Q&A`.
- The **caption** (70% baseline) EXPLAINS it, authored from what the slides and
  transcript actually say. Verbatim `Speech` style is reserved for ASR that
  scores high — it gets sync-checked against `words.json`.

Run the width check **inside** caption generation, so an overflowing `.ass`
cannot exist on disk:

```
caption layout rejected:
  - 2 caption line(s) wider than the safe area: 昨天看到兩個 Gemma demo (1005>960)
```

That rejection is the system working. Shorten the line, regenerate.

## 5. Cover and end card

`modules/cover.py`: max two lines, the big line says the *experience*, product
names go in the subtitle, burned as an **overlay on frame 1** (prepending a
cover segment shifts every caption by one frame). The end card is a PNG in the
work dir; the Structure gate checks the video actually ends on it.

## 6. Mix — editorial speech gate, both versions

Sidechain compressors and VAD both fail on venue ambience (measured: the key
never drops below threshold; VAD scores crowd babble as 82% speech). So the
gate is **editorial**: a set of segment ids where someone worth hearing talks —
original audio full there, music leads elsewhere. numpy envelopes with
raised-cosine ramps, applied with `amultiply`.

Three level lessons, each from user feedback on this edit:

| symptom | cause | fix |
|---|---|---|
| "後面沒有聲音" | montage sections fully muted | keep light room tone (0.10) under the music |
| "開頭怎麼沒音樂" | music-only level tied with room tone | music must clearly LEAD music sections (0.40 vs 0.10) |
| "講話時音樂太小" | duck floor set for silence, not presence | duck to ~0.6× of the music-only level, never below audibility |

Always render **both** `NAME-<track>.mp4` and `NAME-nomusic.mp4`, and gate both
— the silent end card only failed in the no-music version.

## 7. Gates — the argument you are not allowed to win

```bash
python3 verify.py WORK_DIR --output FINAL.mp4
python3 gates.py  FINAL.mp4 --work-dir WORK_DIR   # exit 1 = do not ship
```

From this one edit, the gates blocked, in order: a 3.5s silent ending (twice —
no-music and music versions failed for *different* reasons), 3.0s of dead air
before a late music entry, and a 1.018 decoded peak from stacked gains. Every
one was "explainable". **Explaining a number is not checking it** — fix the
build until the number is inside the threshold.

## 8. The human-eye pass gates cannot do

Gates check position, not style. Extract a frame at every caption moment, tile
them, and *look*: is anything covering a face, is the pill a proper capsule, do
captions match what is on screen behind them. In this skill's history a rebuild
shipped wrong typography **with every gate green** — this pass is why the
templates say "copy the previous build's style block, do not re-derive it".

## 9. Ship

Deliverables land in the **project root** — `NAME-<track>.mp4`,
`NAME-nomusic.mp4`, `cover.jpg` — with everything else in `build/`. Same three
files, every project.
