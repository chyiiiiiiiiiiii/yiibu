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

`ffprobe` every clip (duration + `stream_side_data=rotation`), then:

1. one mid-frame per clip → single contact sheet;
2. a 6-frame filmstrip per clip you might use.

**Do this before writing the edit list.** The single most valuable shot in the
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

## 7. Audio — leave it alone

The ambience (bubbling, clatter, chatter) *is* the food-video soundtrack. Ship
at the original recording level: no loudness target, no compressor, no limiter.

The only permitted touch is **per-segment declipping**: if a segment's source
peaks above 0.95, attenuate that one segment by the minimum dB that clears full
scale. On this edit exactly one of 17 segments needed it (IMG_2636, -1.38 dB;
its source peaks at +0.9 dBFS and ticked audibly).

Intermediate segments carry **PCM in `.mov`** so the final mux is the only AAC
encode.

If BGM is asked for, mixing forces headroom: ambience `0.85` + music `0.12`
(`0.95*0.85 + 0.12 = 0.93`). Verify the decoded peak afterwards.

## 8. Before shipping

Run the delivery gate — see `delivery-traps.md`. Both variants must PASS:

```bash
python3 verify.py WORK_DIR --output FINAL.mp4
```
