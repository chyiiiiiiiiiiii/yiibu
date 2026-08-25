#!/usr/bin/env python3
"""Blocking gates. Every check here exists because the defect SHIPPED.

These are separate from verify.py's advisory checks in one important way:
a missing artifact is a FAILURE, not a skip. The silent ending and the missing
cover both got through because the old runner treated "file not found" as
"not applicable" and printed a WARN nobody blocked on.

The rule these encode, which is the actual lesson from the 11-version edit:

    Do not reason about whether a measurement is acceptable.
    A number outside the threshold is a failure, even when you can explain it.

The silent ending shipped TWICE. Both times the level was measured, seen, and
explained away ("that's the song's own outro", "that's the tail fade").

Usage:
    python3 gates.py OUTPUT.mp4 [--work-dir DIR] [--json]
Exit code 1 on any failure.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Scratch frames are per-process so two concurrent gate runs cannot corrupt
# each other's reads (a fixed /tmp name was also POSIX-only).
_SCRATCH = os.path.join(tempfile.gettempdir(), f"_g_{os.getpid()}")


def _scratch(name):
    return f"{_SCRATCH}_{name}"

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, os.path.join(SKILL_DIR, "modules"))

# ── thresholds ───────────────────────────────────────────────
PEAK_MAX = 0.95
DEAD_DBFS = -45.0
DEAD_MAX_S = 0.8
ENDING_S = 3.0
ENDING_MIN_DBFS = -32.0
SYNC_TOL = 0.15

FRAME_W, FRAME_H = 1080, 1920
SAFE_MARGIN_X = 60          # captions must stay inside this
# Layout anchors. Every text style used in the .ass must be DECLARED against one
# of these in the work dir's layout.json, e.g. {"Speech": "caption", "Hook": "free"}.
# A name allowlist was tried first and is not safe: it silently passed any style
# someone named differently, which is the whole class of bug this gate exists for.
# "free" is allowed but has to be written down — an explicit decision, not a gap.
ANCHORS = {"caption": 0.70, "pill": 0.18}
CAPTION_BASELINE = 0.70     # fraction of height
CAPTION_BASELINE_TOL = 0.06
PILL_CENTRE = 0.18          # mirrors house_style.json pill.centre_pct
PILL_TOL = 0.05
PILL_MAX_W_RATIO = 0.85
COVER_FIRST_FRAME_SIM = 0.90
# Two captions closer than this vertically are in the same place on screen; a
# two-layer design's nearest simultaneous anchors sit 210px apart, so 100 is
# clear of every legitimate stack the skill ships.
CAPTION_SAME_ANCHOR_PX = 100
# A frame of overlap at a hard cut is a rounding artefact, not a collision.
CAPTION_OVERLAP_TOL_S = 0.05

def house(work_dir=None):
    """The machine-checked house style, plus any written-down project override.

    Prose in SKILL.md cannot stop the next agent re-deriving the look. This can.
    """
    spec = json.load(open(os.path.join(SKILL_DIR, "house_style.json"), encoding="utf-8"))
    local = os.path.join(work_dir or ".", "house_style.local.json")
    if os.path.exists(local):
        for k, v in json.load(open(local, encoding="utf-8")).items():
            if isinstance(v, dict) and isinstance(spec.get(k), dict):
                spec[k] = {**spec[k], **v}
            else:
                spec[k] = v
        spec["_overrides"] = sorted(json.load(open(local, encoding="utf-8")).keys())
    return spec


def _dialogues(work_dir):
    """(style, text) for every Dialogue line, plus the raw .ass path."""
    ass = None
    for n in ("captions.ass", "subtitles.ass"):
        p = os.path.join(work_dir or ".", n)
        if os.path.exists(p):
            ass = p
            break
    if not ass:
        return None, []
    rows = []
    for line in open(ass, encoding="utf-8").read().splitlines():
        if line.startswith("Dialogue:"):
            p = line.split(",", 9)
            rows.append({"start": _ass_secs(p[1]), "end": _ass_secs(p[2]),
                         "style": p[3].strip(), "text": p[9]})
    return ass, rows


def _ass_secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _font_file():
    """Resolve the caption font through the skill's own chain (bundled first).

    gates.py used to keep a second, hand-written list that put a personal
    ~/Library/Fonts path ahead of the bundled asset — fine on one machine,
    broken on anyone else's. One resolver, one answer.
    """
    from title import _find_font
    try:
        return _find_font()
    except Exception:                                        # noqa: BLE001
        return None


def _decode(path):
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
         "-ar", "48000", "-"], stdin=subprocess.DEVNULL, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32), 48000


def _dbfs(x):
    import numpy as np
    return 20 * np.log10(max(float(x), 1e-9))


# ── G1: audio must never go dead, least of all at the end ────

def gate_audio(video, work_dir=None):
    import numpy as np
    a, sr = _decode(video)
    fails, det = [], {}
    if not len(a):
        return ["no audio stream"], det

    peak = float(np.abs(a).max())
    over = int((np.abs(a) > 1.0).sum())
    det["decoded_peak"] = round(peak, 4)
    det["over_full_scale"] = over
    if peak > PEAK_MAX or over:
        fails.append(f"clipping: peak {peak:.3f} (max {PEAK_MAX}), {over} samples over")

    w = sr // 4
    k = len(a) // w
    lv = np.array([_dbfs(np.sqrt((a[i * w:(i + 1) * w] ** 2).mean())) for i in range(k)])
    quiet = lv < DEAD_DBFS
    run = best = best_at = 0
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run > best:
            best, best_at = run, i - run + 1
    # A DECLARED muted stretch is not dead air. This gate exists to catch a bed
    # that ran out or a fade inherited from an older cut — accidents. A segment
    # whose audio_policy.json row says "the music takes this stretch" is the
    # opposite of an accident, and it only ever applies to the no-music sibling:
    # the music version still has to carry the bed there, which gate_music_bed
    # and this gate's own check on that file both enforce.
    nomusic = bool(re.search(r"-nomusic\.\w+$", os.path.basename(video)))
    exempt = muted_spans(work_dir) if nomusic else []
    det["longest_silence_s"] = round(best * 0.25, 2)
    det["silence_at_s"] = round(best_at * 0.25, 1)
    if exempt:
        det["declared_mute_spans"] = len(exempt)
        # re-measure, ignoring windows that sit inside a declared muted span
        inside = np.zeros(k, bool)
        for lo, hi in exempt:
            inside[max(int(lo / 0.25), 0):min(int(hi / 0.25) + 1, k)] = True
        run = best = best_at = 0
        for i, q in enumerate(quiet & ~inside):
            run = run + 1 if q else 0
            if run > best:
                best, best_at = run, i - run + 1
        det["longest_undeclared_silence_s"] = round(best * 0.25, 2)
    if best * 0.25 > DEAD_MAX_S:
        fails.append(f"dead air: {best*0.25:.2f}s of silence at {best_at*0.25:.1f}s "
                     f"(max {DEAD_MAX_S}s) — a music bed that ran out, or a tail "
                     f"fade longer than the closing shot"
                     + (" (declared muted spans were already excluded)"
                        if exempt else ""))

    tail = a[-int(ENDING_S * sr):]
    tdb = _dbfs(np.sqrt((tail ** 2).mean()))
    det["ending_dbfs"] = round(tdb, 1)
    pol = audio_policy(work_dir)
    ends_muted = bool(pol and pol.get("segments")
                      and not pol["segments"][-1].get("keep"))
    if nomusic and ends_muted:
        det["ending"] = ("closing segment is declared music-only; the ending is "
                         "checked on the music version")
    elif tdb < ENDING_MIN_DBFS:
        fails.append(f"silent ending: last {ENDING_S}s at {tdb:.1f} dBFS "
                     f"(min {ENDING_MIN_DBFS}) — the closing card is the payoff shot")
    return fails, det


def gate_audio_policy(video, work_dir):
    """Every segment declared an audio intent, and the render obeyed it.

    The defect this exists for: a 48-second food 花絮 in which nobody speaks
    shipped with the room's audio running under all of it, because "the ambience
    IS the food-video soundtrack" was applied to every shot instead of to the
    shots whose sound is worth hearing. Twelve gates were green. The user heard
    it in one pass — "音樂反而變得很小聲，但實際上影片裡根本沒有人在說話".

    Two halves, and only the second is a threshold:

      * COMPLETENESS. With audio_policy 'selective', audio_policy.json must
        cover every segment in timeline.json, each with an explicit keep value
        (a reason string, or null for music-only) and a why. Same principle as
        decisions.json: the machine never decides what a shot's audio is FOR,
        it only refuses to let the question go unanswered.

      * APPLICATION. Measured on the finished no-music file, the muted spans
        must sit at least house audio_policy.min_applied_db below the kept ones.
        This is the part a machine CAN check — that the declaration and the
        audio agree — and it catches the build that writes the policy and then
        renders without it.

    What a segment's audio is for is never checked, because it cannot be:
    modules/audio_scout.py scores every segment of a full restaurant as
    "voiced", correctly, because other diners are talking. Evidence, not verdict.
    """
    import numpy as np
    fails, det = [], {}
    declared = _decision(work_dir, "audio_policy")
    det["audio_policy"] = declared
    if declared != "selective":
        det["note"] = "original audio under the whole video (audio_policy: full)"
        return fails, det

    pol = audio_policy(work_dir)
    if not pol:
        return ["audio_policy is 'selective' but there is no audio_policy.json — "
                "the per-segment calls have to be written down, not held in "
                "someone's head"], det

    tl_p = os.path.join(work_dir or ".", "timeline.json")
    if os.path.exists(tl_p):
        want = [s["id"] for s in json.load(open(tl_p))["segments"]]
        got = [r.get("id") for r in pol.get("segments", [])]
        det["segments_declared"] = f"{len(got)}/{len(want)}"
        missing = [i for i in want if i not in got]
        extra = [i for i in got if i not in want]
        if missing:
            fails.append(f"no audio call for segment(s) {', '.join(missing[:6])}"
                         f"{'...' if len(missing) > 6 else ''} — every segment "
                         f"declares what its audio is for, or the question was "
                         f"never asked")
        if extra:
            fails.append(f"audio_policy.json names segment(s) not in the "
                         f"timeline: {', '.join(extra[:6])}")
    no_why = [r.get("id") for r in pol.get("segments", []) if not r.get("why")]
    if no_why:
        fails.append(f"no reason recorded for {', '.join(no_why[:6])} — a keep/mute "
                     f"call with no why is one nobody can review or reverse")

    kept = [r for r in pol.get("segments", []) if r.get("keep")]
    det["kept"] = f"{len(kept)}/{len(pol.get('segments', []))}"
    det["kept_kinds"] = ",".join(sorted({str(r["keep"]) for r in kept})) or "none"
    if not kept:
        fails.append("every segment is muted — that is not an audio policy, that "
                     "is a silent film; keep the shots whose sound is the payload")

    # Application, measured on the honest file. The music version cannot answer
    # this: the bed is loudest exactly where the ambience was taken away.
    base = os.path.basename(video)
    sib = video if re.search(r"-nomusic\.\w+$", base) else None
    if not sib:
        d = os.path.dirname(os.path.abspath(video))
        c = [os.path.join(d, f) for f in sorted(os.listdir(d))
             if re.search(r"-nomusic\.(mp4|mov|m4v)$", f)]
        sib = c[0] if c else None
    if not sib:
        det["applied"] = "no no-music sibling to measure against"
        return fails, det

    a, sr = _decode(sib)
    win = sr // 4
    k = len(a) // win
    lv = np.array([_dbfs(np.sqrt((a[i * win:(i + 1) * win] ** 2).mean()))
                   for i in range(k)])
    mask = np.zeros(k, bool)
    for lo, hi in muted_spans(work_dir):
        mask[max(int(lo / 0.25), 0):min(int(hi / 0.25) + 1, k)] = True
    if mask.sum() < 2 or (~mask).sum() < 2:
        det["applied"] = "not enough of either state to measure"
        return fails, det
    quiet_med, loud_med = float(np.median(lv[mask])), float(np.median(lv[~mask]))
    want = float(house(work_dir).get("audio_policy", {}).get("min_applied_db", 10.0))
    det["muted_dbfs"] = round(quiet_med, 1)
    det["kept_dbfs"] = round(loud_med, 1)
    det["applied_db"] = round(loud_med - quiet_med, 1)
    det["min_applied_db"] = want
    # Level says the policy was applied; it does not say the kept sound
    # SURVIVED. Masking is spectral, and a broadband comparison said "the room
    # leads" about a sizzle the bed was already 8 dB over. mixcheck.py measures
    # each kept segment in its own band; its count rides along here so the
    # question is asked on every run instead of when someone remembers.
    try:
        import mixcheck
        rows = mixcheck.analyse(work_dir or ".", video, sib)
        if rows:
            masked = [r["id"] for r in rows if r["verdict"] == "MASKED"]
            det["kept_audible"] = f"{len(rows) - len(masked)}/{len(rows)}"
            if masked:
                det["kept_but_masked"] = ",".join(masked) + "  (python3 mixcheck.py)"
    except Exception as e:                                   # noqa: BLE001
        det["kept_audible"] = f"could not measure ({type(e).__name__}: {e})"

    if loud_med - quiet_med < want:
        fails.append(
            f"the audio policy is declared but not applied: muted spans measure "
            f"{quiet_med:.1f} dBFS against {loud_med:.1f} dBFS for the kept ones, "
            f"a difference of {loud_med - quiet_med:.1f} dB where the house "
            f"minimum is {want:.1f} dB. A policy that only exists in the JSON is "
            f"the same video that prompted it")
    return fails, det


# ── G2: cover exists, is frame 1, and survives a thumbnail ───

def gate_cover(video, work_dir):
    fails, det = [], {}
    cover = None
    for name in ("cover.jpg", "cover.png"):
        p = os.path.join(work_dir or ".", name)
        if os.path.exists(p):
            cover = p
            break
    if not cover:
        for f in sorted(os.listdir(work_dir or ".")):
            if re.match(r"cover.*\.(jpg|png)$", f):
                cover = os.path.join(work_dir or ".", f)
                break
    det["cover"] = os.path.basename(cover) if cover else None
    if not cover:
        fails.append("no cover image in the work dir — the cover IS frame 1 and "
                     "the whole click decision on Reels; it is not optional")
        return fails, det

    try:
        from PIL import Image
        import numpy as np
        subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-frames:v", "1",
                        "-y", _scratch("f1.png")], stdin=subprocess.DEVNULL, check=True,
                       capture_output=True)
        f1 = np.asarray(Image.open(_scratch("f1.png")).convert("L").resize((64, 114)),
                        dtype=float)
        cv = np.asarray(Image.open(cover).convert("L").resize((64, 114)), dtype=float)
        sim = 1 - np.abs(f1 - cv).mean() / 255
        det["frame1_matches_cover"] = round(float(sim), 3)
        if sim < COVER_FIRST_FRAME_SIM:
            fails.append(f"frame 1 is not the cover (similarity {sim:.2f}) — burn it "
                         f"as an overlay on frame 1, do NOT prepend a segment")
        hs = house(work_dir)["cover"]
        meta_p = os.path.join(work_dir or ".", "cover_meta.json")
        if not os.path.exists(meta_p):
            fails.append("no cover_meta.json — build the cover with cover.build() so "
                         "its measurements can be gated, not eyeballed")
        else:
            m = json.load(open(meta_p))
            # The cover can be the right SHAPE with the picture on its side.
            # gate geometry and frame-1 similarity both pass a sideways cover —
            # measured 2026-08-23 on a build whose 1080x1920 cover showed a
            # pylon lying horizontal. cover.build() refuses a landscape source
            # now; this catches a build that wrote the file some other way.
            sw, sh = m.get("source_w"), m.get("source_h")
            if sw and sh:
                det["cover_source"] = f"{m.get('source', '?')} {sw}x{sh}"
                if sw > sh:
                    fails.append(
                        f"the cover was built from a LANDSCAPE source "
                        f"({sw}x{sh}) for a {FRAME_W}x{FRAME_H} cover — on phone "
                        f"footage that is the rotation trap: a clip that displays "
                        f"portrait reports 1920x1080, and a frame taken without "
                        f"the display matrix comes out on its side. The file will "
                        f"be the right shape and the picture will not")
            det["title_pt"], det["title_w"] = m["title_pt"], m["title_w"]
            det["subtitle_pt"], det["subtitle_w"] = m["subtitle_pt"], m["subtitle_w"]
            gap = abs(m["title_w"] - m["subtitle_w"])
            det["title_subtitle_gap_px"] = gap
            if m["title_lines"] > hs["max_title_lines"]:
                fails.append(f"cover title has {m['title_lines']} lines, max is "
                             f"{hs['max_title_lines']}")
            if gap > hs["subtitle_width_match_tol_px"]:
                fails.append(f"subtitle width {m['subtitle_w']}px does not track the "
                             f"title's {m['title_w']}px (off by {gap}px, tol "
                             f"{hs['subtitle_width_match_tol_px']}) — the two must read "
                             f"as one stacked block")
            floor = hs.get("subtitle_min_pt", 0)
            if floor and m["subtitle_pt"] < floor:
                fails.append(
                    f"cover subtitle rendered at {m['subtitle_pt']}pt (house "
                    f"floor {floor}pt) — width-matching a long subtitle to a "
                    f"short title crushes it below what an IG grid shows. "
                    f"Shorten the subtitle; never shrink it")
            cap = FRAME_W * hs["title_max_w_ratio"] + hs["title_ink_overhang_tol_px"]
            if m["title_w"] > cap:
                fails.append(f"cover title {m['title_w']}px is wider than the house "
                             f"{hs['title_max_w_ratio']:.0%} of frame")

        import cover as cover_mod
        leg = cover_mod.legibility(cover)
        det.update(leg)
        if not leg["ok"]:
            fails.append(f"cover title too small: line height "
                         f"{leg['title_line_ratio']:.3f} of frame "
                         f"(~{leg['px_at_ig_grid']}px in a 120px grid thumbnail, "
                         f"min ratio {leg['min_ratio']}) — use at most 2 SHORT lines "
                         f"so the sizer can grow the type")
    except Exception as e:                                   # noqa: BLE001
        fails.append(f"cover check failed: {e}")
    return fails, det


# ── G3: caption layout — position, safe area, overflow ───────

def _ass_style_table(raw):
    styles = {}
    for line in raw.splitlines():
        if line.startswith("Style:"):
            f = line[len("Style:"):].split(",")
            styles[f[0].strip()] = {
                "size": int(f[2]), "border": int(f[15]), "outline": float(f[16]),
                "align": int(f[18]), "ml": int(f[19]), "mr": int(f[20]),
                "mv": int(f[21]),
            }
    return styles


def gate_captions(work_dir):
    if _decision(work_dir, "captions") == "deferred":
        return [], {"deferred": "captions deferred by decisions.json"}
    fails, det = [], {}
    ass = None
    for n in ("captions.ass", "subtitles.ass"):
        p = os.path.join(work_dir or ".", n)
        if os.path.exists(p):
            ass = p
            break
    det["ass"] = os.path.basename(ass) if ass else None
    if not ass:
        fails.append("no .ass caption file in the work dir")
        return fails, det

    raw = open(ass, encoding="utf-8").read()
    styles = _ass_style_table(raw)
    ff = _font_file()
    if not ff:
        fails.append("caption font not found; cannot measure overflow")
        return fails, det
    from PIL import ImageFont

    layout_path = os.path.join(work_dir or ".", "layout.json")
    layout = json.load(open(layout_path)) if os.path.exists(layout_path) else {}
    det["layout_declared"] = len(layout)
    over, offbase, nested = [], [], 0
    placed = []
    used_styles, undeclared = set(), set()
    for line in raw.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        p = line.split(",", 9)
        style, text = p[3], p[9]
        st = styles.get(style)
        if not st or st.get("border") == 3 and "\\p1" in text:
            continue
        if "\\p1" in text:            # drawing command, not text
            continue
        # nested colour overrides: a per-keyword replace loop re-tags text it
        # already tagged (\1c...{\1c...}) and libass renders it wrong
        nested += len(re.findall(r"\{\\1c&H[0-9A-Fa-f]{8}&\}\{\\1c&H", text))
        m = re.search(r"\\pos\((\d+),\s*(\d+)\)", text)
        clean = re.sub(r"\{[^}]*\}", "", text).rstrip()
        pad = 2 * int(st["outline"]) if st["border"] == 3 else 0
        avail = FRAME_W - st["ml"] - st["mr"] - pad
        # Per-SPAN width: walk the event with a font-size state machine, the
        # way libass renders it. The old shortcut took the FIRST \fs in the
        # event for every later line — the moment gold keyword spans (\fs90)
        # appeared, English 48px lines were measured at 90px and 9 healthy
        # captions "overflowed". Measure what renders, not a guess at it.
        size, line_w, line_txt, lines_px = st["size"], 0.0, "", []
        for tok in re.split(r"(\{[^}]*\}|\\N)", text):
            if not tok:
                continue
            if tok == "\\N":
                lines_px.append((line_w, line_txt))
                line_w, line_txt = 0.0, ""
            elif tok.startswith("{"):
                fs_m = re.search(r"\\fs(\d+)", tok)
                if fs_m:
                    size = int(fs_m.group(1))
            else:
                line_w += ImageFont.truetype(ff, size).getlength(tok)
                line_txt += tok
        lines_px.append((line_w, line_txt))
        for wpx, sub in lines_px:
            if sub.strip() and wpx > avail:
                over.append(f"{sub[:18]} ({wpx:.0f}>{avail})")
        # Effective vertical position. A caption with NO \pos is the dangerous
        # case, not the safe one: it silently falls back to the style's alignment
        # default, which is how every caption in a whole version rendered at 50%
        # instead of the 70% baseline. So derive the fallback and check it too.
        if m:
            y, src = int(m.group(2)), "pos"
        else:
            al = st["align"]
            if al in (1, 2, 3):        # bottom-anchored
                y = FRAME_H - st["mv"]
            elif al in (4, 5, 6):      # middle-anchored
                y = FRAME_H // 2
            else:                      # top-anchored
                y = st["mv"]
            src = "fallback"
        used_styles.add(style)
        placed.append((_ass_secs(p[1]), _ass_secs(p[2]), y, style,
                       re.sub(r"\{[^}]*\}", "", text).replace("\\N", " ").strip()))
        anchor = layout.get(style)
        if anchor is None:
            undeclared.add(style)
        elif anchor in ANCHORS and \
                abs(y - FRAME_H * ANCHORS[anchor]) > FRAME_H * CAPTION_BASELINE_TOL:
            offbase.append(f"{style}@{y}({src}, declared {anchor})")

    # ── two captions in the same place at the same time ──────────────
    #
    # 0.45s of 清湯底／整鍋都是肉 rendered ON TOP OF 肉片一下鍋／顏色馬上就變 at
    # 20.80s and shipped, with every other caption gate green. Nothing looked
    # for it, because nothing ever had to: captions built from ASR word
    # timings are sequential BY CONSTRUCTION — each phrase ends where the next
    # begins. Authored captions (food-vlog-template §2) are hand-timed
    # arithmetic instead, and the moment a line is stretched past its own
    # segment to clear the min-dwell floor it can walk into its neighbour.
    #
    # Same anchor is the test, not same style: a two-layer design legitimately
    # shows a pill, a label and a caption at once, and the closest two anchors
    # in the shipped event build sit 210px apart.
    collisions = []
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a0, a1, ay, ast, atx = placed[i]
            b0, b1, by, bst, btx = placed[j]
            lap = min(a1, b1) - max(a0, b0)
            if lap > CAPTION_OVERLAP_TOL_S and abs(ay - by) < CAPTION_SAME_ANCHOR_PX:
                collisions.append(f"{atx[:12]}|{btx[:12]} {lap:.2f}s @{max(a0,b0):.2f}s")
    det["overlapping_captions"] = len(collisions)
    if collisions:
        fails.append(
            f"{len(collisions)} pair(s) of captions on screen at the same time in "
            f"the same place — they render on top of each other and neither is "
            f"readable: {'; '.join(collisions[:3])}. Hand-timed captions that each "
            f"stretch past their own segment to reach the dwell floor is how this "
            f"happens; make the handoff explicit (one ends where the next starts).")

    det["overflow"] = len(over)
    det["off_baseline"] = len(offbase)
    det["nested_colour_tags"] = nested
    if over:
        fails.append(f"{len(over)} caption line(s) wider than the safe area: "
                     f"{'; '.join(over[:3])}")
    det["undeclared_styles"] = sorted(undeclared)
    if undeclared:
        hs_ = house(work_dir)
        _base = f'{hs_["captions"]["baseline_pct"] * 100:.0f}%'
        _pill = f'{hs_["pill"]["centre_pct"] * 100:.0f}%'
        fails.append(f"style(s) not declared in layout.json: {', '.join(sorted(undeclared))} "
                     f"— declare each as \"caption\" ({_base}), \"pill\" ({_pill}) or \"free\". "
                     f"An undeclared style is an unchecked style.")
    if offbase:
        fails.append(f"{len(offbase)} caption(s) not at their declared anchor: "
                     f"{', '.join(offbase[:4])} — a style with no \\pos falls back to "
                     f"its alignment default")
    if nested:
        fails.append(f"{nested} nested colour override(s) — highlight keywords in ONE "
                     f"regex pass; a per-keyword replace loop re-tags its own output")
    return fails, det


# ── G4: top pill geometry ────────────────────────────────────

def gate_pill(work_dir):
    if _decision(work_dir, "captions") == "deferred":
        return [], {"deferred": "captions deferred by decisions.json"}
    fails, det = [], {}
    hs = house(work_dir)["pill"]
    pills = os.path.join(work_dir or ".", "pills.json")
    if not os.path.exists(pills):
        # A MISSING ARTIFACT IS A FAILURE, NOT A SKIP. This used to return PASS
        # with "pills: none", so a build with no pills at all — or with pills
        # drawn in ASS instead — sailed through the gate that exists to check them.
        det["pills"] = None
        if hs.get("required"):
            fails.append("no pills.json in the work dir — the top pill names the "
                         "thing on screen and is required; render it with "
                         "modules/title.py render_title_png (NOT in ASS)")
        return fails, det
    import glob
    from PIL import Image
    import numpy as np
    pngs = sorted(glob.glob(os.path.join(work_dir, "pills", "*.png")))
    det["pill_count"] = len(pngs)
    if not pngs:
        fails.append("pills.json exists but pills/*.png does not — nothing was rendered")
        return fails, det

    widths, centres, square = [], [], []
    for p in pngs:
        al = np.asarray(Image.open(p).convert("RGBA"))[:, :, 3]
        xs = np.where(al.sum(axis=0) > 0)[0]
        ys = np.where(al.sum(axis=1) > 0)[0]
        if not (len(xs) and len(ys)):
            continue
        widths.append(int(xs[-1] - xs[0] + 1))
        centres.append(float((ys[0] + ys[-1]) / 2 / FRAME_H))
        # A rounded capsule is transparent at the corners of its own bounding
        # box; an ASS opaque box is not. This is what tells them apart.
        corners = [al[ys[0], xs[0]], al[ys[0], xs[-1]],
                   al[ys[-1], xs[0]], al[ys[-1], xs[-1]]]
        if max(int(c) for c in corners) > hs["corner_alpha_max"]:
            square.append(os.path.basename(p))
    if not widths:
        fails.append("pill PNGs are fully transparent — nothing rendered")
        return fails, det

    det["pill_max_w_ratio"] = round(max(widths) / FRAME_W, 3)
    det["pill_centre"] = round(sum(centres) / len(centres), 3)
    det["square_cornered"] = len(square)
    if max(widths) / FRAME_W > hs["max_w_ratio"]:
        fails.append(f"pill runs edge to edge ({max(widths)}px = "
                     f"{max(widths)/FRAME_W:.0%}) — shorten the text or shrink the font")
    if any(abs(c - hs["centre_pct"]) > PILL_TOL for c in centres):
        fails.append(f"pill not at {hs['centre_pct']:.0%} height — the house position; "
                     f"higher than that and the Reels UI eats it")
    if square:
        fails.append(f"{len(square)} pill(s) have square corners ({square[0]}) — that is "
                     f"an ASS/box render, not the PIL capsule from title.py")

    if hs.get("forbid_fade"):
        movs = sorted(glob.glob(os.path.join(work_dir, "pills", "*.mov")))
        faded = []
        for m in movs:
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-i", m, "-frames:v", "1",
                                "-y", _scratch("pill0.png")], stdin=subprocess.DEVNULL,
                               check=True, capture_output=True)
                a0 = np.asarray(Image.open(_scratch("pill0.png")).convert("RGBA"))[:, :, 3]
                ref = np.asarray(Image.open(m.replace(".mov", ".png"))
                                 .convert("RGBA"))[:, :, 3]
                if int(a0.max()) < int(ref.max()) * 0.9:
                    faded.append(os.path.basename(m))
            except Exception:                                # noqa: BLE001
                continue
        det["faded_pills"] = len(faded)
        if faded:
            fails.append(f"{len(faded)} pill clip(s) fade in ({faded[0]}) — the house "
                         f"default is a hard cut on both layers")
    return fails, det


# ── G5: picture / container ──────────────────────────────────

def gate_delivery(video, work_dir=None):
    fails, det = [], {}
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,start_pts,duration,width,height",
                        "-of", "json", video], capture_output=True, text=True)
    info = json.loads(r.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    det["size"] = f"{v.get('width')}x{v.get('height')}"
    if int(v.get("start_pts", 0) or 0) != 0:
        fails.append("video does not start at PTS 0 — frame 1 renders black "
                     "(re-encode with -fps_mode cfr)")
    # Bits per pixel per frame — resolution-independent, and the thing a viewer
    # actually sees. A 2400k default shipped for a while: 0.027 bpp here, SSIM
    # 0.935 against a 20 Mbps reference, and the softness was caught by eye while
    # every gate passed. The house rule is to keep the picture the user shot;
    # this is the backstop for when someone sets the override too low.
    hs_d = house(work_dir).get("delivery", {})
    floor_bpp = float(hs_d.get("min_bits_per_pixel", 0))
    try:
        fps_s = (v.get("avg_frame_rate") or "30/1").split("/")
        fps = float(fps_s[0]) / float(fps_s[1] or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    vbr = float(v.get("bit_rate", 0) or 0)
    w_, h_ = int(v.get("width", 0) or 0), int(v.get("height", 0) or 0)
    if floor_bpp and vbr and w_ and h_ and fps:
        bpp = vbr / (w_ * h_ * fps)
        det["bits_per_pixel"] = round(bpp, 4)
        det["video_mbps"] = round(vbr / 1e6, 2)
        if bpp < floor_bpp:
            fails.append(
                f"delivery encode is {vbr/1e6:.1f} Mbps = {bpp:.3f} bits/pixel "
                f"(house floor {floor_bpp}) — visibly soft on detailed footage. "
                f"The house rule is to keep the picture the user shot; file size "
                f"is their call. Raise YIIBU_DELIVERY_BITRATE or leave it unset")

    vd, ad = float(v.get("duration", 0) or 0), float(a.get("duration", 0) or 0)
    det["video_dur"], det["audio_dur"] = round(vd, 3), round(ad, 3)
    if vd and ad and abs(vd - ad) > SYNC_TOL:
        fails.append(f"audio/video length mismatch: {vd:.2f}s vs {ad:.2f}s")
    return fails, det


# ── G6: typography — the look itself, not just where it sits ──

def gate_typography(work_dir):
    """The gate that would have caught 62pt outlined captions and ASS-box pills.

    Position gates pass a video that looks nothing like the last one. Style is
    what a reader actually recognises, so it is checked against house_style.json.
    """
    if _decision(work_dir, "captions") == "deferred":
        return [], {"deferred": "captions deferred by decisions.json"}
    fails, det = [], {}
    hs = house(work_dir)
    if hs.get("_overrides"):
        det["overrides"] = ",".join(hs["_overrides"])
    ass, rows = _dialogues(work_dir)
    if not ass:
        return ["no .ass caption file — cannot check typography"], det

    raw = open(ass, encoding="utf-8").read()
    styles = _ass_style_table(raw)
    want = hs["captions"]["styles"]
    used = {r["style"] for r in rows}
    det["styles_used"] = ",".join(sorted(used))

    fam = hs["font"]["family"]
    wrong_font = sorted({s for s in used
                         if _ass_style_font(raw, s) not in (None, fam)})
    det["font"] = fam
    if wrong_font:
        fails.append(f"style(s) not set in the house font {fam}: {', '.join(wrong_font)}")

    for name in sorted(used & set(want)):
        st, w = styles.get(name), want[name]
        if not st:
            continue
        if st["size"] != w["size"]:
            fails.append(f"{name} is {st['size']}pt, house style is {w['size']}pt")
        if st["outline"] != w["outline"]:
            fails.append(f"{name} has outline {st['outline']}, house style is "
                         f"{w['outline']} — a drop shadow, never a black outline")
        if st["align"] != w["alignment"]:
            fails.append(f"{name} alignment is {st['align']}, house style is "
                         f"{w['alignment']}")
    unknown = sorted(used - set(want) - {"SplitLabel", "Credit", "CardBig", "CardList"})
    det["unknown_styles"] = unknown

    if hs["captions"].get("forbid_fade"):
        faded = [r["style"] for r in rows
                 if re.search(r"\\fad\((?!0\s*,\s*0\))", r["text"])]
        det["faded_captions"] = len(faded)
        if faded:
            fails.append(f"{len(faded)} caption(s) use \\fad — the house default is a "
                         f"HARD CUT; a dissolving label reads as a rendering glitch")

    kw = hs["captions"].get("keyword")
    if kw and any(r["style"] == "Speech" for r in rows):
        # The gold keyword layer is part of the house look; a pass with zero
        # gold spans shipped 2026-08-17 and no gate noticed. Count spans that
        # carry BOTH the keyword size and the locked gold colour.
        pat = re.compile(r"\\fs" + str(kw["size"]) + r"[^}]*\\1?c" +
                         re.escape(kw["colour"]))
        spans = sum(len(pat.findall(r["text"])) for r in rows)
        det["keyword_gold_spans"] = spans
        if spans < kw.get("min_spans", 1):
            fails.append(f"only {spans} gold keyword span(s) (house minimum "
                         f"{kw.get('min_spans',1)}) — numbers and product names "
                         f"pop {kw['size']}px in {kw['colour']} (#F6DB66); an "
                         f"all-white caption pass is the 2026-08-17 defect")
        wrong = re.findall(r"\\1?c&H(?!FFFFFF|00EAEAEA|66DBF6)[0-9A-Fa-f]{6}",
                           " ".join(r["text"] for r in rows))
        det["off_palette_colours"] = sorted(set(wrong))
        if wrong:
            fails.append(f"caption colour(s) outside the house palette: "
                         f"{sorted(set(wrong))[:3]} — white, dim-white EN, and "
                         f"gold #F6DB66 are the only caption colours")

    bl = hs.get("bilingual", {})
    if bl.get("required"):
        size, colour = bl["english_font_size"], bl["english_colour"]
        pat = re.compile(r"\\N\{[^}]*\\fs" + str(size) + r"[^}]*\\c" + re.escape(colour))
        missing = [r for r in rows if r["style"] in want and not pat.search(r["text"])]
        det["bilingual"] = f"{len(rows) - len(missing)}/{len(rows)} captions"
        if missing:
            fails.append(f"bilingual is required but {len(missing)} caption(s) have no "
                         f"English line — half-translated is worse than not translated: "
                         f"e.g. {re.sub(r'{[^}]*}', '', missing[0]['text'])[:20]}")
    return fails, det


def _ass_style_font(raw, name):
    for line in raw.splitlines():
        if line.startswith("Style:") and line[len("Style:"):].split(",")[0].strip() == name:
            return line[len("Style:"):].split(",")[1].strip()
    return None


# ── G7: structure — the beats a short-form edit must have ─────

def gate_structure(video, work_dir):
    """A hook in the first second and an end card at the end.

    Both were re-derived from scratch on a rebuild because nothing checked them.
    """
    fails, det = [], {}
    hs = house(work_dir)["structure"]
    _ass, rows = _dialogues(work_dir)

    captions_deferred = _decision(work_dir, "captions") == "deferred"
    if captions_deferred:
        det["hook"] = "deferred with the caption layer"
    if hs.get("hook_required") and not captions_deferred:
        hooks = [r for r in rows if r["style"] == hs["hook_style"]]
        first = min((r["start"] for r in hooks), default=None)
        det["hook_at_s"] = first
        if first is None:
            fails.append(f"no '{hs['hook_style']}'-styled caption — the first 2 seconds "
                         f"decide the scroll and nothing is claiming them")
        elif first > hs["hook_must_start_before_s"]:
            fails.append(f"hook starts at {first:.2f}s, must be inside "
                         f"{hs['hook_must_start_before_s']}s")

    if _decision(work_dir, "end_card") == "off":
        det["end_card"] = "off by decisions.json"
    elif hs.get("end_card_required"):
        card = os.path.join(work_dir or ".", hs["end_card_artifact"])
        det["end_card"] = os.path.basename(card) if os.path.exists(card) else None
        if not os.path.exists(card):
            fails.append(f"no {hs['end_card_artifact']} in the work dir — the closing "
                         f"card is where the viewer learns what the thing is called")
        # AUTHORSHIP, declared. The two checks around this one are satisfied by a
        # SCREENSHOT OF THE LAST CLIP: the file exists, and the last frame matches
        # it at 0.99 because it is that frame. Measured 2026-08-23 on a real
        # build, whose viewer's verdict was "不知所云…完全沒有任何文字" — the
        # exact thing this gate exists to prevent, waved through.
        #
        # Pixels cannot tell a designed card from a grab; the freeze-duration
        # discriminator was measured and does not separate them (0.1s for a card
        # WITH text, 0.0s for the screenshot). So the text is declared, like
        # every other node contract here, and modules/endcard.py writes it.
        meta = os.path.join(work_dir or ".", "endcard_meta.json")
        if os.path.exists(card):
            if not os.path.exists(meta):
                fails.append(
                    "no endcard_meta.json — build the card with modules/endcard.py "
                    "(or write the file yourself) so what it SAYS is on record. "
                    "Without it, a still grabbed from the last clip satisfies every "
                    "other check in this gate: the file exists and the last frame "
                    "matches it, because it is that frame")
            else:
                try:
                    lines = [t for t in json.load(open(meta, encoding="utf-8"))
                             .get("text", []) if str(t).strip()]
                except (ValueError, OSError) as e:
                    lines, _ = [], det.setdefault("endcard_meta", f"unreadable: {e}")
                det["end_card_says"] = lines
                if not lines:
                    fails.append(
                        "endcard_meta.json declares no text — an end card with "
                        "nothing on it is a frame of the footage, not an ending")
        else:
            try:
                from PIL import Image
                import numpy as np
                subprocess.run(["ffmpeg", "-v", "error", "-sseof", "-0.3", "-i", video,
                                "-frames:v", "1", "-y", _scratch("last.png")],
                               stdin=subprocess.DEVNULL, check=True, capture_output=True)
                last = np.asarray(Image.open(_scratch("last.png")).convert("L")
                                  .resize((64, 114)), dtype=float)
                ref = np.asarray(Image.open(card).convert("L").resize((64, 114)),
                                 dtype=float)
                sim = 1 - np.abs(last - ref).mean() / 255
                det["last_frame_matches_card"] = round(float(sim), 3)
                if sim < COVER_FIRST_FRAME_SIM:
                    fails.append(f"the video does not end on {hs['end_card_artifact']} "
                                 f"(similarity {sim:.2f})")
            except Exception as e:                           # noqa: BLE001
                fails.append(f"end-card check failed: {e}")
    return fails, det


# ── G8: verbatim captions must match the audio under them ────

def gate_sync(work_dir):
    """If a caption claims to be speech, the speech has to actually be there.

    Found four real defects the position/typography gates cannot see: a caption
    whose first word was cut off by the segment in-point, a caption 1.3s late, an
    authored line sitting over audio that says something else, and a stale
    words.json (every caption off by one edit's worth of time).

    verify.py's older lip-sync check matched each caption's FIRST CHARACTER to
    the nearest word, which false-positived on pills and on Latin words that ASR
    splits ("G"/"em"/"ma"). This aligns the whole caption instead, and
    back-projects from the median timestamp of the longest matching run — the
    median is what makes a word split across a pause stop lying about its onset.
    """
    import difflib
    import statistics
    fails, det = [], {}
    hs = house(work_dir)["sync"]
    if not hs.get("required", True):
        det["sync"] = "disabled"
        return fails, det

    _ass, rows = _dialogues(work_dir)
    verbatim = [r for r in rows if r["style"] in hs["verbatim_styles"]]
    det["verbatim_captions"] = len(verbatim)
    if not verbatim:
        return fails, det                       # nothing claims to be speech

    wp = os.path.join(work_dir or ".", "words.json")
    if not os.path.exists(wp):
        return ([f"{len(verbatim)} caption(s) use a verbatim style "
                 f"({'/'.join(hs['verbatim_styles'])}) but there is no words.json — "
                 f"a verbatim claim that cannot be checked is not verbatim. Write the "
                 f"ASR words remapped to TIMELINE time."], det)

    words = json.load(open(wp, encoding="utf-8"))
    S, T = [], []
    for w in words:
        for ch in _PUNCT.sub("", w.get("text") or w.get("word", "")):
            S.append(ch)
            T.append(float(w["start"]))
    S = "".join(S)
    if not S:
        return ["words.json has no usable words"], det

    bad_cov, bad_head, bad_lag, lags, signed_lags = [], [], [], [], []
    for r in verbatim:
        cap = _caption_cjk(r["text"])
        if not cap:
            continue
        a, b = r["start"], r["end"]
        lo = next((i for i, t in enumerate(T) if t >= a - hs["search_window_s"]), 0)
        hi = next((i for i, t in enumerate(T) if t > b + hs["search_window_s"]), len(T))
        m = difflib.SequenceMatcher(None, cap, S[lo:hi], autojunk=False)
        blocks = [x for x in m.get_matching_blocks() if x.size > 0]
        if not blocks:
            bad_cov.append((cap, 0.0))
            continue
        cov = sum(x.size for x in blocks) / len(cap)
        big = max(blocks, key=lambda x: x.size)
        tmed = statistics.median(T[lo + big.b: lo + big.b + big.size])
        lag = (tmed - ((big.a + big.size / 2) / len(cap)) * (b - a)) - a
        lags.append(abs(lag))
        signed_lags.append(lag)
        if cov < hs["min_coverage"]:
            bad_cov.append((cap, round(cov, 2)))
        if blocks[0].a > hs["max_head_unmatched"]:
            bad_head.append((cap, blocks[0].a))
        if abs(lag) > hs["max_lag_s"]:
            bad_lag.append((cap, round(lag, 2)))

    # A whole-map offset shows up as a small-but-CONSISTENT lag on every caption,
    # which no per-caption threshold catches. This is the stale-words.json bug:
    # the map was never regenerated after a cut point moved.
    if len(lags) >= 5:
        signed = sorted(signed_lags)
        med = signed[len(signed) // 2]
        same_sign = sum(1 for x in signed_lags if x * med > 0) / len(signed_lags)
        det["median_lag_s"] = round(med, 2)
        if abs(med) > hs["max_median_lag_s"] and same_sign > 0.8:
            fails.append(f"every verbatim caption drifts the same way (median "
                         f"{med:+.2f}s, {same_sign:.0%} same sign) — that is a stale "
                         f"words.json, not 27 bad captions: regenerate the word map "
                         f"from the CURRENT cut points")
    det["worst_lag_s"] = round(max(lags), 2) if lags else None
    det["off_sync"] = len(bad_cov) + len(bad_head) + len(bad_lag)
    if bad_cov:
        fails.append(f"{len(bad_cov)} caption(s) are not what the audio says "
                     f"(coverage < {hs['min_coverage']}): " +
                     "; ".join(f"{c}={v}" for c, v in bad_cov[:3]))
    if bad_head:
        fails.append(f"{len(bad_head)} caption(s) open with words that are not in the "
                     f"audio — usually the cut starts after the word: " +
                     "; ".join(f"{c} (first {n} chars unheard)" for c, n in bad_head[:3]))
    if bad_lag:
        fails.append(f"{len(bad_lag)} caption(s) off by more than {hs['max_lag_s']}s: " +
                     "; ".join(f"{c} {v:+}s" for c, v in bad_lag[:3]) +
                     " — if ALL of them drift by a similar amount, words.json is stale, "
                     "not the captions")
    return fails, det


_PUNCT = re.compile(r"[，、。．.！!？?；;：:「」『』（）()\s\u3000]")


def _caption_cjk(text):
    """The spoken line only: strip ASS tags, the English line, and punctuation."""
    t = re.sub(r"\\N\{\\fs\d+.*$", "", text)          # bilingual second line
    t = re.sub(r"\{[^}]*\}", "", t).replace("\\N", "")
    return _PUNCT.sub("", t).strip()


def gate_music_bed(video, work_dir):
    """The music bed must not die before the video does.

    gate_audio measures the FINISHED MIX, so a bed that has already faded to
    nothing is invisible to it as long as someone is still talking: the last 2.5s
    of a build read -16 dBFS and passed while the music underneath sat at -58.
    The defect was a tail fade inherited from an older cut whose ending had since
    been deleted, so the fade landed under the closing sentence instead of over a
    wind-down beat.

    The skill already ships BOTH a music and a no-music version of every video,
    which makes this measurable: subtract one from the other and what is left is
    the bed. No sibling to subtract means the pair was not shipped, which is its
    own failure.
    """
    import numpy as np
    fails, det = [], {}
    base = os.path.basename(video)
    if re.search(r"-nomusic\.\w+$", base):
        det["music_bed"] = "n/a (this IS the no-music version)"
        return fails, det

    d = os.path.dirname(os.path.abspath(video))
    sib = [os.path.join(d, f) for f in sorted(os.listdir(d))
           if re.search(r"-nomusic\.(mp4|mov|m4v)$", f)]
    det["nomusic_sibling"] = os.path.basename(sib[0]) if sib else None
    if not sib:
        fails.append("no *-nomusic.* sibling next to this file — the house rule is "
                     "that BOTH versions ship, and without the pair the music bed "
                     "cannot be measured underneath the speech")
        return fails, det

    a, sr = _decode(sib[0])
    b, _ = _decode(video)
    n = min(len(a), len(b))
    if n < sr:
        fails.append("music/no-music pair too short or failed to decode")
        return fails, det
    bed = b[:n] - a[:n]                       # what the music version added

    win = sr // 4                             # 0.25s
    rms = np.array([np.sqrt((bed[i:i + win] ** 2).mean())
                    for i in range(0, n - win, win)])
    # RELATIVE threshold, not an absolute dBFS one. Both files are AAC-encoded
    # independently, so subtracting them leaves codec noise as well as the bed;
    # a fixed -40 dBFS line sat inside that noise and the same build settings
    # measured 1.18s one rebuild and 2.93s the next. Judging the bed against its
    # OWN median asks the question that actually matters — did the bed drop out
    # relative to how loud it has been all video — and rides over the noise.
    floor = float(np.median(rms[rms > 0])) * 10 ** (-25 / 20)
    det["bed_dropout_floor_dbfs"] = round(_dbfs(floor), 1)
    live = np.where(rms > floor)[0]
    if not len(live):
        det["bed_peak_dbfs"] = round(_dbfs(np.abs(bed).max()), 1)
        fails.append("the music version has no music in it — the bed is silent "
                     "for the whole video")
        return fails, det

    total_s = n / sr

    # The bed has to ESTABLISH. Everything below this point watches the END of
    # the video; a bed that never starts passed all of it, twice, on two edits,
    # because "still playing at the end" and "playing at the beginning" are
    # different questions and only one was being asked.
    mus = house(work_dir).get("music", {})
    head_limit = float(mus.get("max_silent_head_s", 0))
    if head_limit:
        # AUDIBILITY, not presence. A bed sitting 20 dB under a loud room is
        # there in the arithmetic and gone to the ear, and the dropout floor
        # below — which is relative to the bed's OWN median — happily calls it
        # live. The question a listener asks is whether they can hear music over
        # the programme, so that is the question measured.
        lead = float(mus.get("head_lead_db", 6.0))
        prog = np.array([np.sqrt((a[i:i + win] ** 2).mean())
                         for i in range(0, n - win, win)])
        rel = 20 * np.log10((rms + 1e-12) / (prog + 1e-12))
        # Inclusive: "within `lead` dB" means within, and a bed sitting exactly
        # at the line is audible. The strict form failed a fixture whose bed is
        # deliberately 6 dB under its programme, which is a boundary artefact
        # rather than a defect.
        audible = np.where(rel >= -lead - 0.25)[0]
        first_audible_s = float(audible[0] * win / sr) if len(audible) else total_s
        det["bed_audible_from_s"] = round(first_audible_s, 2)
        det["head_lead_db"] = lead
        det["max_silent_head_s"] = head_limit
        head_dec = (decisions(work_dir) or {}).get("music", {})
        if isinstance(head_dec, dict) and head_dec.get("head") == "cold_open":
            det["cold_open"] = head_dec.get("why", "")[:60] or "declared"
            first_audible_s = 0.0        # declared on purpose; nothing to report
        if first_audible_s > head_limit:
            fails.append(
                f"no audible music until {first_audible_s:.1f}s — the bed is "
                f"more than {lead:.0f} dB under the programme before that, which "
                f"is a silent opening to a listener however present it is in the "
                f"arithmetic. A viewer who hears nothing at the top concludes "
                f"the video has no music. Usually an amplitude-driven duck "
                f"firing on a loud opening shot: leave the head un-ducked, duck "
                f"shallower, or raise the bed so it LEADS instead of tying with "
                f"the room. If the opening holds music back ON PURPOSE — it opens "
                f"on someone talking — say so: decisions.json "
                f'music: {{"head": "cold_open", "why": "..."}}')

    last_live_s = float((live[-1] + 1) * win / sr)
    dead_tail = total_s - last_live_s
    det["bed_median_dbfs"] = round(_dbfs(np.median(rms[live])), 1)
    det["bed_ends_at_s"] = round(last_live_s, 2)
    det["video_len_s"] = round(total_s, 2)
    det["dead_tail_s"] = round(dead_tail, 2)

    # A deliberate fade is fine; a bed that is gone for a chunk of the ending is
    # the thing that reads as "the music cut out". The threshold lives in
    # house_style.json because it has to clear the project's own fade-out length.
    limit = float(house(work_dir).get("music", {}).get("max_dead_tail_s", 1.5))
    det["max_dead_tail_s"] = limit
    if dead_tail > limit:
        fails.append(f"music bed goes silent {dead_tail:.1f}s before the end "
                     f"(last audible at {last_live_s:.1f}s of {total_s:.1f}s) — "
                     f"check the fade-out start against the LAST SPOKEN WORD, not "
                     f"against a length inherited from an earlier cut")
    return fails, det


# ── Decisions only the user can make ─────────────────────────────
#
# These were prose in SKILL.md and references/*.md, which means every run
# re-decided them and reported the result as if it were a default. The loudness
# rule ("ask before normalising") was followed by neither of two consecutive
# builds. Prose cannot bind a model; a required file can.
#
# value -> the choice that needs a written reason, because it departs from the
# documented default or defers work.
REQUIRED_DECISIONS = {
    "loudness":  {"allowed": ("original", "-14LUFS"), "needs_why": "-14LUFS"},
    "captions":  {"allowed": ("on", "deferred"),      "needs_why": "deferred"},
    "end_card":  {"allowed": ("on", "off"),           "needs_why": "off"},
    # 'full' = original audio under the whole video. Correct when someone is
    # talking to camera; wrong on a 花絮 where nobody narrates, which is how 48
    # seconds of restaurant hum shipped on top of a music bed. Either answer is
    # allowed, neither may be assumed, and 'full' has to say why the room earns
    # the whole running time.
    "audio_policy": {"allowed": ("full", "selective"), "needs_why": "full"},
}


def audio_policy(work_dir):
    """The per-segment keep/mute declaration, or None if this build is 'full'."""
    p = os.path.join(work_dir or ".", "audio_policy.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p))
    except (ValueError, OSError):
        return None


def muted_spans(work_dir):
    pol = audio_policy(work_dir)
    if not pol:
        return []
    return [(r["start"], r["start"] + r["dur"])
            for r in pol.get("segments", []) if not r.get("keep")]


def kept_spans(work_dir):
    pol = audio_policy(work_dir)
    if not pol:
        return []
    return [(r["start"], r["start"] + r["dur"])
            for r in pol.get("segments", []) if r.get("keep")]


def decisions(work_dir):
    p = os.path.join(work_dir or ".", "decisions.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}


def _decision(work_dir, key):
    d = decisions(work_dir) or {}
    v = d.get(key)
    return v.get("value") if isinstance(v, dict) else v


def gate_decisions(video, work_dir):
    """Every choice that is the user's must be recorded, not silently defaulted.

    An agent that picks for the user and reports "done" is the failure this
    catches, and it is the one failure mode that varies most between models.
    """
    fails, det = [], {}
    d = decisions(work_dir)
    if d is None:
        return ([f"no decisions.json in the work dir — record the choices only "
                 f"the user can make: {', '.join(sorted(REQUIRED_DECISIONS))}. "
                 f"Each is {{\"value\": ..., \"why\": ...}}; ask, do not default."],
                {"decisions": None})
    for key, spec in sorted(REQUIRED_DECISIONS.items()):
        raw = d.get(key)
        val = raw.get("value") if isinstance(raw, dict) else raw
        why = raw.get("why") if isinstance(raw, dict) else None
        det[key] = val if not why else f"{val} ({why})"
        if val is None:
            fails.append(f"decisions.json has no '{key}' — allowed: "
                         f"{'/'.join(spec['allowed'])}")
        elif val not in spec["allowed"]:
            fails.append(f"decisions.json '{key}'={val!r} is not one of "
                         f"{'/'.join(spec['allowed'])}")
        elif val == spec["needs_why"] and not (why or "").strip():
            fails.append(f"decisions.json '{key}'={val!r} departs from the "
                         f"documented default, so it needs a 'why' the user "
                         f"actually agreed to")
    return fails, det


def gate_deliverables(video, work_dir):
    """Both versions and the cover, at the project's first level.

    "Always deliver BOTH a music and a no-music version" and "deliverables land
    in the PROJECT ROOT" were prose in SKILL.md, which means every run re-decided
    them. A half-delivery is not visible from inside the file being gated, so
    nothing caught it.
    """
    fails, det = [], {}

    # Staged delivery: the set is what delivery.json DECLARES, not what happens
    # to be lying in the directory. In a work dir the old listing check passes
    # for the wrong reason — spine.mov and trimmed.mp4 both read as "a music
    # version" — so a staged build would have been gated by a check that could
    # no longer fail.
    delivery = load_delivery(work_dir)
    if delivery and os.path.dirname(os.path.abspath(video)) == \
            os.path.abspath(work_dir or "."):
        wd = os.path.abspath(work_dir or ".")
        det["staged"] = delivery["files"]
        missing = [k for k in delivery["files"] if not os.path.exists(os.path.join(wd, k))]
        finals = list(delivery["files"].values())
        if missing:
            fails.append(f"declared in {DELIVERY} but not built: {', '.join(sorted(missing))}")
        if not any(re.search(r"-nomusic\.\w+$", f) for f in finals):
            fails.append("no *-nomusic.* in the declared delivery — the no-music "
                         "version is the honest record of the day and always ships")
        if not any(not re.search(r"-nomusic\.\w+$", f)
                   and f.lower().endswith((".mp4", ".mov", ".m4v")) for f in finals):
            fails.append("no music version in the declared delivery — both "
                         "versions ship, whatever the user said about music")
        if not any(re.fullmatch(r"cover\.(jpg|png)", f) for f in finals):
            fails.append("no cover.jpg/png in the declared delivery — the cover "
                         "ships alongside the videos, not only inside build/")
        return fails, det

    d = os.path.dirname(os.path.abspath(video))
    vids = [f for f in sorted(os.listdir(d)) if f.lower().endswith((".mp4", ".mov", ".m4v"))]
    nomusic = [f for f in vids if re.search(r"-nomusic\.\w+$", f)]
    music = [f for f in vids if not re.search(r"-nomusic\.\w+$", f)]
    covers = [f for f in sorted(os.listdir(d)) if re.fullmatch(r"cover\.(jpg|png)", f)]
    det["dir"] = d
    det["nomusic"] = nomusic or None
    det["music"] = music or None
    det["cover"] = covers[0] if covers else None

    if not nomusic:
        fails.append("no *-nomusic.* at the project's first level — the no-music "
                     "version is the honest record of the day and always ships")
    if not music:
        fails.append("no music version at the project's first level — both "
                     "versions ship, whatever the user said about music")
    if not covers:
        fails.append("no cover.jpg/png at the project's first level — the cover "
                     "ships alongside the videos, not only inside build/")
    return fails, det


def gate_cover_colour(video, work_dir):
    """The cover subtitle is the house yellow, measured off the rendered pixels.

    cover.draw() defaults to it, but a caller can still pass a literal colour,
    and nothing looked at the actual image. The house value lives in
    house_style.json so this and the renderer cannot drift apart.
    """
    import numpy as np
    from PIL import Image
    fails, det = [], {}
    hs = house(work_dir)["cover"]
    want_hex = str(hs.get("subtitle_gold", "#F6DB66")).lstrip("#")
    want = np.array([int(want_hex[i:i + 2], 16) for i in (0, 2, 4)], dtype=int)
    det["subtitle_gold"] = "#" + want_hex.upper()

    cover = None
    for name in ("cover.jpg", "cover.png"):
        p = os.path.join(work_dir or ".", name)
        if os.path.exists(p):
            cover = p
            break
    if not cover:
        fails.append("no cover in the work dir to check the subtitle colour on")
        return fails, det

    a = np.asarray(Image.open(cover).convert("RGB"), dtype=int)
    TOL = 26                       # clears JPEG chroma subsampling, not a hue change
    hit = int((np.abs(a - want).max(axis=2) <= TOL).sum())
    det["matching_px"] = hit
    if hit < 2000:
        # Say what IS there, so the fix is one edit rather than a hunt.
        yellowish = a[(a[:, :, 0] > 170) & (a[:, :, 1] > 140) & (a[:, :, 2] < 190)]
        det["dominant_yellow"] = ("#%02X%02X%02X" % tuple(np.median(yellowish, axis=0).astype(int))
                                  if len(yellowish) else None)
        fails.append(
            f"cover subtitle is not the house yellow #{want_hex.upper()} "
            f"(only {hit}px within tolerance; found {det.get('dominant_yellow')}) — "
            f"let cover.draw() default to it, do not pass a literal colour")
    return fails, det


def gate_duck(video, work_dir):
    """The bed has to actually get out of the way of the speech.

    MusicBed proves the music is still PLAYING at the end; nothing proved it
    ever ducked. buildkit.duck_mix triggered on an absolute amplitude, so on
    2026-08-19 it ducked a close mic 7-9 dB, two room-distance judges 2-3 dB,
    and 8.5 dB under a shot of paper being turned — all twelve gates green, and
    the user found it by ear. Measured the same way MusicBed is: subtract the
    no-music sibling and what is left is the bed alone.
    """
    import numpy as np
    fails, det = [], {}
    if re.search(r"-nomusic\.\w+$", os.path.basename(video)):
        det["duck"] = "n/a (this IS the no-music version)"
        return fails, det

    # Some videos have nobody talking in them. A food vlog is authored captions
    # over room tone; the food-vlog template says as much ("audio left at the
    # original level"). There is no quiet speaker for the bed to get out of the
    # way of, and forcing a duck there would push the music down under clatter
    # for no listener's benefit — which is how one of these ended up with a
    # silent opening in the first place.
    #
    # The gate cannot tell "nobody speaks" from "the duck is broken", so it does
    # not try: the claim goes on record and is checked like every other decision.
    mus_dec = (decisions(work_dir) or {}).get("music", {})
    if isinstance(mus_dec, dict) and mus_dec.get("duck") == "none":
        why = str(mus_dec.get("why", "")).strip()
        if not why:
            return ["music.duck is 'none' with no 'why' — say what carries the "
                    "audio instead, and why nothing needs the bed to move"], det
        det["duck"] = f"declared none — {why[:70]}"
        return fails, det

    d = os.path.dirname(os.path.abspath(video))
    sib = [os.path.join(d, f) for f in sorted(os.listdir(d))
           if re.search(r"-nomusic\.(mp4|mov|m4v)$", f)]
    if not sib:
        det["duck"] = "no no-music sibling — MusicBed already fails on this"
        return fails, det

    speech, sr = _decode(sib[0])
    mixed, _ = _decode(video)
    n = min(len(speech), len(mixed))
    if n < sr:
        det["duck"] = "pair too short to measure"
        return fails, det
    bed = mixed[:n] - speech[:n]

    hop = sr // 100                                    # 10 ms
    k = n // hop
    env = np.array([np.abs(speech[i*hop:(i+1)*hop]).max() for i in range(k)])
    edb = 20 * np.log10(env + 1e-9)
    beddb = np.array([20 * np.log10(np.sqrt((bed[i*hop:(i+1)*hop] ** 2).mean()) + 1e-9)
                      for i in range(k)])

    # Classify from the material, never an absolute line — that absolute line is
    # the bug this gate exists to catch.
    floor, top = np.percentile(edb, 20), np.percentile(edb, 97)
    thresh = floor + 0.45 * max(top - floor, 6.0)
    loud = edb > thresh
    det["speech_frames_pct"] = f"{loud.mean():.0%}"
    if loud.mean() < 0.08 or (~loud).mean() < 0.08:
        det["duck"] = "not enough speech / not enough silence to compare"
        return fails, det

    # Ignore frames where the bed is absent entirely (before it enters).
    live = beddb > np.percentile(beddb, 15)
    a = beddb[loud & live]
    b = beddb[(~loud) & live]
    if len(a) < 10 or len(b) < 10:
        det["duck"] = "bed not present under both conditions"
        return fails, det

    drop = float(np.median(b) - np.median(a))
    want = house(work_dir)["music"].get("duck_min_db", 4.0)
    det["bed_under_speech_dbfs"] = round(float(np.median(a)), 1)
    det["bed_elsewhere_dbfs"] = round(float(np.median(b)), 1)
    det["duck_depth_db"] = round(drop, 1)
    det["duck_min_db"] = want
    if drop < want:
        fails.append(_duck_message(drop, want))
    return fails, det


def _duck_message(drop, want):
    """Say the measurement in a way that cannot read as a pass.

    Both defects here were found by `friction.py` in real build logs, not by
    review:

      * `{drop:.1f}` printed the measurement at the SAME precision as the
        threshold, so 3.96 dB came out as "the music only drops 4.0 dB under
        speech (house minimum 4.0 dB)" — a sentence that says you met the bar
        while blocking you for missing it. It cost a render in two separate
        projects (build-safe #8, build-v2 #8), because the only sane reading is
        "the gate is wrong" and the only available move is to render again.
      * a NEGATIVE drop means the bed got LOUDER under the speech, which is the
        opposite failure and the one worth panicking about — and it was
        reported as "only drops -1.6 dB", which reads like a rounding quibble.
        Four of the thirteen recorded Duck failures were this case.
    """
    tail = ("If the speakers sit at different distances, drive the duck from a "
            "written-down segment list (buildkit.duck_mix(..., speech_spans=[...])) "
            "instead of amplitude")
    if drop < 0:
        return (f"the music gets LOUDER under speech by {abs(drop):.2f} dB "
                f"(house minimum is a {want:.1f} dB drop) — the bed is not "
                f"ducking at all, it is competing. " + tail)
    return (f"the music only drops {drop:.2f} dB under speech (house minimum "
            f"{want:.1f} dB, short by {want - drop:.2f} dB) — a bed that does "
            f"not get out of the way buries the quieter speakers. " + tail)


def gate_caption_dwell(work_dir):
    """A caption nobody can finish reading is a defect, not a style choice."""
    if _decision(work_dir, "captions") == "deferred":
        return [], {"deferred": "captions deferred by decisions.json"}
    fails, det = [], {}
    floor = house(work_dir)["captions"].get("min_dwell_s", 1.8)
    _ass, rows = _dialogues(work_dir)
    det["min_dwell_s"] = floor
    if not rows:
        return fails, det
    short = [(r["end"] - r["start"], _caption_cjk(r["text"]) or r["text"])
             for r in rows if (r["end"] - r["start"]) < floor]
    det["captions"] = len(rows)
    det["too_short"] = len(short)
    if short:
        worst = sorted(short)[:3]
        fails.append(
            f"{len(short)} caption(s) on screen for less than {floor}s: "
            + "; ".join(f"{d:.2f}s {t[:14]}" for d, t in worst)
            + " — plan.py has carried this floor as advice for a long time and "
              "nothing enforced it")
    return fails, det


# ── G15: clearance — is any of this somebody else's to release? ──

def gate_clearance(work_dir):
    """Nothing here judges whether footage is embargoed. It checks that the
    question was asked, and that the answer was honoured.

    A 93.6s conference recap shipped with all fourteen other gates green and 41
    of those seconds under NDA — unreleased slides carrying a tentative GA date,
    an unannounced model's spec table, named staff answering a roadmap question.
    No gate is about ownership, so none of them looked.

    **This gate is silent on footage that does not look like session material.**
    It derives its own applicability from the timeline's source filenames rather
    than demanding a scan artifact from every build: a folder of food or running
    clips trips nothing and the user never hears about it, which is the whole
    point. That also means it cannot be skipped by not running the scanner —
    when the sources DO look like session footage, the missing artifact is the
    failure.
    """
    import clearance
    fails, det = [], {}
    tl = os.path.join(work_dir or ".", "timeline.json")
    if not os.path.exists(tl):
        det["clearance"] = "no timeline.json — nothing to check sources against"
        return fails, det

    segs = json.load(open(tl, encoding="utf-8")).get("segments", [])
    sources = sorted({os.path.basename(s.get("file") or s.get("path") or "")
                      for s in segs} - {""})
    hits = clearance.triage_names(sources)
    det["sources"] = len(sources)
    det["session_shaped"] = sorted(hits)

    # A VACUOUS PASS IS NOT A PASS. This gate derives its own applicability from
    # the timeline's source filenames, which is what keeps it silent on food and
    # running footage — and which means an empty source list looks exactly like
    # "nothing here needs asking about". On 2026-08-22 a driver wrote each
    # segment's origin under `source`; the two readers above look for `file` or
    # `path`, the set came out empty, and this gate triaged nothing and reported
    # green on 17 segments it had never seen the names of.
    #
    # gate_timeline now rejects that timeline outright. This stays as the check
    # at the point of the bug: the question "did I actually look at anything?"
    # is one every derive-your-own-applicability gate has to ask itself.
    if segs and not sources:
        fails.append(
            f"{len(segs)} segment(s) in timeline.json and not one names its "
            f"source file — this gate decides whether it applies by READING "
            f"those names, so an empty list is not 'nothing to clear', it is "
            f"'nothing was checked'. Write each segment's origin under \"file\"")
        return fails, det

    dec = decisions(work_dir) or {}
    cl = dec.get("clearance")

    if not hits:
        det["clearance"] = "no session-shaped source material — not applicable"
        # An answer given anyway is still honoured: exclusions are checked below.
        if not cl:
            return fails, det

    scan_path = os.path.join(work_dir or ".", "clearance_scan.json")
    det["scan"] = os.path.basename(scan_path) if os.path.exists(scan_path) else None

    if hits and not cl:
        fails.append(
            f"{len(hits)} source clip(s) look like session footage "
            f"({', '.join(sorted(hits)[:3])}…) and decisions.json records no "
            f"'clearance'. Run `python3 clearance.py FOOTAGE_DIR --work-dir "
            f"{work_dir}`, ask whoever ran the event, then record the answer. "
            f"Who may publish this is not a question a gate can answer for you")
        return fails, det

    if not cl:
        return fails, det

    if isinstance(cl, str):
        fails.append("clearance must be an object with a written 'why' — who "
                     "cleared this, and when. A bare value records nothing")
        return fails, det

    det["clearance"] = cl.get("value")
    if cl.get("value") not in ("public", "internal", "mixed"):
        fails.append(f"clearance value {cl.get('value')!r} is not one of "
                     f"public / internal / mixed")
    if cl.get("value") in ("internal", "mixed") and not str(cl.get("why", "")).strip():
        fails.append("clearance is not 'public' and carries no 'why' — record "
                     "who cleared it and what they said")

    # The mechanical half: a declared exclusion must be absent from the cut.
    excluded = [os.path.basename(x) for x in cl.get("excluded", [])]
    det["excluded"] = excluded
    leaked = sorted(set(excluded) & set(sources))
    if leaked:
        fails.append(
            f"excluded source(s) present in the cut: {leaked} — decisions.json "
            f"says these may not be published and timeline.json uses them")
    return fails, det


def gate_timeline(work_dir):
    """The artifact three other checks read has to have the keys they read.

    Every other node contract in this skill is a declared artifact a gate can
    read — layout.json, pills.json, cover_meta.json, decisions.json. timeline.json
    was not one of them: it is written by each project's own build script, three
    consumers read it, and nothing said what shape it had to be. So the shape got
    guessed, and on 2026-08-22 a driver guessed differently — each segment's
    origin under `source` where the readers look for `file`.

    Nothing errored. A renamed key does not raise; it silently empties the set it
    feeds, and an empty set reads as "nothing to report":

      * gate_clearance triaged an EMPTY list of source names and passed. Its
        entire job is to refuse footage that looks like session material with no
        recorded answer about who may publish it, and it cleared 17 segments it
        had never seen the names of.
      * the coverage table collapsed into one "—" bucket, so the omission check
        — the other thing the gates are structurally blind to — reported nothing.
      * the build log recorded "1 source clip" for a 17-segment cut.

    All sixteen gates were green while that was true. Hence a seventeenth: the
    contract is now declared and checked, like the other four.

    NOT required. The single-video postprod path does not write a timeline, and
    gate_clearance already says so gracefully. This validates the file when it
    exists, which is the only time its shape can be wrong.
    """
    fails, det = [], {}
    p = os.path.join(work_dir or ".", "timeline.json")
    if not os.path.exists(p):
        det["timeline"] = "none (single-video path writes no timeline)"
        return fails, det
    try:
        tl = json.load(open(p, encoding="utf-8"))
    except (ValueError, OSError) as e:
        return [f"timeline.json does not parse: {e}"], det

    segs = tl.get("segments")
    if not isinstance(segs, list) or not segs:
        return ["timeline.json has no 'segments' list — every consumer of this "
                "file iterates it"], det
    det["segments"] = len(segs)

    missing_id = [i for i, s in enumerate(segs)
                  if not str(s.get("id") or "").strip()]
    if missing_id:
        fails.append(f"segment(s) at index {missing_id[:5]} have no \"id\" — "
                     f"gate_audio_policy matches audio_policy.json to the cut by "
                     f"id, and an unnamed segment can never be matched")
    ids = [s.get("id") for s in segs if s.get("id")]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        fails.append(f"duplicate segment id(s): {dupes[:5]} — the audio policy "
                     f"call for one of them silently applies to the other")

    # `path` is accepted because gate_clearance already accepts it; `source` is
    # named in the message because it is the guess that was actually made, and a
    # message that names the near miss is the one that gets acted on.
    no_src = [s.get("id") for s in segs
              if not str(s.get("file") or s.get("path") or "").strip()]
    det["source_key"] = "file" if any(s.get("file") for s in segs) else (
        "path" if any(s.get("path") for s in segs) else None)
    if no_src:
        near = sorted({k for s in segs for k in s
                       if k in ("source", "src", "clip", "filename", "input")})
        hint = (f' — found "{near[0]}" instead' if near else "")
        fails.append(
            f"{len(no_src)} segment(s) do not name their source file{hint}. "
            f"Use \"file\" (or \"path\"): gate_clearance reads it to decide "
            f"whether this footage needs a publication answer at all, and "
            f"coverage.py groups screen time by it. Neither errors without it — "
            f"they both just go quiet, which is how a cut shipped with the "
            f"clearance gate green and nothing behind it")

    bad_dur = [s.get("id") for s in segs
               if not isinstance(s.get("dur"), (int, float)) or s.get("dur", 0) <= 0]
    if bad_dur:
        fails.append(f"segment(s) {bad_dur[:5]} have no positive \"dur\" — "
                     f"coverage.py sums it for screen time per subject")

    summed = sum(float(s.get("dur") or 0) for s in segs)
    det["total_summed_s"] = round(summed, 2)
    if isinstance(tl.get("total"), (int, float)):
        det["total_declared_s"] = round(float(tl["total"]), 2)
        if abs(float(tl["total"]) - summed) > 0.15:
            fails.append(
                f"timeline.json says total {tl['total']:.2f}s but its segments "
                f"sum to {summed:.2f}s — one of them is stale, and every caption "
                f"timed against this file is off by the difference")
    return fails, det


# ── G18: pacing — is any shot too short to register? ──

def _timeline_segments(work_dir):
    """[(id, file, start, dur)] from timeline.json, or None if there is none.

    `start` is trusted when written and accumulated from `dur` when it is not:
    the template path writes it, and a build that only wrote durations still
    lands in the right order, which is all either caller needs.
    """
    p = os.path.join(work_dir or ".", "timeline.json")
    if not os.path.exists(p):
        return None
    try:
        segs = json.load(open(p, encoding="utf-8")).get("segments")
    except (ValueError, OSError):
        return None                       # gate_timeline reports the parse error
    if not isinstance(segs, list) or not segs:
        return None
    out, t = [], 0.0
    for s in segs:
        try:
            dur = float(s.get("dur") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        start = s.get("start")
        start = float(start) if isinstance(start, (int, float)) else t
        out.append((str(s.get("id") or "?"),
                    str(s.get("file") or s.get("path") or ""), start, dur))
        t = start + dur
    return out


def gate_pacing(work_dir):
    """A shot nobody can register is a defect, not a style choice.

    review.py has printed shortest_s from the day it was written and, in its own
    words, grades nothing. That is exactly what plan.py did with MIN_CAPTION_S
    — carried as advice, enforced by nobody — until a 0.75s caption shipped with
    every gate green. The same shape, one field over.

    The floor comes from measurement, not taste: every finished timeline in
    reach on 2026-08-25 — six cuts across three folders — had a shortest shot of
    1.30 1.40 1.50 1.70 2.30 2.30, and the beat-synced running-vlog reference
    bottoms out at 1.50s. The round-B build the viewer called 「很不順、跳」 had
    a 0.20s shot. 1.2 sits under everything anybody kept, so this fires on
    "nobody has done this and got away with it", not on a fast cut.

    Deliberately NOT a cuts-per-second ceiling. At min_shot_s=1.2 every legal
    shot already forces cuts/s <= 0.83, so a ceiling near 0.8 would catch almost
    nothing the floor missed — and the kept cuts run 0.24-0.45 against 0.56 for
    the rejected one, a 24% gap that no six-sample threshold should be driven
    through. A gate that misfires once gets loosened, and a loosened gate stops
    catching anything while still looking like protection. review.py keeps
    printing cuts_per_s where a person can weigh it.
    """
    fails, det = [], {}
    segs = _timeline_segments(work_dir)
    if segs is None:
        det["pacing"] = "no timeline.json (single-video path writes none)"
        return fails, det
    floor = house(work_dir).get("pacing", {}).get("min_shot_s", 1.2)
    det["min_shot_s"] = floor
    det["segments"] = len(segs)
    real = [(i, f, d) for i, f, _s, d in segs if d > 0]
    if not real:
        return fails, det
    det["shortest_s"] = round(min(d for _i, _f, d in real), 2)
    total = sum(d for _i, _f, d in real)
    if total > 0:
        det["cuts_per_s"] = round(len(real) / total, 2)   # printed, not graded
    short = sorted(((d, i, f) for i, f, d in real if d < floor))
    if short:
        named = "; ".join(f"{i} {d:.2f}s" + (f" ({os.path.basename(f)})" if f else "")
                          for d, i, f in short[:3])
        fails.append(
            f"{len(short)} shot(s) under {floor}s: {named} — nothing in this "
            f"repo's finished work has gone below 1.3s, and the cut a viewer "
            f"called 「很不順、跳」 had a 0.20s shot. If this speed is the point, "
            f"say so: house_style.local.json pacing.min_shot_s, which gates.py "
            f"prints as an override")
    return fails, det


# ── G19: monologue — was a continuous take left as one performance? ──

def gate_monologue(work_dir):
    """Somebody talking to camera is a performance, not a shot pool.

    Round B, 2026-08-23: the footage was chosen because it held one 63-second
    take of somebody talking. Four drivers kept 38.2s in 3 pieces, 28.7s in 5,
    10.2s in 11, and 6.0s — and those four numbers fall in exactly the order the
    viewer ranked the videos, which no other measurement on that page does. The
    one he called 「很不順、跳，口播被截掉很多」 is the eleven-piece one.

    Mean piece length separates them about six-fold — 12.7s and 5.7s for the two
    that worked, 0.93s for the one that did not. That gap is why this is a gate
    while cuts_per_s is not: nobody chops a monologue into second-long confetti
    on purpose, so there is no legitimate build sitting near the threshold.

    Scope is deliberately narrow. A source only counts as a monologue while a
    VERBATIM caption (sync.verbatim_styles) sits over it, so an event cut with
    no speech never reaches the check and a B-roll clip reused all afternoon is
    not a monologue. Both exemptions are load-bearing: round A of the same
    benchmark had zero Speech captions across three builds.
    """
    fails, det = [], {}
    if _decision(work_dir, "captions") == "deferred":
        return [], {"deferred": "captions deferred by decisions.json"}
    segs = _timeline_segments(work_dir)
    if segs is None:
        det["monologue"] = "no timeline.json (single-video path writes none)"
        return fails, det

    hs = house(work_dir)
    verbatim = set(hs.get("sync", {}).get("verbatim_styles", ["Speech"]))
    min_piece = hs.get("monologue", {}).get("min_piece_s", 1.5)
    max_pieces = hs.get("monologue", {}).get("max_pieces", 6)
    det["min_piece_s"], det["max_pieces"] = min_piece, max_pieces

    _ass, rows = _dialogues(work_dir)
    spans = [(r["start"], r["end"]) for r in rows if r["style"] in verbatim]
    if not spans:
        det["monologue"] = ("no verbatim captions — nothing here is a "
                            "monologue to protect")
        return fails, det

    # a segment is part of a monologue while a verbatim caption overlaps it
    takes = {}
    for sid, f, start, dur in segs:
        if dur <= 0 or not f:
            continue
        if not any(a < start + dur and b > start for a, b in spans):
            continue
        takes.setdefault(f, []).append((sid, dur))

    det["takes"] = {os.path.basename(f): {"pieces": len(v),
                                          "kept_s": round(sum(d for _i, d in v), 1)}
                    for f, v in takes.items()}

    for f, pieces in sorted(takes.items()):
        name = os.path.basename(f)
        kept = sum(d for _i, d in pieces)
        if len(pieces) > max_pieces:
            fails.append(
                f"{name} is spoken over and cut into {len(pieces)} pieces "
                f"(house max {max_pieces}), keeping {kept:.1f}s at "
                f"{kept / len(pieces):.2f}s a piece — the build a viewer called "
                f"「口播被截掉很多」 was 11 pieces at 0.93s, against 3 pieces at "
                f"12.7s for the one he had no complaints about. Let the take be "
                f"one thing and cut B-roll around it")
        tiny = sorted(d for _i, d in pieces if d < min_piece)
        if tiny:
            fails.append(
                f"{name} has {len(tiny)} spoken fragment(s) under {min_piece}s "
                f"(shortest {tiny[0]:.2f}s) — a piece that short cannot carry a "
                f"sentence, so the words land in the middle of a cut")
    return fails, det


GATES = [
    ("Timeline", lambda v, w: gate_timeline(w)),
    ("Pacing", lambda v, w: gate_pacing(w)),
    ("Monologue", lambda v, w: gate_monologue(w)),
    ("Decisions", gate_decisions),
    ("Audio", gate_audio),
    ("AudioPolicy", gate_audio_policy),
    ("MusicBed", gate_music_bed),
    ("Duck", gate_duck),
    ("Dwell", lambda v, w: gate_caption_dwell(w)),
    ("Deliverables", gate_deliverables),
    ("CoverColour", gate_cover_colour),
    ("Cover", lambda v, w: gate_cover(v, w)),
    ("Captions", lambda v, w: gate_captions(w)),
    ("Typography", lambda v, w: gate_typography(w)),
    ("Structure", lambda v, w: gate_structure(v, w)),
    ("Sync", lambda v, w: gate_sync(w)),
    ("Pill", lambda v, w: gate_pill(w)),
    ("Delivery", lambda v, w: gate_delivery(v, w)),
    ("Clearance", lambda v, w: gate_clearance(w)),
]


DELIVERY = "delivery.json"


def load_delivery(work_dir):
    """WORK_DIR/delivery.json — the staged set and where it is going.

    Layer three of "you cannot ship what was not gated". The first two layers
    check AFTER the fact: the build log makes a missing gate run visible, and
    the Claude Code Stop hook refuses to end a turn on an ungated render. Both
    are still checks beside the door. This one moves the door: the deliverables
    are BUILT into the work dir under staging names, and the only thing in the
    toolchain that copies them out to the project's first level — under the
    names a person would post — is a gate run that came back 0.

    Forgetting to gate therefore does not produce an unchecked video. It
    produces no video at all, which is a failure that reports itself.

        {"dir": "..",                        # relative to WORK_DIR, or absolute
         "files": {"vp_music.mp4":   "devjam-recap.mp4",
                   "vp_nomusic.mp4": "devjam-recap-nomusic.mp4",
                   "cover.jpg":      "cover.jpg"}}

    Declared as an artifact rather than inferred from filenames for the reason
    every other contract here is a file: a convention cannot be read by a gate,
    and a rename that breaks an inference is silent.

    Absent = the old behaviour, gate in place and publish nothing. Nothing that
    worked before needs to change; template mode's hand-written render scripts
    keep working exactly as they did.
    """
    p = os.path.join(work_dir or ".", DELIVERY)
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (ValueError, OSError):
        return None
    files = d.get("files")
    if not isinstance(files, dict) or not files:
        return None
    return {"dir": d.get("dir", ".."), "files": files}


def publish(work_dir, delivery):
    """Move the staged set to the project's first level. ONLY called on exit 0.

    Moved, not copied: two files with the same content and different names is
    how a stale cut gets posted. The move is done one file at a time and any
    failure is reported rather than swallowed — a half-published set is worse
    than an unpublished one, and the gates that check the SET (Deliverables)
    have already run against the staging dir by this point.
    """
    wd = os.path.abspath(work_dir or ".")
    dest = delivery["dir"]
    dest = dest if os.path.isabs(dest) else os.path.normpath(os.path.join(wd, dest))
    os.makedirs(dest, exist_ok=True)
    moved, problems = [], []
    for staged, final in sorted(delivery["files"].items()):
        src = os.path.join(wd, staged)
        if not os.path.exists(src):
            problems.append(f"{staged} was declared in {DELIVERY} but is not in "
                            f"the work dir")
            continue
        try:
            # shutil.move, not os.replace: footage and work dirs regularly live
            # on an external drive while the project does not, and os.replace
            # raises EXDEV across filesystems — which would have failed the
            # publish of a delivery that had just passed every gate.
            shutil.move(src, os.path.join(dest, final))
        except OSError as e:
            problems.append(f"{staged} -> {final}: {e}")
            continue
        moved.append(final)
    return moved, problems, dest


def append_build_log(video, work_dir, results, published=None):
    """Append this gate run to WORK_DIR/build_log.jsonl + BUILD_LOG.md.

    Written by gates.py rather than by a separate command on purpose: a logging
    step someone has to remember is a logging step that gets skipped, which is
    the same lesson that put the lint on buildkit's import.

    What goes in is only what the machine can PROVE — durations, sizes, gate
    verdicts, and how many attempts it took. Token counts and the name of the
    model driving the edit are not observable from here; an agent that wants to
    record them writes them into notes.json and they are copied through, clearly
    marked as self-reported.
    """
    import datetime
    import platform
    wd = work_dir or "."
    jl = os.path.join(wd, "build_log.jsonl")
    attempt = 1
    if os.path.exists(jl):
        with open(jl, encoding="utf-8") as f:
            attempt = sum(1 for line in f if line.strip()) + 1

    def probe(p):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate",
                 "-show_entries", "format=duration,bit_rate",
                 "-of", "json", p], capture_output=True, text=True).stdout
            j = json.loads(out)
            st, fm = (j.get("streams") or [{}])[0], j.get("format", {})
            return {"w": st.get("width"), "h": st.get("height"),
                    "duration_s": round(float(fm.get("duration", 0)), 2),
                    "bitrate_kbps": round(int(fm.get("bit_rate", 0)) / 1000),
                    "size_mib": round(os.path.getsize(p) / 1048576, 1)}
        except Exception:                                     # noqa: BLE001
            return {}

    failures = {r["name"]: r["failures"] for r in results if r["failures"]}
    entry = {
        "attempt": attempt,
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "output": os.path.basename(video),
        "verdict": ("blocked" if failures else
                    "incomplete" if any(r["pass"] and r["deferred"] for r in results)
                    else "shippable"),
        "gates_run": len(results),
        # The names that left the work dir. The Stop hook reads this: a file
        # published under a different name than the one gated would otherwise
        # look exactly like a render nobody checked.
        **({"published": sorted(published)} if published else {}),
        "gates_failed": sorted(failures),
        "failures": failures,
        "video": probe(video),
        "host": {"platform": platform.platform(), "hw_encoder": _hw_encoder()},
    }
    for name in ("timeline.json", "words.json", "decisions.json"):
        p = os.path.join(wd, name)
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            continue
        if name == "timeline.json":
            entry["segments"] = len(data.get("segments", []))
            entry["sources_used"] = len({s.get("file") for s in
                                         data.get("segments", [])})
        elif name == "words.json":
            entry["asr_words"] = len(data)
        else:
            entry["decisions"] = data
    try:
        import coverage as _cov
        rep = _cov.report(wd)
        if rep:
            entry["coverage"] = rep
    except Exception:                                         # noqa: BLE001
        pass

    notes = os.path.join(wd, "notes.json")
    if os.path.exists(notes):
        try:
            entry["self_reported"] = json.load(open(notes, encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            pass

    with open(jl, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    rows = [json.loads(x) for x in open(jl, encoding="utf-8") if x.strip()]
    md = ["# Build log", "",
          f"`{os.path.basename(os.path.abspath(wd))}` — {len(rows)} gate run(s). "
          "Written by gates.py on every run; a run that is not logged did not happen.",
          "",
          "| # | when | output | verdict | gates failed |",
          "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['attempt']} | {r['at'][:19].replace('T', ' ')} | "
                  f"{r['output']} | {r['verdict']} | "
                  f"{', '.join(r['gates_failed']) or '—'} |")
    last = rows[-1]
    v = last.get("video", {})
    md += ["", "## Latest", "",
           f"- **{v.get('w')}×{v.get('h')}**, {v.get('duration_s')}s, "
           f"{v.get('bitrate_kbps')} kbps, {v.get('size_mib')} MiB",
           f"- segments: {last.get('segments', '—')} from "
           f"{last.get('sources_used', '—')} source clips",
           f"- ASR words on the timeline: {last.get('asr_words', '—')}",
           f"- encoder: {last['host']['hw_encoder']}  ·  {last['host']['platform']}"]
    if last.get("self_reported"):
        md += ["", "### Self-reported (NOT measured here)", ""]
        for k, val in last["self_reported"].items():
            md.append(f"- {k}: {val}")
    else:
        # Say the hole is there. This section used to be omitted entirely when
        # notes.json was absent, and SKILL.md's "write them in IF YOU WANT them
        # kept" made it optional, so three agents in a row recorded nothing and
        # a benchmark could not answer what any of it cost. A missing number
        # that is printed as missing gets filled in; one that is silently
        # skipped does not. Still not a gate: what a run cost has no bearing on
        # whether the video is shippable.
        md += ["", "### Self-reported (NOT measured here)", "",
               "- none recorded — a build script cannot observe the model name, "
               "token cost or wall-clock time. Write them to "
               "`WORK_DIR/notes.json` and they land here, labelled as claims."]
    open(os.path.join(wd, "BUILD_LOG.md"), "w", encoding="utf-8").write(
        "\n".join(md) + "\n")
    return entry


def _hw_encoder():
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True).stdout
        return "h264_videotoolbox" if "h264_videotoolbox" in out else "libx264"
    except OSError:
        return "unknown"


def repeat_history(work_dir, results, this_attempt=None):
    """{gate: (streak, previous_failures, identical)} for gates failing again.

    A gate says what is wrong with the cut. It has never said what the LAST
    attempt was told, and that turns out to be the difference between descending
    a gradient and guessing. On 2026-08-22 MusicBed rejected four renders in a
    row; the measured head moved 15.0s -> 3.5s -> 1.5s -> 1.5s, and the last two
    were the same number because that attempt changed nothing that mattered. The
    agent could not see the sequence — every message it got was word for word
    the one before — so it kept paying a full render per guess.

    Everything needed was already on disk: gates.py writes build_log.jsonl and
    reads it back to number the attempts. This reads two lines further.
    """
    p = os.path.join(work_dir or ".", "build_log.jsonl")
    if not os.path.exists(p):
        return {}
    try:
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except (ValueError, OSError):
        return {}
    # the run being reported is already appended by the time this is called
    if this_attempt is not None:
        rows = [r for r in rows if r.get("attempt") != this_attempt]
    if not rows:
        return {}
    out = {}
    for r in results:
        if r["pass"]:
            continue
        prev = rows[-1].get("failures", {}).get(r["name"])
        if not prev:
            continue
        streak = 1
        for row in reversed(rows):
            if row.get("failures", {}).get(r["name"]):
                streak += 1
            else:
                break
        out[r["name"]] = (streak, prev, list(prev) == list(r["failures"]))
    return out


def run(video, work_dir):
    results = []
    for name, fn in GATES:
        try:
            fails, det = fn(video, work_dir)
        except Exception as e:                                # noqa: BLE001
            fails, det = [f"gate crashed: {e}"], {}
        results.append({"name": name, "pass": not fails, "details": det,
                        # "deferred" = work still owed (captions postponed).
                        # end_card "off" is a TERMINAL decision with a written
                        # why, not owed work — it must not hold exit at 2.
                        "deferred": bool(det.get("deferred")) or
                                    str(det.get("hook", "")).startswith("deferred"),
                        "failures": fails})
    return results


def preflight(work_dir):
    """Print the build checklist derived from house_style.json.

    The gates tell an agent it failed. This tells it what to do first — which is
    the difference between one rebuild and five.
    """
    hs = house(work_dir)
    c, p, cv, st, bl, sy = (hs["captions"], hs["pill"], hs["cover"],
                            hs["structure"], hs["bilingual"], hs["sync"])
    ap = hs.get("audio_policy", {"artifact": "audio_policy.json",
                                 "mute_attenuation_db": -20.0,
                                 "min_applied_db": 10.0})
    L = [
        "=" * 62, "  HOUSE STYLE — build to this, then gates.py checks it", "=" * 62,
        f"\n  FONT  {hs['font']['family']}  (modules/title.py _find_font)",
        "\n  CAPTIONS   .ass, every line an explicit {\\an5\\pos(540,"
        f"{int(c['baseline_pct'] * FRAME_H)})}}",
        f"    min dwell {c.get('min_dwell_s', 1.8)}s — shorter than this and "
        f"nobody finishes reading it",
    ]
    for n, s in c["styles"].items():
        L.append(f"    {n:<7} {s['size']}pt  outline {s['outline']}  "
                 f"shadow >={s['shadow_min']}  align {s['alignment']}")
    L += [
        f"    fades: {'FORBIDDEN — hard cut' if c['forbid_fade'] else 'allowed'}",
        "    declare every style in layout.json as caption / pill / free",
        f"\n  PILL       {p['method']} via title.py render_title_png("
        f"pct={p['centre_pct']}, font_size={p['font_size']})",
        f"    NOT drawn in ASS. render_title_png shrinks to <= "
        f"{p['max_w_ratio']:.0%} of frame for you.",
        f"    bake to a FINITE alpha clip before overlay; fades: "
        f"{'FORBIDDEN' if p['forbid_fade'] else 'allowed'}",
        f"    artifacts required: pills.json + pills/*.png",
        f"\n  COVER      <= {cv['max_title_lines']} lines, title <= "
        f"{cv['title_max_w_ratio']:.0%} of frame width",
        f"    subtitle sized to MATCH the title width (tol "
        f"{cv['subtitle_width_match_tol_px']}px)",
        "    burn as an overlay on frame 1, never a prepended segment",
        "    build via cover.build() so cover_meta.json exists",
        f"\n  STRUCTURE  a '{st['hook_style']}' caption starting before "
        f"{st['hook_must_start_before_s']}s",
        f"    end card: {st['end_card_artifact']}, and the video must END on it",
        f"\n  PACING     no shot shorter than "
        f"{hs.get('pacing', {}).get('min_shot_s', 1.2)}s",
        f"    nothing kept in this repo has gone under 1.3s; the cut a viewer "
        f"called 「很不順、跳」 had a 0.20s shot",
        f"    cuts/s is NOT gated — review.py prints it for a person to weigh",
        f"\n  MONOLOGUE  one take carrying "
        f"{'/'.join(sy['verbatim_styles'])} captions stays a performance:",
        f"    at most {hs.get('monologue', {}).get('max_pieces', 6)} pieces, "
        f"none under {hs.get('monologue', {}).get('min_piece_s', 1.5)}s",
        f"    cut B-roll AROUND a long take, do not cut the take into it — "
        f"11 pieces at 0.93s lost to 3 at 12.7s on the same footage",
        f"\n  SYNC       any caption styled {'/'.join(sy['verbatim_styles'])} is a "
        f"VERBATIM claim and gets checked",
        f"    against work_dir/words.json in TIMELINE time "
        f"[{{text,start,end,probability}}]",
        f"    remap the ASR words to the CUT timeline and regenerate them whenever a "
        f"cut point moves",
        f"    authored lines belong in Note/Hook, which are not sync-checked",
        "\n  DECISIONS  WORK_DIR/decisions.json is REQUIRED — the user's calls:",
        # Generated from REQUIRED_DECISIONS, never typed out twice: a hardcoded
        # copy of this list is how a new required key ships without the
        # checklist that is supposed to announce it.
        *[f"    {k}: {' | '.join(v['allowed']):<24}"
          f"({v['needs_why']} needs a written why)"
          for k, v in REQUIRED_DECISIONS.items()],
        "    Never default these. A 'why' must be one the user actually agreed to.",
        f"\n  AUDIO      policy 'selective' -> WORK_DIR/{ap['artifact']}, one row per",
        "    segment: keep = VOICE | SFX | FOOD | null, each with a why.",
        f"    muted spans attenuated {ap['mute_attenuation_db']:.0f} dB (NOT silence — the",
        "    no-music sibling is what the bed gets measured against), and they must",
        f"    measure >= {ap['min_applied_db']:.0f} dB below the kept ones on the finished file.",
        "    evidence: python3 modules/audio_scout.py WORK_DIR/segments",
        "\n  EXIT       0 shippable / 1 something is broken / 2 deferred, NOT finished",
        f"\n  BILINGUAL  {'REQUIRED' if bl['required'] else 'off'}"
        + (f" — every caption needs \\N{{\\fs{bl['english_font_size']}"
           f"\\c{bl['english_colour']}}}English" if bl["required"] else
           " (set required:true in work_dir/house_style.local.json to turn on)"),
    ]
    if hs.get("_overrides"):
        L.append(f"\n  ⚠ PROJECT OVERRIDES ACTIVE: {', '.join(hs['_overrides'])}")
    L += ["\n" + "=" * 62,
          "  then:  python3 gates.py FINAL.mp4 --work-dir WORK_DIR", "=" * 62, ""]
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--preflight", action="store_true",
                    help="print the house-style build checklist and exit")
    args = ap.parse_args()
    if args.preflight:
        preflight(args.work_dir or ".")
        sys.exit(0)
    if not args.video:
        ap.error("video is required (or pass --preflight)")
    wd = args.work_dir or os.path.dirname(os.path.abspath(args.video))

    results = run(args.video, wd)

    # Publish BEFORE the report is printed, so what the reader sees is the
    # delivery as it now exists on disk — and only when the verdict is a clean
    # 0. A deferred run (exit 2) publishes nothing on purpose: "nothing is
    # broken" and "this is finished" are the two sentences this repo has spent
    # the most effort keeping apart, and a file sitting at the project's first
    # level says the second one.
    delivery = load_delivery(wd)
    moved, move_problems = [], []
    clean = not any(r["failures"] for r in results) and not any(
        r["pass"] and r["deferred"] for r in results)
    dest = None
    if delivery and clean:
        moved, move_problems, dest = publish(wd, delivery)
    # Publishing is NOT appended to `results`: `results` is the gate list, its
    # length is logged as gates_run, and a twentieth entry that is not one of
    # the nineteen gate functions would make that number a small lie.

    # Log the file where it now IS. append_build_log ffprobes the path it is
    # given, and probe() swallows its own errors — so logging the staged path
    # after the set had been moved recorded "video": {} on exactly the runs
    # that succeeded. The successful runs are the ones whose size, duration and
    # bitrate anyone would later want.
    logged_video = args.video
    if moved and dest:
        final = (delivery["files"] or {}).get(os.path.basename(args.video))
        if final and os.path.exists(os.path.join(dest, final)):
            logged_video = os.path.join(dest, final)

    try:
        logged = append_build_log(logged_video, wd, results, published=moved)
    except Exception as e:                                    # noqa: BLE001
        logged = None
        print(f"  (build log not written: {e})", file=sys.stderr)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 62)
        print("  SHIPPING GATES")
        print("=" * 62)
        again = repeat_history(wd, results,
                               logged.get("attempt") if isinstance(logged, dict)
                               else None)
        for r in results:
            tag = ("⏸ DEFERRED" if r["pass"] and r["deferred"]
                   else "✅ PASS" if r["pass"] else "❌ FAIL")
            print(f"\n  [{tag}] {r['name']}")
            for k, v in r["details"].items():
                print(f"     {k}: {v}")
            for f in r["failures"]:
                print(f"     ❌ {f}")
            if r["name"] in again:
                streak, prev, identical = again[r["name"]]
                print(f"     ⟳ {streak} attempts in a row on this gate.")
                if identical:
                    print("       IDENTICAL to last time — whatever you changed "
                          "did not move this measurement. Re-read the message "
                          "for what it asks for, or record a decision; another "
                          "render of the same thing costs the same and says the "
                          "same.")
                else:
                    for f in prev:
                        print(f"       last time: {f[:150]}")
        bad = sum(len(r["failures"]) for r in results)
        defer = [r["name"] for r in results if r["pass"] and r["deferred"]]
        print("\n" + "=" * 62)
        if bad:
            print(f"  ❌ BLOCKED — {bad} failure(s)")
        elif defer:
            print(f"  ⏸ INCOMPLETE — nothing is broken, but {len(defer)} gate(s) "
                  f"were deferred by an explicit decision:")
            print(f"     {', '.join(defer)}")
            print("     This is NOT a finished delivery. Say so to the user.")
        else:
            print("  ✅ SHIPPABLE")
        if moved:
            print(f"  📦 published to {dest}:")
            for f in moved:
                print(f"     {f}")
        elif delivery and not clean:
            print(f"  📦 NOT published — {len(delivery['files'])} staged file(s) "
                  f"stay in the work dir until this comes back 0.")
        for f in move_problems:
            print(f"  ❌ publish: {f}")
        if logged:
            print(f"  build log: attempt #{logged['attempt']} → "
                  f"{os.path.join(wd, 'BUILD_LOG.md')}")
        print("=" * 62)
        # Advisory, never blocking. The gates find defects and are blind to
        # OMISSION: a build passed all twelve while half the subjects had two
        # shots and the rest four, and a person had to spot it.
        try:
            import coverage as _cov
            print(_cov.render(_cov.report(wd)), end="")
        except Exception:                                     # noqa: BLE001
            pass
        print()
    if any(r["failures"] for r in results) or move_problems:
        sys.exit(1)                       # something is wrong
    if any(r["pass"] and r["deferred"] for r in results):
        sys.exit(2)                       # nothing wrong, but not finished
    sys.exit(0)


if __name__ == "__main__":
    main()
