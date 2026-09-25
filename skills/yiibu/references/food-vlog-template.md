# Food / restaurant 花絮 — locked template

> **Build with `modules/buildkit.py`** (it self-lints the build script on
> import), record the user's calls in `WORK_DIR/decisions.json`, and gate with
> `gates.py` — all three are BLOCKING as of 2026-08-18. This template's recipe
> is unchanged; only the construction tooling moved into code.


Derived from the 2026-08-10 雅香石頭火鍋 edit (37s, 9:16, 17 segments).

**When this applies:** a folder of phone clips from one meal. Nobody narrates to
camera; the payload is the food and the process. Output is a 30–45s reel the
user shares with friends and uses to recommend the place.

This is a *third* shape, distinct from the other two templates:

| | talking-head vlog | this |
|---|---|---|
| payload | what the speaker says | what the food/process shows |
| captions | transcribed speech | **authored narration** |
| audio | speech is the content | ambience is texture |

## 1. Intake — build a contact sheet before planning

```bash
python3 plan.py SOURCE_DIR --platform reels     # builds SOURCE_DIR_sheets/
```

That writes both: one mid-frame per clip into a contact sheet, and a **6-frame
filmstrip per clip** into `SOURCE_DIR_sheets/filmstrips/`. It used to be this
section asking you to build them by hand, and on 2026-09-01 it was skipped —
the hook was chosen off one 300px mid-frame and turned out to be a neck and an
ear in five of its six frames, with its only readable frame outside the cut. A
step you have to remember is a step that gets missed, so plan.py does it.

**Look at the filmstrips before writing the edit list**, and never judge framing
off the contact sheet alone. The single most valuable shot in the
雅香 edit — a price board reading `蛋10 白飯20 / 30 60 60 100 70 70 80`, which is
what makes the whole "看盤子顏色算錢" concept legible — was invisible in the
contact sheet and only surfaced in IMG_2628's filmstrip at 2.29s.

## 2. Do NOT transcribe-and-caption

Restaurant noise breaks ASR. Measured on this material:

- `initial_prompt` came back verbatim as the "transcript" for 12 of 14 clips
  (prompt echo) — never pass a topical `initial_prompt` to Whisper here;
- with VAD and no prompt, word confidences ran 0.02–0.37 and output flipped
  between takes (`太香了吧` / `台湾的烧饼` / `像个年轻人` for the same 2 seconds);
- language auto-detect split the room correctly (host zh, guests en) but the
  content was still unusable.

So: **captions are authored from what the user tells you the place does**, not
from ASR. Caption a spoken line only when the user states it or ASR is
confident (`Smell so good` scored 0.95 and was used; nothing else was).

**Authored captions are hand-timed, and hand-timed captions collide.** ASR-built
captions cannot overlap — each phrase ends where the next word-group begins. The
moment you author them, that guarantee is gone, and the trap is specific: a
1.5-2s shot is shorter than the 1.8s dwell floor, so every line gets stretched
into the NEXT segment to qualify. Two neighbours stretched toward each other
cross. On the 莫宰羊 build 清湯底／整鍋都是肉 rendered on top of 肉片一下鍋／顏色馬上
就變 for 0.45s and shipped.

When two lines share an anchor, **the first one's end IS the second one's
start** — one expression, not two independent ones. `gate_captions` now fails on
same-anchor temporal overlap, but write the handoff explicitly anyway; the gate
is the second line of defence, not the design.

## 3. Story order — process, not chronology

```
0  reaction (0.8s, no caption)      ← a face enjoying it, silent punch
1  the hook line, hero caption      ← the best steam shot
2  the "why care" info beat         ← the one shot that explains the gimmick
3-6 how it works, in order          ← 拿料 → 計價 → 炒 → 倒湯 → 滾 → 醬料
7  開動 + eating reactions
8  everyone approves
9  group photo end card
```

Segments run **1.3–2.8s**; 17 of them plus a 2.9s end card ≈ 37s. The info beat
belongs at position 2, right after the hook — leading with "顏色決定價錢" is a
stronger reason to keep watching than another pretty steam shot.

## 4. Facts — read the frame at full resolution

Before putting a number or a shop claim on screen, extract that frame at full
size and read it. The prices above were only quoted after doing so; a first
pass had them illegible and the caption was written without numbers instead.
Never state 年份 / 老店幾十年 / prices the footage doesn't show.

## 5. Cover

Cover must contain **food**. A group photo reads as a group photo at thumbnail
size and kills the click — and the group photo is already the ending, so
spending it on the cover throws away the payoff.

- source: a reaction frame with the shop sign in frame;
- `fill_scale * 1.16`, anchored bottom, so the face sits in the upper half;
- light vignette only (top ~110α over 13%, bottom ~150α over the last 26%);
- title ~1075, subtitle scaled so its **rendered width matches the title's**
  (measure with `textbbox`, don't guess a point size);
- bake it as frame 1 (`-loop 1 -t 0.034` segment at the head of the concat) AND
  ship the standalone JPG.

## 6. Top info card

Same pill as `modules/title.py`. **Starts after the hook**, not over it — delay
it with `tpad=start_duration=<hook_end>` on the pill clip. On this edit the
hook ran to 3.28s and the card showed 3.28→8.48s.

Text names the experience (`第一次品嚐雅香石頭火鍋`), not the location.

## 7. Audio — the room is NOT the soundtrack; the sizzle is

The first version of this section said "leave it alone: the ambience (bubbling,
clatter, chatter) *is* the food-video soundtrack". That is true of about a third
of the shots and wrong about the rest, and applying it to a whole cut produced
the 2026-08-21 defect: 48 seconds of continuous restaurant hum under a music
bed, on a video where nobody says a word to camera. Every gate was green. The
user's verdict took one pass —

> 音樂反而變得很小聲，但實際上影片裡根本沒有人在說話

Room tone is not the soundtrack. The **sizzle** is, the **boil** is, the pot
landing is, someone laughing is. The 40 dB of air-conditioning between them is
what buries the music.

So audio is a **per-segment editorial decision**, recorded in `decisions.json`
as `audio_policy` and spelled out in `WORK_DIR/audio_policy.json`:

| keep | what it means |
|---|---|
| `VOICE` | someone in the video is audibly speaking or laughing |
| `SFX` | a sound event — the pot set down, the ladle, the lid |
| `FOOD` | the food itself is making the sound — boil, sizzle, slurp |
| `null` | room tone only → attenuated, the music takes the stretch |

**Default for this template is `selective`.** `full` is still allowed — it is
right for a talking-head vlog — but it needs a written why, because it is the
answer that shipped the defect.

### Getting the evidence

```bash
python3 modules/audio_scout.py WORK_DIR/segments
```

Per segment: dBFS, voiced fraction, sizzle, event rate. Read it, then decide —
and note what it CANNOT do for you. In a full restaurant it scores every one of
28 segments as "voiced", and it is not wrong: other diners are talking. No
threshold separates "our subject is speaking" from "the room murmurs", which is
exactly why `gate_audio_policy` checks that a person answered rather than
checking the answer.

The one number that did discriminate on the 莫宰羊 build was **prominence** —
how far the segment's own p90 level sits above the cut's noise floor. The
loudest food beat (涮, +14.2 dB) and the emptiest one (麵線, −1.2 dB, literally
below the floor) are 15 dB apart. Use it as a sanity check on your calls, not
as the rule: it also ranks street traffic above a sizzling plate.

### Levels

- **Muted segments are attenuated, not silenced.** `MUTE_DB = -20` in the build
  script. Digital silence is the literal reading of 靜音 and the wrong
  construction: the no-music sibling would carry real dead air, and that sibling
  is what `gate_music_bed` and `gate_duck` SUBTRACT to find the bed. At −20 dB
  under a bed at full level the room is inaudible — that is the mute a viewer
  experiences — while both files stay well-formed.
- **The duck follows the policy, not a level meter.** Kept segments are, by
  definition, the ones whose sound is the payload; the bed steps back on exactly
  those and nowhere else. An amplitude detector cannot find them — it fires on
  restaurant clatter and punches holes in the music, and it never aligns with
  the buckets `gate_duck` measures into (asked 8 dB → achieved 5.4 → gate read
  1.2). Driven by the policy, asked 12 dB reads 7.5 dB of real separation.
- **The hook gets music.** Never duck the opening; the bed comes in with the
  first frame.
- **Ship at the original recording level** apart from per-segment declipping and
  the smallest trim that keeps the AAC deliverable under full scale. Measure the
  DECODED file, never the filter graph.
- Intermediate segments carry **PCM in `.mov`** so the final mux is the only AAC
  encode.

### Check the mix in the BAND, never broadband

```bash
python3 mixcheck.py WORK_DIR --music NAME-track.mp4 --nomusic NAME-nomusic.mp4
```

The same wrong measurement was made twice on the 莫宰羊 build and reported to the
user as fact both times: room -25.9 dBFS against bed -23.5 dBFS, therefore "the
room leads". It does not follow. **Masking is spectral.** In the band the sizzle
actually occupies (4-10 kHz) the bed was already 8.9 dB ahead of it — and at the
bed level two steps quieter, still 1.7 dB ahead. The sizzle those segments were
kept for had never been audible, and the broadband number said the opposite.

A bright track (hats, air) will eat a sizzle while leaving a rolling boil
untouched, because the boil lives at 80-800 Hz and the hats do not. Two segments
with the same `keep: FOOD` label can therefore land on opposite sides of the
line. `mixcheck.py` measures each one where its own sound lives.

A masked kept segment is not automatically a defect — sometimes the room is
wanted as texture — but it IS a decision, so `gate_audio_policy` prints
`kept_but_masked` on every run. Keeping a segment's audio for a sound nobody can
hear is a note-to-self, not an edit.

Measured on the 莫宰羊 build, which is what this should sound like:

```
KEPT   (17 segs)  room -22.3  bed -29.9   -> room leads by  7.5 dB
MUTED  (11 segs)  room -42.3  bed -21.2   -> music leads by 21.1 dB
```

## 8. Before shipping

`verify.py` is the advisory report and cannot stop anything. `gates.py` is the
one that blocks, and this recipe used to name only the first — run BOTH, on
BOTH variants:

```bash
python3 verify.py WORK_DIR --output FINAL.mp4    # advisory
python3 gates.py  FINAL.mp4 --work-dir WORK_DIR  # BLOCKING — exit 1 = do not ship
```
