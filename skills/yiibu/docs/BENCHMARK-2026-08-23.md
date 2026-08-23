# Three drivers, two folders — 2026-08-23

The one benchmark page this repo keeps. Two runs, the same three drivers, on
deliberately different material:

| | footage | what it exercised |
|---|---|---|
| **round A** | a rained-out evening road race, 28 clips, nobody narrating | the event path: authored captions only |
| **round B** | a morning 5K, 19 clips, **one 63-second take of somebody talking to camera** | the speech path: ASR, `proofread.py`, `gate_sync` |

Round B exists because round A left the entire ASR half of this skill untouched:
zero `Speech` captions across all three builds, so `proofread.py`, `gate_sync`
and the prompt-echo guard were never reached. That was the right call and it was
measurable rather than a matter of taste — an ASR pass over round A's 27 clips
produced 63 words at **median confidence 0.38**, 56% of them under 0.5, reading
like 「才告訴各位要好發明有信任性」 (0.53) and 「快走」 (0.04).

A first attempt at round A, a day earlier, could not be quoted. Its source folder
had a previous edit of the same footage in it — four finished videos, the cover,
the music, and `project_config.py`, that edit's whole configuration — and one
driver reused it string for string: `ENDING_CAPTION = "WHAT A GREAT DAY"` came
out as the closing caption verbatim, `TOP_TITLE = "沒想到是VISOGE水上樂園"` as the
hook, and the music file as the deliverable's name. That was the harness's
failure, not the model's, and `bench.py` exists because of it.

---

## What the two runs establish

**Six builds, three drivers, two kinds of footage. Every one reached `exit 0` on
17 blocking gates. Not one on the first render.**

> Quality lives in the executable checks, never in the agent driving them.

That sentence has been an assertion in this repo since the beginning. This is the
evidence, and two runs on different material is meaningfully more than one.

**What it does not establish is a ranking of models.** One run per driver per
folder, one viewer, no rubric, and cost data that is real for two drivers and
absent for the third in units that do not mean the same thing. Round B's ranking
came out in a different order from round A's, which is the clearest statement of
how much weight a single run carries.

---

## Round B — measured

From each run's `build_log.jsonl` and `notes.json`, and from `review.py` over
each finished file. Nothing here is typed by hand.

| | Claude Opus 5 | gpt-5.6-terra | Gemini Flash | gpt-5.6-sol |
|---|---|---|---|---|
| verdict | shippable | shippable | shippable | shippable |
| renders rejected first | 5 | 2 | 2 | 3 |
| length | 46.67s | 49.80s | 58.83s | 59.77s |
| segments | **26** | 15 | 14 | 17 |
| cuts per second | **0.56** | 0.30 | 0.24 | 0.28 |
| shortest shot | **0.20s** | 1.50s | 1.50s | 1.50s |
| **the 63s take: pieces / kept** | 11 / 10.2s | 5 / 28.7s | **3 / 38.2s** | **— / 6.0s** |
| captions | Hook 1 · Speech 9 · Note 5 | Hook 1 · **Speech 0** · Note 10 | Hook 1 · **Speech 13** · Note 4 | Hook 1 · **Speech 0** · Note 7 |
| loudness / music bed | -16.8 LUFS / -30.0 dBFS | -16.4 / -16.1 | -20.7 / -24.5 | **-25.8 / -34.9** |
| worked | 45.0 min | 17.5 min | — | — |
| input / output tokens | 300 / 179,235 | 5,304,308 / 18,489 | — | — |
| cache read | 24,615,608 | 5,027,840 | — | — |

**One row explains the ranking.** How much of the 63-second take survived —
38.2s, 28.7s, 10.2s, 6.0s — falls in exactly the viewer's order. The material
was chosen because it contained a continuous performance, and what separated
four drivers was whether they let it be one.

Model names are read from each driver's own session log where one exists. Two of
the three self-reported a name that did not match: `gpt-5` for a session its own
log records as `gpt-5.6-terra`, and `Gemini 2.5 Flash` for what the operator knew
to be 3.7 Flash. The `--model` flag is a claim; the log is not.

**Round A, for the record:** all three shippable at 50.43s / 55.50s / 50.47s;
37.8 min · 324 in · 164,065 out · 29.9M cache-read for Claude, against 19.6 min ·
7,347,317 in · 29,222 out · 7.2M cache-read for gpt-5.6-terra.

### Before quoting any token number

**Two of three, not three.** Antigravity stores conversations as protobuf blobs
with no reachable token field. Its `/usage` and `/credits` panels report
remaining quota and the context panel reports what is currently loaded — three
different quantities, none of them consumption. The column stays blank rather
than being filled with the nearest available number.

**The two that exist count different things.** Claude reports `input_tokens`
*excluding* cache; Codex's appears to *include* it. Putting 300 and 5,304,308 in
one column and calling one small is a mistake the layout invites.

**Tokens are not money.** Cached reads, fresh input, output and reasoning all
price differently, per vendor and per plan.

---

## One viewer's verdict, and the reversal

Round A: Claude Opus 5, then gpt-5.6-terra, then Gemini Flash.
Round B: **Gemini Flash (90–95), then Claude Opus 5 (80), then gpt-5.6-terra.**

The same viewer, a day apart, on the same three drivers. Recorded as judgement,
not measurement — and the reversal is the most useful thing on this page, because
it is what a single run per driver is worth.

What he described, and what the numbers say about it:

**Gemini Flash — 「沒有任何問題，節奏、B-roll、字幕都很棒」.** It kept the
63-second take in **three pieces totalling 38.2s** and captioned it with 13
verbatim lines. It let the talking be the video. Its one fault was a cover whose
picture is rotated 90° — see below.

**gpt-5.6-terra — 「很差」.** Its hook is the Strava stats screenshot with a
caption drawn *on top of the numbers already printed on it*: two texts, one
place. It wrote **zero** `Speech` captions, so a person talking for half the
runtime is uncaptioned. It ends abruptly with speech still audible under the cut.

**Claude Opus 5 — 「很不順、跳，口播被截掉很多」.** 26 segments in 46.67s, 0.56
cuts per second — roughly twice the other two — and it cut the 63-second take
into **eleven fragments keeping 10.2 of 63.6 seconds**. Its shortest shot is
0.20s, six frames. `review.py`'s contact sheet shows the mechanism plainly:
through the middle of the video the speech captions run continuously while the
picture keeps cutting away from the person speaking.

**gpt-5.6-sol — 「完整性欠佳…突然就結束了」, and 「音樂都快聽不到了」.** It used
**6.0 seconds** of the 63-second take, the least of the four, wrote zero `Speech`
captions, and delivered at -25.8 LUFS with the bed at -34.9 dBFS — 5 to 9 LUFS
quieter than every other build. Every audio gate passed it. Two explanations
were measured and both were wrong: the bed is not buried (it leads the programme
by +5.2 dB), and it is not a broken declaration (all four declared `loudness:
original`, which is the rule that protects a vlog's recorded level). The whole
file is simply quiet, and `original` covers the footage's level while the bed's
level is a choice the build makes that nothing measured. Printed by `review.py`
now, not gated — across five builds the beds land at -16.1, -18.5, -24.5, -30.0
and -34.9 dBFS and the -30.0 one drew no complaint, so there is no line in that
spread to draw.

### Round A's verdict, at the same resolution

Compressing round A to one line while quoting round B in detail would leave a
reader thinking one driver is simply the worst, and across two runs none of them
is. Every driver shipped at least one clear defect, and each one got past all 17
gates:

**Claude Opus 5 — 「成品完美，沒有任何問題」.** The only build across both rounds
that drew no complaint.

**gpt-5.6-terra — ranked second.** Its closing card held **4.85s frozen**, 9% of
the runtime motionless, and its caption read 「雨中開跑」 over a photo taken
*after* finishing.

**Gemini Flash — ranked third, 「不知所云…完全沒有任何文字」.** It authored no end
card at all: `endcard.png` was a still grabbed from its own final clip, which is
the defect that produced `endcard_meta.json`.

Round A: Claude, gpt-5.6-terra, Gemini Flash.
Round B: Gemini Flash, Claude, gpt-5.6-terra.

Two of the three moved two places in a day. On this evidence the honest summary
is that all three clear the floor, all three produce faults a person has to
catch, and which one is "better" is not something two runs can answer.

### Across all three runs

The viewer's own summary, after the fourth driver landed and after revisiting
round B:

| | round 0 (contaminated) | round A | round B |
|---|---|---|---|
| Claude Opus 5 | 1st | 1st, 「完美」 | 2nd, **87–90** |
| Gemini 3.7 Flash | 2nd | 3rd | 1st, **95** |
| gpt-5.6-terra | 3rd | 2nd | 4th |
| gpt-5.6-sol | — | — | 3rd |

> 「三輪平均下來，Claude Opus 5 都還是算品質最穩定的一個 model。接下來我可能就會
> 選 Anti-Gravity 加上 Gemini 3.7 Flash。」

Those two sentences look like they disagree and they do not, which is the most
useful thing on this page. **Consistency and ceiling are different properties,
and an operator picks on a third one.** Claude placed 1st, 1st, 2nd and drew a
complaint only once; Gemini placed 2nd, 3rd, 1st and produced both the best
single edit here and, a round earlier, the one that shipped no ending at all.
The choice between them is not settled by a ranking, and nothing in this run
tells you which property matters more for your own footage.

### It was not cross-contamination, and it was not the gates

Both were checked rather than assumed.

**Not contamination.** The Claude session rendered 23:01–23:47 and wrote its
deliverables at 23:45. It first read another slot's directory at **00:19** —
thirty-four minutes after it had finished. Each driver worked in its own staged
folder.

**Not the gates.** Its build log records **26 segments from attempt #1**. The
gates rejected its cover and one caption that drifted 1.07s; they never pushed it
toward a shorter cut. That edit was chosen up front.

So the answer is the uninteresting one: this is judgement, the repo leaves
judgement free on purpose, and on this folder it went badly. `n=1`.

---

## Why there is no shot-length gate

The obvious response to "0.20s shots and 0.56 cuts/s" is a floor, and `plan.py`
already carries a measured band (`beat: 1.8–3.2s`) from a reviewed edit. It
looked like the `min_dwell_s` precedent exactly: advice in `plan.py` that nothing
enforced, until a 0.75s caption shipped and it became a gate.

The distribution killed it:

| | segments | below 1.8s | shortest |
|---|---|---|---|
| Claude Opus 5 | 26 | 11 | 0.20s |
| gpt-5.6-terra | 15 | 4 | 1.50s |
| Gemini Flash | 14 | **6** | 1.50s |

**All three go below the band, and the edit scored 90–95 has six such shots.** A
1.8s floor would have blocked the best video in the run. The dwell precedent does
not transfer either: a caption under 1.8s is unreadable, which is a fact about
people; a 0.2s shot is a style, which is not.

What actually separated them — one continuous performance cut into eleven pieces
— is not a defect in general. Cutting inside a take is ordinary editing. It was
wrong *here* because the take was the content, and no threshold knows that.

So it is printed instead of judged: `review.py` reports pieces-and-seconds per
source clip, and a person decides.

---

## What the gates could not see, and what changed

**`timeline.json` was an undeclared contract.** One driver wrote each segment's
origin under `source` where `gates.py` and `coverage.py` read `file`. A renamed
key empties the set it feeds, so `gate_clearance` triaged an *empty list* and
passed on 17 segments whose names it had never seen. → **`gate_timeline`**, the
seventeenth gate; and `gate_clearance` no longer treats "I found nothing to
check" as "there was nothing to check".

**An end card could be a screenshot of your own last shot.** The gate asked
whether `endcard.png` exists and whether the last frame matches it; a still
grabbed from the final clip answers both at 0.99, because it *is* that frame. →
**`modules/endcard.py` + `endcard_meta.json`**: the text on the card is declared,
and a card declaring nothing fails.

**Nobody ever looked at the finished video.** Nine builds, and `edit-critic` was
invoked zero times — it appears in those sessions only because SKILL.md's table
is in their context. Every defect a viewer found in round B was invisible to all
17 gates. → **`review.py`**: one command, any driver, producing a contact sheet
of frame 1, every caption moment and the last frame, plus the shape of the cut.
It grades nothing and never fails.

**A hook can exist without working**, and a cover can be the right shape with the
picture on its side. Neither is gated. The first has no reproducible threshold;
the second is a rotation bug `cover.build()` could plausibly catch from its
source aspect, and is the open item on this page.

### The pattern underneath all of them

Every hole had one shape: **"the file exists" is not the same question as
"somebody wrote it"**, and only the first was being asked. That is now the third
rule for adding a gate in `CONTRIBUTING.md` — *no gate a null result can satisfy*
— and it is worth more than either run's result.

---

## What a real quantitative comparison would still need

- **repeats.** One run per driver per folder is a single sample of a stochastic
  system, and round B reversed round A's order.
- **more folders.** Two down: food, conference, and a single long talking-head
  take through `postprod.py` — which writes no `timeline.json` at all, and so is
  untouched by the seventeenth gate.
- **a rubric, and more than one judge.**
- **comparable cost.** Every driver reporting fresh input, cached input, output
  and reasoning separately, plus a price list. Two of three can do the first half
  today.
