# Delivery traps — read before shipping any video

Every entry here shipped broken at least once. They share one property: the
intermediate files all looked fine, and the defect only existed in the file the
viewer actually plays. `verify.py` reports on them (advisory) and `gates.py`'s
**Delivery** gate blocks on them — run both on the final mp4 and do not ship
on a gate failure.

```bash
python3 verify.py WORK_DIR --output FINAL.mp4
python3 gates.py  FINAL.mp4 --work-dir WORK_DIR
```

## 1. Don't touch the audio level unless asked

The `-14 LUFS` social-loudness target belongs to *published* content. A personal
花絮 / vlog / 紀錄 that the user wants to share with friends should ship at the
**original recording level**: no make-up gain, no compressor, no limiter, no
loudness normalisation.

Ask before normalising. Pushing a phone recording that already peaks near
0 dBFS up to -14 LUFS is what causes every problem in section 2.

The only audio touch that needs no permission is **preventing clipping**: if a
source segment peaks above ~0.95, attenuate that one segment by the minimum
amount that clears full scale. Leave every other segment at 0 dB.

## 2. Verify the DECODED file, never the filter graph

`ebur128` inside the filter chain reported `-1.0 dBFS` on a file that decoded at
`+1.57 dBFS` with **315 samples over full scale**. AAC reconstructs a
heavily-limited waveform *above* the limiter ceiling — measured **+3.07 dB** of
overshoot — and that clips on playback as crackle.

Always decode the finished mp4 back to float and check the peak.

If you must hit a loudness target on hot material:
- gentle `acompressor` **before** the make-up gain, so the limiter isn't clawing
  back 5 dB on every transient (that squashed waveform is what makes AAC
  overshoot);
- limiter ceiling at **-3.5 dBFS**, not -1.5;
- then re-measure the decoded peak. Lowering the ceiling alone is not enough —
  without compression even -16 LUFS still decoded above full scale.

`alimiter` also has `level=enabled` by default, which re-normalises the output
back up and defeats the ceiling. Always pass `level=disabled`.

## 3. Encode AAC exactly once

Encoding each segment to AAC and then re-encoding after concat stacks codec
generations for no reason. Give intermediate segments **PCM in `.mov`**
(`-c:a pcm_s16le`) and let the final mux be the only AAC encode.

## 4. `loudnorm` eats the tail and NaNs on silence

- It buffers ~3s of lookahead and **drops that much off the end** — the closing
  card ends up silent, and `-t` does not save you.
- Fed pure digital silence it emits NaN and kills the AAC encoder.

Use it to *measure* only (`print_format=json`), over the **content portion**
(exclude a silent closing card), then apply a constant `volume=NdB`.

Never put a synthetic noise floor under a silent closing card to dodge the NaN:
at -62 dBFS nominal it came back at **-24 dBFS** after gain — plainly audible
hiss. Use `anullsrc` and fix the measurement instead.

## 4b. The music bed dies before the video does — three separate causes

Shipped as "音樂最後三秒直接斷掉". `gate_audio` passed the whole time, because it
measures the finished MIX and someone was still talking over the silence. Only
the music/no-music PAIR shows it. `gate_music_bed` now blocks on this; the three
causes underneath it were found one at a time, each hiding the next:

1. **`afade=t=out` after `atrim`+`asetpts` does not ramp — it hard-cuts the
   stream to digital zero** (-180 dBFS) at the fade start. Same render with the
   filter deleted held -19 dBFS to the last sample. Shortening the fade only
   moves where the cliff lands, which is what makes it look like a fade problem.
   There is usually no reason to fade at all: let the bed play until the video
   ends.
2. **`-ss` + `-stream_loop` + `asetpts` before `aresample` + `atrim` in one
   graph** produced a 167.5s bed branch for an 83.9s video, so the bed's timeline
   did not match the picture's. Pre-render the bed to its own file and **assert
   its length equals the video's** instead of reasoning about the graph.
3. **`sidechaincompress` → `amix` silently stopped passing the bed ~1.6s before
   the end**, with `bed.wav` measuring -23.6 dBFS at that point and the mixed
   output bit-identical to the no-music version. Three filter-graph fixes each
   moved the number without explaining it. Computing the duck envelope in numpy
   (10ms hop, attack/release smoothing, fixed depth) and adding the bed to the
   speech directly is a dozen lines, is fully measurable, and has no opinions
   about stream lengths.

**Measure the delivered PAIR by absolute level, never by subtracting them.**
Both files are AAC-encoded independently, so in quiet passages the difference is
codec noise: identical build settings measured 1.18s of dead tail on one rebuild
and 2.93s on the next. Comparing each file's own RMS answers it directly — if
the music version is not louder than its `-nomusic` sibling at time T, there is
no music at time T. `gate_music_bed` therefore judges against the bed's own
median rather than an absolute dBFS line.

`modules/bgm.py` still uses the `sidechaincompress` construction from cause 3 and
its `measure_audible_end()` inspects the **BGM file**, not the delivered mix —
which is why it never caught any of this. Treat that as unfixed.

## 5. Concat leaves video starting at +0.033s → black first frame

The concat demuxer hands back `start_pts=507` on video while audio starts at 0.
Players have no picture at t=0 and paint it black.

- **Fix:** `-fps_mode cfr` on the re-encode.
- **Not** `setpts=PTS-STARTPTS` — across concat boundaries it silently dropped
  the entire closing card (1025 frames instead of 1109).

## 6. Two ways to hang ffmpeg forever

Both produce a full-size output file and then never exit:

- **`-loop 1 -i cover.png` feeding an overlay.** `-t` does not make the looped
  input EOF. Render the overlay to a finite alpha clip first
  (`-c:v qtrle` `.mov`), then overlay that file.
- **A bare `apad`.** It never signals EOF, so the muxer waits forever after the
  video ends. Bound it: `apad=whole_dur=<total>`. Also check the video stream is
  actually full length — a short video stream plus padded audio hangs too.

## 7. ASS `Format:` must list `Name`

```
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
```

Omitting `Name` misaligns every field by one and a stray `0,` renders as a
leading comma on every caption.

## 8. Use the house font, don't substitute

Font, sizes, colours and margins come from `config.py` — `演示斜黑体`,
`FONT_SIZE_DEFAULT = 82`, outline 0 / shadow 5, and the rounded title pill from
`modules/title.py`. Substituting a "nicer" font makes the video inconsistent
with every other one the user has published. Check glyph coverage before using
any character: `演示斜黑体` has `·` (U+00B7) but LINE Seed TW lacks `・`
(U+30FB) and renders tofu.
