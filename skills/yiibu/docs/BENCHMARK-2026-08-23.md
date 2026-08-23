# Three drivers, one folder — 2026-08-23

The rerun, and the only benchmark page this repo keeps. The first attempt, a day
earlier, could not be quoted:

Its source folder had a previous edit of the same footage sitting beside the raw
clips — four finished videos, the cover, the music, and `project_config.py`,
that edit's whole configuration. One driver read it, and the reuse was string
for string:

| in the leaked `project_config.py` | in that driver's edit |
|---|---|
| `ENDING_CAPTION = "WHAT A GREAT DAY"` | closing caption `WHAT A GREAT DAY`, verbatim |
| `TOP_TITLE = "沒想到是VISOGE水上樂園"` | hook `說好的路跑／變成水上樂園？` |
| `MUSIC_SOURCE = music_src.mp3` | that exact file, deliverable named after it |

It was ranked second and was about to be quoted as evidence that a cheaper model
gets you there too. The failure was the harness's, not the model's — an agent
handed a folder is supposed to read the folder — and `bench.py` exists because
of it. Nothing recorded what any of that round cost, either; that is why
`finish` reads the driver's own log instead of asking anyone to type a number.

## What this page is for

Two things, and neither of them is a scoreboard.

**It is evidence for a claim this repo makes and had never tested.** `AGENTS.md`
says a different driver running the same commands reaches the same standard.
Three drivers, three independently written build scripts, one prompt, one clean
folder — and all three reached a green board on 17 blocking gates. That part is
reproducible and it is the point.

**It is a defect log.** Three holes in the gates turned up, each found by a
person watching a video that had passed everything. Two are now closed. The
third is deliberately left open, and the reasoning for that is the most useful
paragraph here.

What it is **not** is a ranking of models. One run each, one viewer, and cost
data for two of the three in units that do not mean the same thing. The numbers
below are laid out so you can see exactly that.

---

## The setup

| | |
|---|---|
| footage | 28 files, one rained-on evening road race, staged by `bench.py` — footage only, nothing else in the folder |
| input | a separate copy per driver, so none could see another's work |
| music | the same track in every `<agent>/music/`, never in `source/` |
| prompt | one `PROMPT.md` per agent, paths pre-filled, no editing by hand |
| brief | 45–60s vertical recap; shot choice, order, captions, pacing all left to the driver |
| bar | 17 blocking gates, identical for all three |

---

## What the run establishes

**All three reached `exit 0`. None reached it on the first render. The three
edits are nothing alike** — different hooks, different lengths, different
caption voices, different endings.

> Quality lives in the executable checks, never in the agent driving them.

That sentence has been in this repo since the beginning as an assertion. This is
the first time it has been run as an experiment.

---

## Measured

From each run's `build_log.jsonl` and `notes.json` — written by the machine, not
typed by anyone.

| | Claude Opus 5 | gpt-5.6-terra | Gemini 3.7 Flash |
|---|---|---|---|
| verdict | shippable | shippable | shippable |
| gates run | 17 | 17 | 17 |
| renders rejected first | 2 | 2 | 1 |
| rejected by | AudioPolicy, Duck | Delivery, Structure | Cover, Duck, MusicBed |
| finished length | 50.43s | 55.50s | 50.47s |
| segments | 23 | 21 | 22 |
| worked | 37.8 min | 19.6 min | — |
| input tokens | 324 | 7,347,317 | — |
| output tokens | 164,065 | 29,222 | — |
| cache read | 29,927,294 | 7,155,200 | — |
| cache write | 572,944 | 0 | — |

**None of the three wrote a single verbatim caption.** All used authored styles
only, and that is not three drivers happening to agree — it is a measurable
property of the audio. An ASR pass left behind by one of the runs covers all 27
clips: 14 produced any text at all, 63 words in total, **median word confidence
0.38, with 56% of words under 0.5**. What it produced reads like
「才告訴各位要好發明有信任性」 (0.53), 「快走」 (0.04), 「好」 (0.02). Rain, a PA
stack, several thousand people.

A `Speech` line is a claim that the words under it were said. None of the three
made that claim on a transcript this weak, which is `AGENTS.md` §4 holding
without anyone enforcing it. It also means this run exercised none of the ASR
path — `proofread.py`, `gate_sync`, the prompt-echo guard — and a folder where
somebody talks to camera is the obvious next test.
(Evidence: `yiibu-benchmark-2/asr_probe_transcripts.json`.)

---

## Read this before quoting the token numbers

**They are not a cost comparison, and they are not even the same measurement.**

**Two of three, not three.** Antigravity stores its conversations as protobuf
blobs with no reachable token field. Its `/usage` and `/credits` panels report
remaining quota, and the context-usage panel reports what is currently loaded —
three different quantities, none of them "what this run consumed". The column is
blank rather than filled with the nearest available number.

**The two that exist count different things.** Claude reports `input_tokens`
*excluding* cache; its 324 is fresh input, with 29.9M read from cache
separately. Codex's 7,347,317 appears to *include* its 7,155,200 cached, which
would put fresh input around 192,117 — inferred from the shape of its per-turn
records, not from a published spec. Putting 324 and 7,347,317 in the same column
and calling one small is a mistake the layout invites and the reader should
refuse.

**Tokens are not money.** Cached reads price differently from fresh input,
output prices differently again, reasoning tokens differently again, and the
rates differ per vendor and per plan. Converting any of this to a cost needs a
price list this page does not have.

So: here is what each driver's own log says it did. Anyone who wants a cost
comparison has to bring pricing and a lot more runs.

---

## The slot names and the models are not the same thing

The staged directories were named before anyone knew which tool would drive
which, and it came out crossed:

| directory | actually driven by |
|---|---|
| `claude-opus/` | Claude Opus 5 (Claude Code) |
| `gemini-flash/` | **gpt-5.6-terra** (Codex) |
| `terra/` | **Gemini 3.7 Flash** (Antigravity) |

They are deliberately **not** renamed. The driver logs that made the attribution
possible refer to those paths, and one slot was run twice by two different tools
— renaming would destroy the only evidence that separates the run whose output
survived from the run whose log is readable. `bench.py report` labels every row
by the model recorded in `notes.json`, never by the folder.

This nearly reversed the conclusion: a verdict given by folder name, checked
against timings recorded by tool, disagreed with itself for one round of
messages. The mapping above is the fix, and the general lesson is that a slot is
a slot and the model has to be recorded separately.

---

## One viewer's verdict

Recorded as what it is: **one person, on 2026-08-23, after watching all three.**
Not a measurement, no rubric, no second judge.

1. **Claude Opus 5** — no faults found.
2. **gpt-5.6-terra** — an ending that stalls: the closing card holds for 4.9s,
   ~9% of the runtime frozen, and its caption reads 「雨中開跑」 over a photo
   taken *after* finishing.
3. **Gemini 3.7 Flash** — "不知所云…完全沒有任何文字". No ending was authored at
   all; see below.

The order matches the previous round's, which is mildly reassuring and proves
nothing on its own: same viewer, same footage, n=1 either way.

---

## What the gates could not see

Three defects, all found by watching, all on videos with a full green board.

**1. `timeline.json` was an undeclared contract.** One driver wrote each
segment's origin under `source` where `gates.py` and `coverage.py` read `file`.
Nothing raised — a renamed key silently empties the set it feeds — so
`gate_clearance` triaged an *empty list* of source names and passed on 17
segments whose names it had never seen. **Closed:** `gate_timeline`, the
seventeenth gate, and `gate_clearance` no longer treats "I found nothing to
check" as "there was nothing to check".

**2. An end card could be a screenshot of your own last shot.** `gate_structure`
asked two questions and a still grabbed from the final clip answered both: the
file exists, and the last frame matches it — at 0.99, because it *is* that
frame. The video simply stopped on a shot of somebody holding snacks.

The tempting discriminator was measured and rejected: "a real card is a still,
so the tail should freeze" separates nothing here — the card *with* authored
text was held 0.1s, the screenshot 0.0s, and the one held longest (4.9s) carried
a caption contradicting its own photo. Freeze duration is a pacing choice, not
evidence of authorship. **Closed** by declaration instead: `modules/endcard.py`
writes `endcard_meta.json` recording the text drawn, and the gate fails when it
is missing or empty. Filling each build's in truthfully, the two that authored
an ending pass and the screenshot cannot, because there is nothing on it to
declare.

**3. A hook can exist and not work.** Both of the lower-ranked edits carried
exactly one `Hook`-styled caption starting inside the first second, which is all
`gate_structure` asks. One of them was 「雨裡的活動現場」 over 2.4 seconds of
unbroken motion-blurred handheld — a caption that *names the scene* rather than
opening a question. **Deliberately not closed.** There is no reproducible
threshold for "is this hook any good", and a gate without one gets tuned until
it passes, which is the failure it would exist to prevent.

---

## Does this contradict the claim it was run to test?

It reads like it might: the page opens by saying the standard held, then lists
three things that got through. It does not, and the distinction is worth being
exact about because it decides whether the sentence needs rewriting.

`SKILL.md` defines "the same standard" narrowly and on purpose — caption style,
audio targets, cover geometry, honest reporting of what is unfinished — and says
outright that cuts and rhythm are judgement and *should* differ. On that
definition all three drivers met it. What a viewer noticed as a quality gap was
mostly on the side the repo already declares free.

The end card is the exception, and it is not a counterexample either. That
requirement *looked* gated: `gate_structure` checked that `endcard.png` existed
and that the last frame matched it. A screenshot of the final clip satisfies
both. So the rule — the closing card is where the viewer learns what the thing
is called — was never encoded; only a proxy for it was, and the proxy accepted a
null. What remained in that spot was prose, and prose behaved exactly as this
repo's first line predicts prose behaves:

> Anything that depends on an agent remembering, noticing, or being clever is
> not a standard — it is a hope.

Two drivers authored a real ending by being careful. One did not. That is the
distribution you get from a hope, and getting it from three independent drivers
in one afternoon is better evidence for the sentence than for anything against
it.

So the sentence stands. What it was missing is the corollary this run earned,
now the third rule in `CONTRIBUTING.md`: **no gate a null result can satisfy.**
Ask what an empty or absent input does to a check before it ships. Three defects
in this repo have had that shape — a style-name allowlist, a renamed
`timeline.json` key, and this end card — and every one of them looked like a
working gate until somebody watched the video.

---

## The distinction that made those three tractable

It is easy to look at that list and conclude the gates need to judge taste. They
do not, and two of the three were not taste failures at all.

| | question | checkable? |
|---|---|---|
| 1 | **was the work done at all?** | yes — and this is where two of the three defects lived |
| 2 | is what was made consistent with the footage? | partly, by a person or `edit-critic`; not by a threshold |
| 3 | is it any good? | no, and this repo leaves it free on purpose |

The end card was not a bad ending. It was **no ending**, accepted as one because
"the file exists" and "somebody wrote it" are different questions and only the
first was being asked. Same shape as `layout.json` before it, and
`timeline.json` the day before that.

Tier 3 already has an answer here, and it is not a gate: `coverage.py` prints
and does not block, `edit-critic` argues, and the rule stands —

> All gates green does not mean the video is good. Say "it passes the gates",
> never "it is finished", until someone has watched it.

This round is that rule working. Seventeen gates green, then a person watched
three videos and found three things none of them could see.

---

## What a real quantitative comparison would need

This page cannot rank models, and the gap is not small:

- **repeats.** One run each is a single sample of a stochastic system. Same
  prompt, same folder, several runs per driver, before any difference means
  anything.
- **more than one folder.** One rained-on road race says nothing about a
  conference, a meal, or a talking head.
- **a rubric and more than one judge.** "No faults found" and "不知所云" are
  real reactions and not a scale.
- **comparable cost.** Every driver reporting fresh input, cached input, output
  and reasoning separately, plus a price list. Two of the three can do the first
  half today; one cannot do any of it.

Until then this page says one thing, and says it with evidence: the floor held
across three drivers, and three defects that a green board could not see were
found by watching.
