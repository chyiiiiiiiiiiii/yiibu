# Running / sport talking-head vlog — locked template

Derived from the 2026-08-09 夜跑 5K edit. **Build to this template first; only
tune when the user asks.** It covers the case the main pipeline does not: a
*folder of phone clips* (not one recording) where the talking is the payload.

Not to be confused with the `running-video` skill — that one is for beat-synced
scenery montages with a minimap. This is for "I just ran, here's what I learned".

## When this applies

Several clips from one session, most of them talking to camera, one or two with
no speech (scenery / running form). Output is a 9:16 IG Reel, 45–70s.

## 1. Intake — inspect, don't ask

`ffprobe` every clip for duration + `stream_side_data=rotation` (iPhone
landscape clips carry `rotation=-90` and ffmpeg auto-uprights them; the
`scale=…:increase,crop` chain below handles either orientation).

Transcribe each clip **separately** before planning the order — the transcript
is what tells you which clip is the hook and which is the payload.

## 2. Story order — result first, not chronological

```
hook (the result line, ~1.8s)      ← the number the viewer came for
first running clip (motion)
no-speech b-roll clips, grouped
main content (the payload)
result assessment
sign-off
```
Put the no-speech clips **together, early**, right after the opening motion
clip. Splitting one into the middle of the talking looks like a breather on
paper but reads as an interruption; the user asked for them adjacent.

Ordering is a judgement call — write out the `PLAN` list of
`(clip, in, out, label)` and rebuild from it, so a reorder is a one-line edit.

## 3. Silence removal — measure, don't trust `silencedetect`

Outdoor night audio sits well above -30 dB, so `silencedetect` returns nothing.
Profile the speech band instead:

```
highpass=250, lowpass=3400, 50ms hop RMS
threshold = percentile25(dB) + 8
```

- Cut only gaps **> 0.7s**; leave ~0.18s at each cut. Cutting every micro-pause
  makes a talking head feel frantic.
- Typical yield: a 9.5s clip with 6s of dead air → 3.6s.

**Cut boundaries must contain the whole trailing word.** A boundary placed at
the ASR's word-end clips the tail (a 「以上」 was lost this way and only surfaced
when the user spotted the missing subtitle). After cutting, re-run ASR on the
span and confirm the last word is intact; pad the out-point ~0.2s if not.

## 4. Assembly

Per segment, then `concat` demuxer:

```
-vf scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,format=yuv420p
-af aresample=48000
-c:v h264_videotoolbox -b:v 20M   -c:a aac -b:a 192k -ac 2 -ar 48000
```

## 5. Transcript

Concatenating segments invalidates every timestamp. Two options:

- Re-transcribe the assembled base (slow), or
- **remap the per-clip word times** with a piecewise offset built from the
  segment marks. Faster, and it preserves hand corrections. Keep the original
  `words_v1.json` and always remap *from it*, never from an already-remapped
  copy.

Remap boundaries need slack: ASR word starts can precede the segment boundary by
~0.25s, so pick a threshold in the silent gap, not exactly at the cut.

Then run the **`transcript-proofer` agent** (see SKILL.md step 2). It
re-verifies its own suggestions against the audio; apply `fix`/`missing`,
adjudicate `uncertain` yourself.

## 6. Subtitles — the locked config

```python
pos = {"y_ratio": 0.780, "alignment": 2, "clear_top": 0.60, "clear_bottom": 0.90}
bilingual = False                      # Chinese-only for a personal reel
KEYWORD_POP_ANIMATION = False          # static gold, no scale-pop
EMPHASIS_BLOCK_STEP   = 175            # 250 reads as two unrelated lines
EMPHASIS_MIN_CHUNK_SEC = 0.4
EMPHASIS_MIN_PHRASE_SEC = 0.6
```

- **Disable the LLM segmentation and review passes.** On short bursty speech
  they split mid-word, produce 7-second captions and 0.1s flashes, and the
  result changes between runs. Rule-based grouping is deterministic and better
  here:
  ```python
  S._segment_with_llm = lambda words: None
  S._review_subtitles_with_llm = lambda words, phrases, keywords: None
  ```
- **Pin the hero captions** rather than letting `_detect_emphasis_moments` pick.
  The LLM promotes flat lines (「但整體來說都還不錯」) and its choice drifts:
  ```python
  HERO = ("步頻170心率170", "慢慢來", "明天繼續加油", "Let's go")
  S._detect_emphasis_moments = lambda texts: {
      i for i, t in enumerate(texts) if any(h in t for h in HERO)
  }
  ```
- **Force phrase breaks with punctuation** in `words.json` (`險。` `進。`
  `不錯。`) — the rule-based grouper breaks on punctuation, so this is the lever
  for fixing a boundary, including at clip cuts.
- Keep word timings **strictly monotonic** after hand edits; a negative gap
  makes the grouper break the line.
- The grouper also breaks where a **gold keyword span ends**. If a trailing word
  must stay on the same caption as a keyword (`步頻170` + `以上`), merge them
  into one token — and write it without a space (`170以上`), since a literal
  space in the token survives into the render.
- Merge ASR-split digits into one token (`16`+`8` → `168`) or CJK-Latin spacing
  inserts gaps mid-number.

## 7. Cover

Ship **both**: a standalone JPG and the same image baked as frame 1
(`-loop 1 -t 0.034`), so IG's default cover is already designed.

- Source: pick a sharp, well-lit frame with the face in the upper half. Score
  candidates by gradient energy + brightness, then *look at them*.
- **Zoom past fill and anchor the crop to the bottom** (`fill_scale * 1.20`,
  `t = height - H`). This lifts the face into the upper half so the caption
  block never lands on the chin — the failure mode on the first attempt.
- **Light vignette only** (top ~110α over 13%, bottom ~140α over the last 26%).
  A heavy bottom scrim was rejected; legibility comes from each text run's own
  soft drop shadow (blur 13, offset (0,7), ~205α), not from darkening the photo.
- Layout: statement line ~y985 (86px), `均速` + gold pace ~y1170 (pace at 216px
  Futura), nothing below unless asked. Keep text inside y 500–1500 so IG's
  square/4:5 grid crop does not cut it.

## 8. Audio

Ambient only at `volume=2.25`, **no BGM by default** (the user removed it), then
`loudnorm=I=-14:TP=-1.5:LRA=11`. Target ≈ -15 LUFS integrated, true peak ≤ -1
dBFS. Speech should land -17 to -21 dBFS RMS, b-roll ambience -25 to -30.

If BGM is asked for: pick the window by scanning 1s-RMS over the track and
maximising the **worst second** across the needed span, not the mean — an
"inspiring" track dipped to near-silence mid-video. Duck with
`sidechaincompress:threshold=0.12` (0.05 keeps outdoor ambience permanently
above threshold, so the music never comes back up) and `amix:normalize=0`.

## 9. ffmpeg gotchas that cost real time here

- **Use `h264_videotoolbox`.** Software x264 on 1080×1920 + libass ran >20 min
  and produced a 550MB file; videotoolbox does the same job in ~10s.
- **Bound every `-loop 1` image input with `-t`.** Unbounded loops let the
  encode run away far past the video length. This was the actual cause of the
  slow render, not libass.
- `settb=AVTB` on **both** branches before `xfade`, or it fails with
  "timebase do not match".
- `asetpts=N/SR/TB` must come **before** `atrim` when the input used `-ss`;
  otherwise `atrim=0:X` filters against the seek-offset timestamps and silently
  truncates the audio (music stopped 20s into a 56s video).
- Never let two ffmpeg jobs write the same output path — the file ends up with
  no moov atom.

## 10. Deliverables

`~/Desktop/running-YYYY-MM-DD/` containing the mp4 and the cover JPG. At ~14
Mbps a 50s reel is ~78MB, which exceeds the chat upload limit — send the cover
inline and give the user the path for the video.

## 11. Hand-built ASS numbers (0813 上海版 learnings)

When the subtitle module is bypassed and the ASS is written by hand (folder-of-clips
builds), these are the locked numbers — they were re-derived the hard way when a
build shipped with 80px-flat subtitles ("字幕又變小了") and an overflowing line:

- body **82px**, gold keywords **90px** (`{\fs90\c&H66DBF6&}…{\fs82\c&HFFFFFF&}` — colour is house_style.json captions.keyword, the user-locked #F6DB66; the old &H5AD6F5 here predated that lock),
  hero **132px** — same as config.py `FONT_SIZE_DEFAULT/KEYWORD/EMPHASIS`.
- **Line-width gate is BLOCKING**: measure every line with PIL at its real per-span
  size; > **960px** (1080 − 2×60 margins) = build failure, not a judgement call.
  Fix by splitting at a semantic break into two timed events (proportional times),
  never by letting it clip.
- Uncertain proper nouns / numbers ("?K 5分44秒", unverifiable park names) get a
  caption that dodges the unknown, then ONE question to the user — they answer in
  seconds and it's a one-line rebuild.
- Worked example (segments → concat → cutaways over the monologue → hand ASS →
  duck/loudnorm → cover burn): `references/examples/running-vlog/vp_build.py`.
  amix gotcha: ambient stream FIRST in `amix=duration=first`, or audio outruns video.
