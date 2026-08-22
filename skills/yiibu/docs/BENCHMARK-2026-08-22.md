# Three models, one folder — 2026-08-22

Three agents were given the same footage, the same skill and the same machine,
and told to make a 45–60s vertical recap. Nothing about the edit was specified:
each one chose its own shots, order, captions, music and length.

| driver | agent id | work dir |
|---|---|---|
| Claude Opus 5 (Claude Code) | `claude-opus` | `yiibu-benchmark-results/claude-opus/` |
| Gemini 3.7 Flash | `gemini-flash` | `yiibu-benchmark-results/gemini-flash/` |
| TeraGPT | `terra` | `yiibu-benchmark-results/terra/` |

Footage: 27 clips, 91.4s total, one evening road race that got rained on.

**Read the numbers in this page as three different kinds of claim.** What
`build_log.jsonl` wrote is measured; the ranking is one person's judgement after
watching; token cost and total wall-clock were never instrumented and are
therefore absent rather than estimated. Keeping those three apart is the whole
point of the build log, and it is easy to lose by writing a table.

---

## The result that matters

**All three reached `exit 0` on all 16 gates. None of them reached it on the
first render.**

That is this repo's own claim under test, and it is the reason to keep the page:
the standard survived three different models, and the *edits* did not resemble
each other at all. Different hooks, different lengths, different caption voices,
different music — same floor.

> Quality lives in the executable checks, never in the agent driving them.

---

## Measured

Straight out of each run's `build_log.jsonl`. The gate-run span is the wall
clock between the **first** and **last** gate invocation — the render-and-fix
phase only. It excludes everything before the first render (reading the folder,
choosing shots, writing the build script), which is where most of the thinking
happens, so do not read it as "how long the agent took".

| | claude-opus | gemini-flash | terra |
|---|---|---|---|
| final verdict | shippable | shippable | shippable |
| gate runs logged | 12 | 3 | 6 |
| renders rejected before green | 4 | 1 | 4 |
| gate-run span | 12.9 min | 3.4 min | 9.6 min |
| duration | 54.97s | 47.07s | 49.43s |
| segments | 23 | 21 | 17 |
| source clips credited | 23 | 21 | 1 |
| delivered size | 90.1 MiB | 75.0 MiB | 80.4 MiB |
| caption events | 14 | 13 | 10 |
| caption styles used | Hook + Note | Hook + Note | Hook + Note |
| verbatim (`Speech`) lines | 0 | 0 | 0 |

Two rows deserve a sentence rather than a number.

**"source clips credited: 1"** is not an edit that used one clip. `terra`'s
`timeline.json` names each segment's origin under the key `source`; `gates.py`
and `coverage.py` read `file`. See the findings below — this is a defect, and
every gate was green while it was true.

**No `Speech` lines anywhere.** All three independently decided this footage
cannot carry verbatim captions — rain, a PA stack and several thousand people —
and put everything in authored styles. That is the rule working: a `Speech` line
is a claim that the words under it were said, and none of the three claimed it.

---

## What each render was rejected for

| gate | claude-opus | gemini-flash | terra |
|---|---|---|---|
| Duck | 2.3 dB | 3.6 dB | 2.6 dB |
| MusicBed (silent head) | at 2.0s | — | at 1.5 / 3.5 / 15.0s |
| Captions (overflow) | — | 3 lines | 1 line |
| Cover / CoverColour / Pill | ✓ | — | — |
| Audio (dead air) | — | — | 1.00s, 1.75s |
| Clearance | — | — | bare value, no `why` |

Read the first two rows across, not down.

**`gate_duck` rejected 3 of 3 first renders**, at 2.3, 2.6 and 3.6 dB against a
4.0 dB house minimum. Three independent agents, three different build scripts,
the same failure. That is not three mistakes; that is a default that does not
clear its own gate on this kind of material.

**`gate_captions` overflow hit 2 of 3.** Both were CJK lines past the safe area
— `說好的路跑怎麼變成水上樂園？` measured 1456px against a 960px limit. The check
is callable while captions are being generated, which turns a ship-time
rejection into an authoring-time error; one of the three runs did that, and it
is the one that never saw the failure.

---

## What the gates could not see

The gates are blind to truth and omission by construction, so this is the part
that needed a person. Two things a reviewer should know before drawing
conclusions from the ranking:

**Caption voice diverged far more than anything the gates measure.** The same
footage produced `跑一跑，雨小了` (descriptive), `雨越下越大大家越跑越嗨`
(an intensity claim plus a stance) and `每一步，都在往前。` (neither — poetic,
and true of any run ever filmed). All three passed every caption gate. Choosing
between them is editorial judgement and no threshold will ever make it.

**`terra` shipped a library stand-in named `visoge-recap.mp4`.** The track is
`bgm-library/energetic/mixkit-techno-117.mp3` — nobody asked for it, so it is
rung 4 of the resolve ladder and the house rule names the deliverable
`NAME-standin-<mood>.mp4`. A user cannot hear the difference in a filename and
will publish it. This is precisely the failure the naming rule exists to stop,
and no gate enforces it.

---

## Quality ranking

Recorded as what it is: **one viewer's judgement, on 2026-08-22, after watching
all three.** Not a measurement, and not reproducible from anything in this repo.

1. Claude Opus 5
2. Gemini 3.7 Flash — rated close to first
3. TeraGPT

The practical reading the viewer drew: if the cheapest driver that still clears
the bar is what you want, Gemini 3.7 Flash produced a publishable short.

### The ranking is not safe to quote, and the reason is a harness leak

The shared source folder was contaminated before any agent started: a previous
edit of this same footage had been copied in alongside the raw clips — four
finished videos, its cover art, its music file, and **`project_config.py`, that
edit's entire configuration**.

`gemini-flash` reused it. Not inferred from resemblance — the strings match:

| in the leaked `project_config.py` | in the `gemini-flash` edit |
|---|---|
| `ENDING_CAPTION = "WHAT A GREAT DAY"` | closing caption `WHAT A GREAT DAY`, verbatim |
| `TOP_TITLE = "沒想到是VISOGE水上樂園"` | hook `說好的路跑／變成水上樂園？` |
| `MUSIC_SOURCE = music_src.mp3  # Dina Ayada - problems` | that exact file; deliverable named `-problems` |

Neither string appears in the `terra` edit, and the `claude-opus` run was built
from an isolated copy containing only the 28 raw clips.

So the second-place edit did not independently arrive at its hook, its closing
line or its music: it read decisions a person had already made on this footage.
**That is the confound, and it lands exactly on the conclusion the ranking was
being used to support** — "a cheaper model gets you there too". It may well be
true. This run cannot be the evidence for it.

The failure is the harness's, not the model's. An agent handed a folder is
supposed to read the folder. Nothing told it that half of what was in there was
the answer key.

---

## Status of this page

This run stands as evidence for exactly one thing: **three different drivers
reached a green board on the same footage, and none did it first try.** That
part does not depend on the contaminated folder — it is about the checks, and
the checks ran identically for all three.

It is **not** evidence about which model is better, and it should not be quoted
that way. Two things have to be fixed before it can be:

1. a clean source folder, containing only footage
2. an instrumented harness, so cost is measured rather than absent

A rerun should also cover all three arms, not just the contaminated one: the
suite itself changed as a result of this benchmark (see the findings), and
`terra`'s build no longer passes it.

---

## Not captured

**Token cost and total wall-clock time were not instrumented for any of the
three.** They are absent from this page rather than estimated, because a guessed
number in a comparison table is indistinguishable from a measured one a week
later.

A build script cannot observe either — that is why `WORK_DIR/notes.json` exists
and why `gates.py` copies it into the log under `self_reported`, labelled. The
mechanism was already there and went unused by all three, because SKILL.md said
to write the file *if you want the numbers kept*. An optional step is a skipped
step; that is the oldest lesson in this repo and it still caught it.

Two things changed as a result. SKILL.md now says to write `notes.json` at the
end of every run, and BUILD_LOG.md prints the **Self-reported** heading even
when the file is absent — so an unrecorded run reads as a hole rather than as a
run with nothing to report. Neither is a gate: what a run cost has no bearing on
whether the video is shippable, and a gate that blocks a good video over a
missing token count would deserve to be ignored.

---

## What this benchmark says the repo should change

The page is worth more as a list of defects than as a scoreboard.

1. **`buildkit.duck_mix`'s default depth does not clear `gate_duck`.** 3 of 3
   first renders failed it on event material. Either the default moves, or the
   gate's own message should name the default as the likely cause.

2. **`timeline.json` was an undeclared contract.** — **fixed, `gate_timeline`.**
   `terra` wrote `source` where `gates.py` and `coverage.py` read `file`;
   `sources_used` reported 1 of 17, the coverage table collapsed to a single `—`
   bucket, and `gate_clearance` — whose entire job is to refuse footage that
   looks like session material with no recorded publication answer — triaged an
   **empty list** and returned PASS on 17 segments whose names it had never
   seen. Every other node contract in this skill is a declared artifact a gate
   can read; this one was a shape three agents each guessed at, and one guessed
   differently. It is now the seventeenth gate, and `gate_clearance` no longer
   treats "I found nothing to check" as "there was nothing to check". Verified
   against all three runs: `terra` fails with the near-miss key named in the
   message, the other two still pass.

3. **The stand-in naming rule has no gate.** See `terra` above. It is a filename
   check against `decisions.json` and the resolve rung, and it is the difference
   between a user publishing a placeholder and knowing they have one.

4. **Caption overflow is an authoring-time error being found at ship time.**
   2 of 3 hit it. Generating and validating captions in the same act is already
   the documented pattern; nothing makes it the default.
