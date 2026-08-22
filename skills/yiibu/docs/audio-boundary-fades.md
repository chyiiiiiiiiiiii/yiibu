# Audio Cut Boundaries — Technical & Techniques Reference

Everything about how yiibu cuts audio without pops, why the old
approach was silently broken, and the ffmpeg/DSP techniques that make the fix
correct. Read this before touching `modules/silence_cut.py` or the cut path.

---

## 1. Why a cut pops (the physics)

Digital audio is a stream of samples. A "cut" removes a span and glues the
sample *after* the removed span directly onto the sample *before* it. If those
two samples sit at different instantaneous amplitudes, you get a **step
discontinuity**:

```
   …last kept sample        first sample after the gap
        │                        │
   ─────┘                        └──────      ← waveform
        ▲ instantaneous jump ────┘
```

A step in the time domain is broadband energy in the frequency domain — you
hear it as a **click / pop / tick**. It is loudest when both sides are audible
(voice mid-word, a tone mid-cycle). It is silent when at least one side is
silence (nothing to step from).

**The only robust cure is to ramp the amplitude to ~0 at the moment of the
join** — fade the tail of the outgoing segment down and the head of the
incoming segment up. With both sides at zero, there is no step. A 20–40 ms
ramp is inaudible as a fade but completely removes the click. We use 30 ms
(`SILENCE_CUT_CROSSFADE_MS = 50` is the ceiling; per-segment clamping keeps it
short on tiny segments).

---

## 2. The bug that was here

`run_silence_cut` makes cuts in **three** independent stages:

| Stage | Mechanism (old) | Boundary result |
|-------|-----------------|-----------------|
| Clap removal | ffmpeg `aselect='not(...)'` | hard splice |
| Silence removal | `auto-editor` render | hard splice |
| Manual cuts | ffmpeg `aselect='not(...)'` | hard splice |

The intended smoothing was a single "Step 5":

```python
"-af", f"highpass=f=20,afade=t=in:d={crossfade_s}"
```

`afade=t=in` **with no `st=` (start time)** fades in starting at `t=0` — it
ramps the **first 50 ms of the whole file** and nothing else. Every interior
join stayed a hard splice. The variable was named `SILENCE_CUT_CROSSFADE_MS`
and the comment claimed "smooth audio at cut boundaries", but the code was a
**no-op for every actual boundary**. Classic intent ≠ implementation — it ran
without error, so it survived.

---

## 3. The fix — architecture

Two ideas.

### 3a. One faded renderer for all three stages

`render_faded_cut(input, keep_ranges, output, fade_ms)` is now the single
primitive every stage renders through. Given the ranges to **keep** (not cut),
it:

1. extracts each kept range and re-encodes it with an `afade` on **both**
   edges, then
2. losslessly concatenates the segments (`-c copy`).

```
keep_ranges = [(0,1), (2,3)]

 seg0 [0..1]           seg1 [2..3]
 ┌───────────┐         ┌───────────┐
 │        ╲fade        fade╱     ╲fade      ← 30ms ramps at every edge
 └───────────┘         └───────────┘
         └── concat -c copy ──┘
                  ▼
        output: join at t=1.0 is fully faded
```

### 3b. auto-editor becomes a *detector*, not a *renderer*

auto-editor's own render hard-cuts. So we ask it only for its **decision** and
render it ourselves:

```
auto_editor clap_cleaned --margin 0.2s --export v1 --output ae_chunks.json
```

`--export v1` emits `chunks` = `[start_frame, end_frame, speed]`; `speed`
`1.0` = keep, `99999` = silence/cut. `chunks_to_keep_ranges()` turns those
into second-based keep-ranges, which go straight into `render_faded_cut`. Same
frames auto-editor would have kept — but now *we* own the encode, so we fade.

### Stage wiring (new)

```
clap zones ──invert_ranges──► keep ─┐
                                    ├─► render_faded_cut ─► faded splices
auto-editor v1 chunks ──────────────┤
                                    │
manual cuts ──invert_ranges─────────┘
```

`invert_ranges(cut_ranges, total)` = complement of the cut zones within
`[0,total]` (merges overlaps, drops zero-length keeps). It converts the two
"here's what to remove" stages (clap, manual) into the "here's what to keep"
form the renderer wants.

---

## 4. The ffmpeg techniques, in detail

### 4a. `afade` on both edges, clamped

```python
f = min(fade_s, dur / 2.0)               # never let two fades overlap
afade = (f"afade=t=in:st=0:d={f:.3f},"
         f"afade=t=out:st={dur - f:.3f}:d={f:.3f}")
```

- `st=` (start) is mandatory for the fade-out — that is exactly the field the
  old code omitted. Fade-out must start at `dur - f`, not `0`.
- **Clamping** `f` to `dur/2` matters: a 30 ms fade on a 40 ms segment would
  make the in- and out-ramps overlap and null the segment. On very short kept
  slivers the fade auto-shrinks.

### 4b. Per-segment extract → lossless concat (not one filtergraph)

Each kept range is a separate re-encode into an `.mkv` holding **h264 video +
PCM audio**, then joined with the concat demuxer — video copied through,
audio encoded to AAC exactly once:

```python
# per segment (parallel, see 4d):
ffmpeg -ss {start} -i input -t {dur} -af {afade} <video-codec> -c:a pcm_s16le seg_i.mkv
# then, once:
ffmpeg -f concat -safe 0 -i list.txt -c:v copy -c:a aac output.mp4
```

Why not a single `aselect`+`afade` filtergraph? Because `afade` in a filter
graph can't address "every interior join" — it has one start time. Per-segment
extraction gives every segment its own two edges to fade, and video is copied
(no generation loss, video-use Hard Rule #2).

- `-ss` **before** `-i` = fast input seeking; accurate here because we
  re-encode the segment (no dependence on the source GOP boundary).
- `-t {dur}` bounds the segment length.

### 4c. Why PCM segments, not AAC (the A/V-drift trap)

The obvious version encodes each segment to AAC and concats with `-c copy`.
That **accumulates A/V drift**: every AAC segment carries encoder
priming/padding (~0.93 ms here), so audio grows ~1 ms per segment relative to
video — ~37 ms (>1 frame of lip-sync) over 40 cuts.

Fix: segments carry **lossless PCM** (`pcm_s16le`, in `.mkv` since MP4 doesn't
hold PCM). PCM concat is sample-exact. The concat step then does
`-c:v copy -c:a aac`, decoding the now-*continuous* PCM across all segments and
encoding to AAC **once** → a single priming at t=0. Measured drift over 40
segments: **0.0 ms**. This is the practical reading of video-use Hard Rule #2
("lossless concat") — lossless means *PCM through the join*, not "AAC with
`-c copy`".

### 4d. Parallel segment encode

Segments are independent, so they encode concurrently on a
`ThreadPoolExecutor` (`min(len, cpu_count)` workers; each ffmpeg subprocess
releases the GIL, so threads give real parallelism). **Order is taken from the
job list (enumerate order), never completion order** — otherwise a fast late
segment could land early in the concat. Measured: 40-segment render
17.9 s → 6.1 s (2.9× on 8 cores).

### 4c. auto-editor `--export v1`

`v1` is the stable, tiny JSON contract (`{"version":"1","chunks":[[s,e,speed]]}`).
Frame-based, so convert with the clip's real fps (`_probe_fps`, parses the
`num/den` `r_frame_rate`). The cut sentinel is `99999`; we keep any chunk whose
speed is normal and positive.

---

## 5. The verification technique (`verify.py`)

A fix you can't observe on the artifact isn't done. `run_silence_cut` writes
`boundaries.json` (the interior join offsets in the output timeline, from
`keep_ranges_to_boundaries` = cumulative kept durations minus the last edge).
`check_cut_boundaries` then proves each was faded:

```
              ref = median RMS of the ±50–150 ms neighbourhood
   RMS │   ▁▂▃▄▅▆▇█        █▇▆▅▄▃▂▁
       │              ╲  ╱                 faded  →  center ≪ ref      PASS
       │               ╲╱   ← center = min RMS in ±20 ms
       └──────────────────────────────────────► t
                        ▲ boundary

   RMS │   ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇          hard cut → center ≈ ref     FLAG
```

- **Dip test:** `center < 0.4 × ref` ⇒ faded. Hard cut leaves `center ≈ ref`.
- **Silence guard:** if `ref < 0.01` the join is silence-adjacent — no pop is
  possible — skip it (avoids false positives).
- Runs on the **voice track** (`trimmed.mp4`), not the BGM mix: BGM is
  continuous and would mask the voice dip, hiding a real regression.

RMS is computed at 10 ms resolution by `extract_rms_values` (the same helper
clap detection already uses — no new DSP code).

---

## 6. Mapping to video-use "Hard Rules"

The public `browser-use/video-use` repo codifies the correctness rules this
fix now satisfies:

| video-use rule | Here |
|----------------|------|
| #2 per-segment extract → lossless `-c copy` concat | `render_faded_cut` |
| #3 30 ms audio fades at every segment boundary | `afade` in/out per segment |
| #7 verify your own output before shipping | `check_cut_boundaries` |
| (subtitles applied last) | already correct — `compose.py:297,456` |

---

## 7. Config knobs

- `SILENCE_CUT_CROSSFADE_MS` (config.py, default 50) — fade length ceiling in
  ms. Per-segment clamped to `dur/2`. Lower = tighter/punchier, higher =
  smoother but risks audibly ducking short words. 20–40 ms is the sweet spot
  for voice-over.
- auto-editor detection unchanged (`--margin 0.2s`): the fix changed *how we
  render* the decision, not *what gets cut*.

---

## 8. Known limitations / follow-ups

- **Severity by path (verified).** With `--margin 0.2s`, silence-removal joins
  sit *between retained silence margins* → the join is silence-to-silence and
  barely pops; `check_cut_boundaries` correctly skips these (silence guard).
  The audible pops this fix removes are on the **clap** and **manual** paths,
  where the join is audible-to-audible. The fade is applied on all three paths
  regardless — this note is about where it *mattered*.
- `boundaries.json` lists the **final cut stage's** joins. In the common case
  (no manual cuts) that is the full silence-removal set. When manual cuts run,
  only the manual joins are listed for verification; earlier silence joins are
  still faded (they go through the identical `render_faded_cut`, covered by
  unit tests) but aren't re-listed. Threading a fully-composed boundary list
  across stages is a possible follow-up if a manual-cut pop ever slips through.
- The dip test is deliberately lenient (`0.4 × ref`) to avoid false positives
  on natural low-energy moments; a genuinely tiny un-faded click on an
  otherwise loud bed could still pass. The unit tests on `render_faded_cut`
  are the primary guarantee; `check_cut_boundaries` is the artifact-level
  backstop.
- Pre-existing unrelated test breakage noted here at the time has since been
  cleared (2026-08-21): the `generate_karaoke_line` tests were replaced with
  tests for the renderer that actually ships, and
  `test_broll.py::test_align_broll_multiword_keyword` turned out to be failing
  on a real alignment bug rather than on staleness.

---

## 9. Test inventory

| Test | Proves |
|------|--------|
| `test_render_faded_cut_fades_internal_boundary` | boundary RMS < 25 % of mid-segment |
| `test_render_faded_cut_preserves_kept_duration` | output = Σ kept ranges |
| `test_invert_ranges_*` (4) | cut→keep complement, merge, edges, empty |
| `test_chunks_to_keep_ranges_v1` | auto-editor v1 parse |
| `test_keep_ranges_to_boundaries` | join offsets = cumulative durations |
| `test_render_faded_cut_no_av_drift_many_segments` | 40 segments, A/V drift < 10 ms |
| `test_render_faded_cut_preserves_segment_order` | output follows keep order (parallel-safe) |
| `test_run_silence_cut_fades_manual_cut_boundary` | end-to-end faded join at t=1.0 |
| `test_run_silence_cut_silence_path_glue_sync_format` | auto-editor path: glue + verify + sync + h264/30fps |
| `test_check_cut_boundaries_passes_when_faded` | verifier accepts a fade |
| `test_check_cut_boundaries_flags_unfaded_pop` | verifier catches a hard cut |
| `test_check_cut_boundaries_no_file_is_pass` | no-op when nothing to check |

Run: `python3 -m pytest tests/test_silence_cut.py tests/test_verify.py -q`
