#!/usr/bin/env python3
"""Regression test for the shipping gates.

Each case reconstructs a defect that actually shipped and asserts the gate
catches it. Without this, the gates themselves can rot silently — a threshold
edited to make a build pass would go unnoticed, which is the same failure mode
they exist to prevent.

    python3 tests/test_gates.py
"""
import json
import os
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

import gates  # noqa: E402

W, H, FPS = 1080, 1920, 30
PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def mkvideo(path, dur, audio_expr="sin(2*PI*220*t)*0.2", tail_silence=0.0):
    """Solid-colour video with a tone; optionally silent for the last N seconds."""
    if tail_silence:
        af = (f"volume='if(gt(t,{dur - tail_silence}),0,1)':eval=frame")
    else:
        af = "anull"
    subprocess.run(
        ["ffmpeg", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=slategray:s={W}x{H}:r={FPS}:d={dur}",
         "-f", "lavfi", "-i", f"aevalsrc={audio_expr}:s=48000:d={dur}",
         "-af", af, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-fps_mode", "cfr", "-shortest", "-y", path],
        check=True, capture_output=True)
    return path


ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Note,演示斜黑体,76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(path, body):
    open(path, "w", encoding="utf-8").write(ASS_HEAD + body + "\n")


def main():
    print("\nshipping-gate regression\n" + "-" * 46)
    with tempfile.TemporaryDirectory() as d:
        # ---- Audio: silent ending (shipped twice) --------------------
        v = mkvideo(os.path.join(d, "silent_end.mp4"), 8.0, tail_silence=4.0)
        fails, det = gates.gate_audio(v)
        check("silent ending is caught",
              any("silent ending" in f or "dead air" in f for f in fails), str(det))

        v_ok = mkvideo(os.path.join(d, "ok.mp4"), 8.0)
        fails_ok, _ = gates.gate_audio(v_ok)
        check("clean audio passes", not fails_ok, str(fails_ok))

        # ---- Cover: missing entirely (shipped) ----------------------
        empty = os.path.join(d, "nocover")
        os.makedirs(empty, exist_ok=True)
        fails, _ = gates.gate_cover(v_ok, empty)
        check("missing cover is caught", any("no cover" in f for f in fails))

        # ---- Captions: no \pos -> falls back to 50% (shipped) -------
        import json as _json
        wd = os.path.join(d, "wd")
        os.makedirs(wd, exist_ok=True)
        _json.dump({"Note": "caption"}, open(os.path.join(wd, "layout.json"), "w"))
        write_ass(os.path.join(wd, "captions.ass"),
                  "Dialogue: 4,0:00:01.00,0:00:03.00,Note,,0,0,0,,早上先跟戰友會合")
        fails, det = gates.gate_captions(wd)
        check("caption with no \\pos is caught",
              any("declared anchor" in f for f in fails), str(det))

        # ---- Captions: overflow past the safe area (shipped) --------
        write_ass(os.path.join(wd, "captions.ass"),
                  "Dialogue: 4,0:00:01.00,0:00:03.00,Note,,0,0,0,,"
                  "{\\an5\\pos(540,1344)}這一行故意寫得非常長長到一定會超出安全區範圍")
        fails, det = gates.gate_captions(wd)
        check("caption overflow is caught",
              any("wider than the safe area" in f for f in fails), str(det))

        # ---- Captions: nested colour tags (shipped) -----------------
        write_ass(os.path.join(wd, "captions.ass"),
                  "Dialogue: 4,0:00:01.00,0:00:03.00,Note,,0,0,0,,"
                  "{\\an5\\pos(540,1344)}全新的 {\\1c&H0000D7FF&}{\\1c&H0000D7FF&}LiteRT"
                  "{\\1c&H00FFFFFF&}-LM.js")
        fails, det = gates.gate_captions(wd)
        check("nested colour override is caught",
              any("nested colour" in f for f in fails), str(det))

        # ---- Captions: a correct file passes ------------------------
        write_ass(os.path.join(wd, "captions.ass"),
                  "Dialogue: 4,0:00:01.00,0:00:03.00,Note,,0,0,0,,"
                  "{\\an5\\pos(540,1344)}早上先跟戰友會合")
        fails, det = gates.gate_captions(wd)
        check("correct caption file passes", not fails, str(fails))

        # ---- Captions: layout must be DECLARED, not guessed by name --
        write_ass(os.path.join(wd, "captions.ass"),
                  "Dialogue: 4,0:00:01.00,0:00:03.00,Note,,0,0,0,,"
                  "{\\an5\\pos(540,1344)}早上先跟戰友會合")
        lp = os.path.join(wd, "layout.json")
        if os.path.exists(lp):
            os.remove(lp)
        fails, det = gates.gate_captions(wd)
        check("undeclared style is caught",
              any("not declared in layout.json" in f for f in fails), str(det))

        _json.dump({"Note": "pill"}, open(lp, "w"))
        fails, det = gates.gate_captions(wd)
        check("style at the wrong declared anchor is caught",
              any("declared anchor" in f for f in fails), str(det))

        _json.dump({"Note": "caption"}, open(lp, "w"))
        fails, det = gates.gate_captions(wd)
        check("correctly declared layout passes", not fails, str(fails))

        # ---- MusicBed: the bed must not die before the video does ----
        # Shipped: the music was gone for the last 2.7s while gate_audio passed,
        # because gate_audio measures the finished MIX and speech was still
        # playing over the silence. Only the music/no-music PAIR reveals it.
        def mkpair(sub, bed_until=None):
            """A -nomusic file and its music sibling, the bed a distinct tone."""
            dd = os.path.join(d, sub)
            os.makedirs(dd, exist_ok=True)
            dur, speech = 8.0, "sin(2*PI*220*t)*0.20"
            bed = "sin(2*PI*1320*t)*0.10"
            if bed_until is not None:
                # comma escaped: lavfi splits options on bare commas
                bed += rf"*lt(t\,{bed_until})"
            mkvideo(os.path.join(dd, "clip-nomusic.mp4"), dur, speech)
            mkvideo(os.path.join(dd, "clip-standin.mp4"), dur, f"{speech}+{bed}")
            return os.path.join(dd, "clip-standin.mp4")

        v = mkpair("bed_dies", bed_until=5.0)          # 3s of dead tail
        fails, det = gates.gate_music_bed(v, d)
        check("music bed dying before the end is caught",
              any("goes silent" in f for f in fails), str(det))

        v = mkpair("bed_ok")                            # bed runs to the last sample
        fails, det = gates.gate_music_bed(v, d)
        check("music bed that plays to the end passes", not fails, str(det))

        # ---- the bed has to ESTABLISH, not just survive ----------------
        # "why is there no music at the start" was reported on two separate
        # edits and passed every gate both times, because everything above
        # watches the END. Measured as MASKING: a bed 20 dB under a loud room is
        # present in the arithmetic and gone to the ear.
        def mkhead(sub, bed_from):
            dd = os.path.join(d, sub)
            os.makedirs(dd, exist_ok=True)
            room = "sin(2*PI*220*t)*0.22"
            bed = rf"sin(2*PI*1320*t)*0.20*gt(t\,{bed_from})"
            mkvideo(os.path.join(dd, "clip-nomusic.mp4"), 8.0, room)
            mkvideo(os.path.join(dd, "clip-standin.mp4"), 8.0, f"{room}+{bed}")
            return os.path.join(dd, "clip-standin.mp4")

        v = mkhead("head_silent", 3.0)
        fails, det = gates.gate_music_bed(v, d)
        check("a silent opening is caught",
              any("no audible music" in f for f in fails), str(det))

        v = mkhead("head_ok", 0.0)
        fails, det = gates.gate_music_bed(v, d)
        check("music from the first frame passes", not fails, str(det))

        # A hook that deliberately holds the bed back is legal ON RECORD only.
        wd7 = os.path.join(d, "head_silent")
        json.dump({"loudness": {"value": "original", "why": "x"},
                   "captions": "on", "end_card": "on",
                   "music": {"head": "cold_open",
                             "why": "opens on a line that a bed would fight"}},
                  open(os.path.join(wd7, "decisions.json"), "w"))
        fails, det = gates.gate_music_bed(mkhead("head_silent", 3.0), wd7)
        check("a declared cold open is allowed", not fails, str(det))

        # The no-music version is not checked against itself.
        fails, det = gates.gate_music_bed(
            os.path.join(d, "bed_ok", "clip-nomusic.mp4"), d)
        check("the -nomusic file itself is not gated", not fails, str(det))

        # Shipping the pair is the house rule, so a lone music file is a failure.
        lone = os.path.join(d, "lone")
        os.makedirs(lone, exist_ok=True)
        mkvideo(os.path.join(lone, "clip-standin.mp4"), 4.0)
        fails, det = gates.gate_music_bed(os.path.join(lone, "clip-standin.mp4"), d)
        check("a music version with no -nomusic sibling is a failure",
              any("nomusic" in f for f in fails), str(det))

        # ---- Decisions: the user's choices cannot be silently defaulted ----
        import json as _json
        dec = os.path.join(d, "dec")
        os.makedirs(dec, exist_ok=True)
        fails, det = gates.gate_decisions(None, dec)
        check("a missing decisions.json is a failure",
              any("no decisions.json" in f for f in fails), str(det))

        _json.dump({"loudness": "original", "captions": "on"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(None, dec)
        check("an incomplete decisions.json is a failure",
              any("no 'end_card'" in f for f in fails), str(det))

        _json.dump({"loudness": "-14LUFS", "captions": "on", "end_card": "on"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(None, dec)
        check("departing from the default with no reason is a failure",
              any("needs a 'why'" in f for f in fails), str(det))

        _json.dump({"loudness": {"value": "-14LUFS", "why": "published promo"},
                    "captions": "on", "end_card": "on",
                    "audio_policy": "selective"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(None, dec)
        check("a recorded, reasoned decision passes", not fails, str(fails))

        # 'full' is allowed but is the one that has to argue for itself: it is
        # what shipped 48s of restaurant hum under a music bed.
        _json.dump({"loudness": {"value": "-14LUFS", "why": "published promo"},
                    "captions": "on", "end_card": "on", "audio_policy": "full"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(None, dec)
        check("audio_policy 'full' with no reason is a failure",
              any("needs a 'why'" in f for f in fails), str(det))

        _json.dump({"loudness": "sortof", "captions": "on", "end_card": "on"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(None, dec)
        check("an out-of-range decision value is a failure",
              any("is not one of" in f for f in fails), str(det))

        # A deferral must be recorded to take effect — it cannot be assumed.
        _json.dump({"loudness": "original", "end_card": "on",
                    "captions": {"value": "deferred", "why": "v1 preview"}},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_captions(dec)
        check("a recorded caption deferral defers the caption gate",
              not fails and det.get("deferred"), str(det))

        _json.dump({"loudness": "original", "captions": "on", "end_card": "on"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_captions(dec)
        check("without a recorded deferral the caption gate still blocks",
              any(".ass" in f for f in fails), str(det))

        # ---- Deliverables: both versions + cover at the project root --
        dl = os.path.join(d, "deliver")
        os.makedirs(dl, exist_ok=True)
        mkvideo(os.path.join(dl, "x-standin.mp4"), 2.0)
        v = os.path.join(dl, "x-standin.mp4")
        fails, det = gates.gate_deliverables(v, d)
        check("music-only delivery is caught",
              any("no *-nomusic" in f for f in fails), str(det))

        mkvideo(os.path.join(dl, "x-nomusic.mp4"), 2.0)
        fails, det = gates.gate_deliverables(v, d)
        check("missing cover at the project root is caught",
              any("no cover" in f for f in fails), str(det))

        open(os.path.join(dl, "cover.jpg"), "wb").close()
        from PIL import Image as _I
        _I.new("RGB", (W, H)).save(os.path.join(dl, "cover.jpg"))
        fails, det = gates.gate_deliverables(v, d)
        check("a complete delivery passes", not fails, str(fails))

        nomusic_only = os.path.join(d, "nomusic_only")
        os.makedirs(nomusic_only, exist_ok=True)
        mkvideo(os.path.join(nomusic_only, "y-nomusic.mp4"), 2.0)
        _I.new("RGB", (W, H)).save(os.path.join(nomusic_only, "cover.jpg"))
        fails, det = gates.gate_deliverables(
            os.path.join(nomusic_only, "y-nomusic.mp4"), d)
        check("no-music-only delivery is caught",
              any("no music version" in f for f in fails), str(det))

        # ---- Cover subtitle colour is the house yellow ---------------
        import cover as _cov
        from PIL import Image as _Img
        for sub, gold, want_fail, label in [
            ("gold_ok", None, False, "house-yellow cover subtitle passes"),
            ("gold_bad", (255, 214, 0), True, "the old hard-coded gold is caught"),
        ]:
            cd = os.path.join(d, sub)
            os.makedirs(cd, exist_ok=True)
            im, _pt, _sp, _m = _cov.draw(
                _Img.new("RGB", (W, H), (20, 20, 30)), "5K 均速 4:51",
                "肚子痛還是平了紀錄", **({} if gold is None else {"gold": gold}))
            im.save(os.path.join(cd, "cover.jpg"), quality=94)
            fails, det = gates.gate_cover_colour(None, cd)
            check(label, bool(fails) == want_fail, str(det))

        # ---- Keyword gold: an all-white caption pass is a defect ------
        wd2 = os.path.join(d, "gold")
        os.makedirs(wd2, exist_ok=True)
        import json as _j
        _j.dump({"Speech": "caption"}, open(os.path.join(wd2, "layout.json"), "w"))
        white = ("Dialogue: 0,0:00:00.50,0:00:02.00,Speech,,0,0,0,,"
                 "{\\an5\\pos(540,1344)}今天跑了五公里\n")
        golded = ("Dialogue: 0,0:00:00.50,0:00:02.00,Speech,,0,0,0,,"
                  "{\\an5\\pos(540,1344)}均速{\\fs90\\c&H66DBF6&}4:51"
                  "{\\fs84\\c&HFFFFFF&}整\n" * 3)
        write_ass(os.path.join(wd2, "subtitles.ass"),
                  "Style: Speech,演示斜黑体,84,&H00FFFFFF,&H00FFFFFF,&H00000000,"
                  "&H64000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1\n" + white)
        fails, det = gates.gate_typography(wd2)
        check("an all-white caption pass (no gold spans) is caught",
              any("gold keyword" in f for f in fails), str(det))
        write_ass(os.path.join(wd2, "subtitles.ass"),
                  "Style: Speech,演示斜黑体,84,&H00FFFFFF,&H00FFFFFF,&H00000000,"
                  "&H64000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1\n" + golded)
        fails, det = gates.gate_typography(wd2)
        check("gold keyword spans at the locked colour pass",
              not any("gold" in f or "palette" in f for f in fails), str(fails))

        # ---- Duck: the bed must get out of the way of the speech -----
        # Reconstructs 2026-08-19: duck_mix keyed off an absolute amplitude, so
        # a room-distance speaker got 2 dB of duck while every gate stayed green.
        import numpy as np
        wd3 = os.path.join(d, "duck")
        os.makedirs(wd3, exist_ok=True)
        SR, DUR = 48000, 6.0
        t = np.arange(int(SR * DUR)) / SR
        # "speech": a burst in the middle third, quiet room tone either side
        voice = 0.02 + 0.30 * ((t > 2.0) & (t < 4.0))
        speech = (np.sin(2 * np.pi * 200 * t) * voice).astype(np.float32)
        music = (np.sin(2 * np.pi * 660 * t) * 0.25).astype(np.float32)

        def write_pair(tag, duck_lin):
            env = np.where((t > 2.0) & (t < 4.0), duck_lin, 1.0)
            for name, sig in (("-nomusic", speech), ("", speech + music * env)):
                raw = os.path.join(wd3, f"{tag}{name}.f32")
                np.repeat(sig[:, None], 2, axis=1).astype(np.float32).tofile(raw)
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y",
                     "-f", "lavfi", "-i", f"color=c=black:s=320x568:r=30:d={DUR}",
                     "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", raw,
                     "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                     "-c:a", "aac", "-shortest",
                     os.path.join(wd3, f"{tag}{name}.mp4")], check=True)
            return os.path.join(wd3, f"{tag}.mp4")

        shallow = write_pair("shallow", 10 ** (-2.0 / 20))     # only 2 dB
        fails, det = gates.gate_duck(shallow, wd3)
        check("a 2 dB duck under speech is caught",
              any("does not get out of the way" in f or "only drops" in f
                  for f in fails), str(det))

        for f in os.listdir(wd3):
            if f.endswith(".mp4") or f.endswith(".f32"):
                os.remove(os.path.join(wd3, f))
        deep = write_pair("deep", 10 ** (-11.0 / 20))          # the house depth
        fails, det = gates.gate_duck(deep, wd3)
        check("an 11 dB duck passes", not fails, str(det) + str(fails))

        # ---- Dwell: a caption nobody can finish reading ---------------
        wd4 = os.path.join(d, "dwell")
        os.makedirs(wd4, exist_ok=True)
        style = ("Style: Note,演示斜黑体,76,&H00FFFFFF,&H00FFFFFF,&H00000000,"
                 "&H64000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1\n")
        flash = ("Dialogue: 4,0:00:01.00,0:00:01.70,Note,,0,0,0,,"
                 "{\\an5\\pos(540,1344)}來不及看完\n")
        held = ("Dialogue: 4,0:00:01.00,0:00:03.40,Note,,0,0,0,,"
                "{\\an5\\pos(540,1344)}看得完\n")
        write_ass(os.path.join(wd4, "subtitles.ass"), style + flash)
        fails, det = gates.gate_caption_dwell(wd4)
        check("a 0.70s caption is caught", any("less than" in f for f in fails),
              str(det))
        write_ass(os.path.join(wd4, "subtitles.ass"), style + held)
        fails, det = gates.gate_caption_dwell(wd4)
        check("a 2.40s caption passes", not fails, str(fails))

        # ---- Cover module invariants --------------------------------
        import cover
        from PIL import Image
        try:
            cover.draw(Image.new("RGB", (W, H)), "一行\n兩行\n三行", "sub")
            three_line_raises = False
        except ValueError:
            three_line_raises = True
        check("3-line cover title is rejected", three_line_raises)

        # ---- Delivery: the two defects that survive every other gate ----
        # Both are invisible in a player and in every frame-level check. The
        # first renders frame 1 black in a feed; the second drifts lip-sync.
        wd5 = os.path.join(d, "wd5")
        os.makedirs(wd5, exist_ok=True)

        good = mkvideo(os.path.join(wd5, "good.mp4"), 4.0)
        fails, det = gates.gate_delivery(good)
        check("a clean render passes Delivery", not fails, str(fails))

        # PTS offset: the classic result of concatenating without -fps_mode cfr.
        shifted = os.path.join(wd5, "shifted.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", good,
                        "-map", "0", "-c", "copy",
                        "-output_ts_offset", "1.5", shifted],
                       check=True, capture_output=True)
        fails, det = gates.gate_delivery(shifted)
        check("a non-zero start PTS is caught",
              any("PTS 0" in f for f in fails), str(det))

        # Audio longer than video: the shape you get when a music bed is padded
        # to a length the picture never reaches.
        mismatch = os.path.join(wd5, "mismatch.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", f"color=c=slategray:s={W}x{H}:r={FPS}:d=4.0",
             "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*220*t)*0.2:s=48000:d=6.0",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-fps_mode", "cfr",
             mismatch], check=True, capture_output=True)
        fails, det = gates.gate_delivery(mismatch)
        check("an audio/video length mismatch is caught",
              any("length mismatch" in f for f in fails), str(det))

        # A difference inside SYNC_TOL is normal encoder rounding, not a defect.
        near = os.path.join(wd5, "near.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", f"color=c=slategray:s={W}x{H}:r={FPS}:d=4.0",
             "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*220*t)*0.2:s=48000:d=4.05",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-fps_mode", "cfr",
             near], check=True, capture_output=True)
        fails, det = gates.gate_delivery(near)
        check("rounding inside SYNC_TOL is not flagged",
              not any("length mismatch" in f for f in fails), str(det))

        # ---- Clearance: the question no other gate is about --------
        # 41 of 93.6 seconds shipped under NDA with every other gate green.
        import clearance as _cl
        wd6 = os.path.join(d, "wd6")
        os.makedirs(wd6, exist_ok=True)

        def _timeline(files):
            json.dump({"total": 10.0,
                       "segments": [{"id": f"s{i:02d}", "file": f, "dur": 1.0,
                                     "start": float(i)}
                                    for i, f in enumerate(files)]},
                      open(os.path.join(wd6, "timeline.json"), "w"))

        def _dec(obj):
            json.dump(obj, open(os.path.join(wd6, "decisions.json"), "w"))

        BASE = {"loudness": {"value": "original", "why": "x"},
                "captions": "on", "end_card": "on"}

        # Stage 1 is the applicability test, so prove it on real names first.
        check("filename triage finds a session clip",
              _cl.triage_filename("IMG_3353_devrel_sharing.MOV") == ["sharing"])
        check("filename triage ignores a food clip",
              _cl.triage_filename("IMG_3394_cake.MOV") == [])

        # Food and running folders must never see this gate at all.
        _timeline(["IMG_3388.MOV", "IMG_3394_cake.MOV", "IMG_3391_lunch.MOV"])
        _dec(BASE)
        fails, det = gates.gate_clearance(wd6)
        check("silent on footage that is not session-shaped",
              not fails and "not applicable" in str(det), str(det))

        # Session-shaped sources with no answer recorded: blocked.
        _timeline(["IMG_3388.MOV", "IMG_3353_devrel_sharing.MOV"])
        _dec(BASE)
        fails, det = gates.gate_clearance(wd6)
        check("session footage with no clearance answer is blocked",
              any("clearance" in f for f in fails), str(fails))

        # Answered: passes.
        _dec({**BASE, "clearance": {"value": "public",
                                    "why": "organiser cleared it 2026-08-21"}})
        fails, det = gates.gate_clearance(wd6)
        check("a recorded clearance answer unblocks it", not fails, str(fails))

        # A bare string records nothing — who cleared it is the whole point.
        _dec({**BASE, "clearance": "public"})
        fails, det = gates.gate_clearance(wd6)
        check("a bare clearance value is rejected",
              any("written 'why'" in f for f in fails), str(fails))

        # THE mechanical half: an excluded source must not reach the cut.
        _timeline(["IMG_3388.MOV", "IMG_3353_devrel_sharing.MOV"])
        _dec({**BASE, "clearance": {"value": "mixed", "why": "Eric cleared 花絮 only",
                                    "excluded": ["IMG_3353_devrel_sharing.MOV"]}})
        fails, det = gates.gate_clearance(wd6)
        check("an excluded source found in the cut is caught",
              any("excluded source" in f for f in fails), str(fails))

        _timeline(["IMG_3388.MOV", "IMG_3394_cake.MOV"])
        fails, det = gates.gate_clearance(wd6)
        check("the same exclusion passes once the clip is gone",
              not fails, str(fails))


        # ---- AudioPolicy: 48s of room hum under a bed nobody asked for ----
        # The 0820 莫宰羊 build. Nobody narrates; the room ran under every shot;
        # twelve gates were green and the user heard it immediately.
        wd7 = os.path.join(d, "wd7")
        os.makedirs(wd7, exist_ok=True)
        AP_BASE = {"loudness": "original", "captions": "on", "end_card": "on",
                   "clearance": "public"}

        def _ap(policy_value, segments):
            _json.dump({**AP_BASE, "audio_policy": policy_value},
                       open(os.path.join(wd7, "decisions.json"), "w"))
            _json.dump({"total": 8.0, "segments":
                        [{"id": r["id"], "file": f"{r['id']}.MOV",
                          "start": r["start"], "dur": r["dur"]} for r in segments]},
                       open(os.path.join(wd7, "timeline.json"), "w"))
            _json.dump({"policy": "selective", "segments": segments},
                       open(os.path.join(wd7, "audio_policy.json"), "w"))

        SEGS = [{"id": "s01", "keep": "FOOD", "start": 0.0, "dur": 4.0,
                 "why": "the boil"},
                {"id": "s02", "keep": None, "start": 4.0, "dur": 4.0,
                 "why": "room tone, music takes it"}]

        # a build that declares nothing at all
        _json.dump(AP_BASE, open(os.path.join(wd7, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(v_ok, wd7)
        check("audio_policy left undecided is caught",
              any("audio_policy" in f for f in fails), str(fails))

        # declared selective, but no per-segment calls written down
        _json.dump({**AP_BASE, "audio_policy": "selective"},
                   open(os.path.join(wd7, "decisions.json"), "w"))
        for stale in ("audio_policy.json", "timeline.json"):
            q = os.path.join(wd7, stale)
            if os.path.exists(q):
                os.remove(q)
        fails, det = gates.gate_audio_policy(v_ok, wd7)
        check("selective with no audio_policy.json is caught",
              any("written down" in f for f in fails), str(fails))

        # a segment with no call at all
        _ap("selective", [SEGS[0]])
        _json.dump({"total": 8.0, "segments": [
            {"id": "s01", "file": "a.MOV", "start": 0.0, "dur": 4.0},
            {"id": "s02", "file": "b.MOV", "start": 4.0, "dur": 4.0}]},
            open(os.path.join(wd7, "timeline.json"), "w"))
        fails, det = gates.gate_audio_policy(v_ok, wd7)
        check("a segment with no audio call is caught",
              any("no audio call" in f for f in fails), str(fails))

        # declared, complete — but the render ignored it (THE defect)
        _ap("selective", SEGS)
        flat = mkvideo(os.path.join(d, "flat-nomusic.mp4"), 8.0)
        fails, det = gates.gate_audio_policy(flat, wd7)
        check("a policy declared but not applied is caught",
              any("declared but not applied" in f for f in fails), str(det))

        # and the same policy, actually applied
        applied = os.path.join(d, "applied-nomusic.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error",
             "-f", "lavfi", "-i", f"color=c=slategray:s={W}x{H}:r={FPS}:d=8",
             "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*220*t)*0.2:s=48000:d=8",
             "-af", "volume='if(gt(t,4),0.06,1)':eval=frame",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
             "-fps_mode", "cfr", "-shortest", "-y", applied],
            check=True, capture_output=True)
        fails, det = gates.gate_audio_policy(applied, wd7)
        check("the same policy, actually applied, passes", not fails, str(det))

        # a declared muted tail is not "dead air" on the no-music sibling...
        deep = os.path.join(d, "deep-nomusic.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error",
             "-f", "lavfi", "-i", f"color=c=slategray:s={W}x{H}:r={FPS}:d=8",
             "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*220*t)*0.2:s=48000:d=8",
             "-af", "volume='if(gt(t,4),0.0008,1)':eval=frame",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
             "-fps_mode", "cfr", "-shortest", "-y", deep],
            check=True, capture_output=True)
        fails, det = gates.gate_audio(deep, wd7)
        check("a DECLARED muted stretch is not dead air",
              not any("dead air" in f for f in fails), str(det))

        # ...but the same silence with no declaration still is
        fails, det = gates.gate_audio(deep, empty)
        check("the same silence undeclared is still dead air",
              any("dead air" in f or "silent ending" in f for f in fails), str(det))


        # ---- Captions: two lines in the same place at the same time -------
        # 0.45s of 清湯底／整鍋都是肉 rendered on top of 肉片一下鍋／顏色馬上就變
        # and shipped, every other caption gate green. ASR-timed captions are
        # sequential by construction; hand-timed ones are not.
        wd8 = os.path.join(d, "wd8")
        os.makedirs(wd8, exist_ok=True)
        _json.dump({"Note": "caption"}, open(os.path.join(wd8, "layout.json"), "w"))
        AT = "{\\an5\\pos(540,1344)}"

        write_ass(os.path.join(wd8, "subtitles.ass"),
                  f"Dialogue: 4,0:00:19.10,0:00:21.25,Note,,0,0,0,,{AT}清湯底\n"
                  f"Dialogue: 4,0:00:20.80,0:00:22.75,Note,,0,0,0,,{AT}肉片一下鍋")
        fails, det = gates.gate_captions(wd8)
        check("two captions at one anchor at one time is caught",
              any("same time in the same place" in f for f in fails), str(det))

        # the same two lines, handed off cleanly
        write_ass(os.path.join(wd8, "subtitles.ass"),
                  f"Dialogue: 4,0:00:18.95,0:00:20.80,Note,,0,0,0,,{AT}清湯底\n"
                  f"Dialogue: 4,0:00:20.80,0:00:22.75,Note,,0,0,0,,{AT}肉片一下鍋")
        fails, det = gates.gate_captions(wd8)
        check("an explicit handoff passes", not fails, str(fails))

        # a two-layer design DOES put several lines up at once, on purpose:
        # the shipped event build's nearest simultaneous anchors are 210px apart
        _json.dump({"Note": "caption", "CardList": "free"},
                   open(os.path.join(wd8, "layout.json"), "w"))
        write_ass(os.path.join(wd8, "subtitles.ass"),
                  f"Dialogue: 4,0:00:19.00,0:00:22.00,Note,,0,0,0,,{AT}主標\n"
                  "Dialogue: 4,0:00:19.00,0:00:22.00,Note,,0,0,0,,"
                  "{\\an5\\pos(540,1554)}副標")
        fails, det = gates.gate_captions(wd8)
        check("a deliberate stacked layer 210px away is not a collision",
              not any("same time in the same place" in f for f in fails), str(det))

        # ---- Timeline: the contract three other checks read ---------
        #
        # 2026-08-22, three drivers on one folder. One of them wrote each
        # segment's origin under `source`; gate_clearance and coverage.py read
        # `file`. Nothing raised — a renamed key just empties the set it feeds —
        # and the whole sixteen came out green on a cut whose source names no
        # gate had ever seen.
        wd9 = os.path.join(d, "wd9")
        os.makedirs(wd9, exist_ok=True)

        def _tl(obj):
            _json.dump(obj, open(os.path.join(wd9, "timeline.json"), "w"))

        GOOD = {"total": 4.0, "segments": [
            {"id": "s01", "file": "IMG_1791.mov", "start": 0.0, "dur": 2.0},
            {"id": "s02", "file": "IMG_1794.MOV", "start": 2.0, "dur": 2.0}]}

        _tl(GOOD)
        fails, det = gates.gate_timeline(wd9)
        check("a well-formed timeline passes", not fails, str(fails))

        os.remove(os.path.join(wd9, "timeline.json"))
        fails, det = gates.gate_timeline(wd9)
        check("no timeline at all is silent (the single-video path)",
              not fails, str(fails))

        # THE defect, reconstructed exactly: the key is spelled `source`.
        TERRA = {"total": 4.0, "segments": [
            {"id": "s01", "source": "IMG_1796.MOV", "start": 0.0, "dur": 2.0},
            {"id": "s02", "source": "IMG_1834.MOV", "start": 2.0, "dur": 2.0}]}
        _tl(TERRA)
        fails, det = gates.gate_timeline(wd9)
        check("a segment that does not name its source is caught",
              any("do not name their source" in f for f in fails), str(fails))
        check("the message names the near miss that was actually made",
              any('"source"' in f for f in fails), str(fails))

        # ...and the gate that was silently disarmed by it now says so. Before
        # this, gate_clearance triaged an empty list and returned PASS.
        _json.dump({"loudness": {"value": "original", "why": "x"},
                    "captions": "on", "end_card": "on",
                    "clearance": {"value": "public", "why": "a public race"}},
                   open(os.path.join(wd9, "decisions.json"), "w"))
        fails, det = gates.gate_clearance(wd9)
        check("clearance no longer passes on zero derivable sources",
              any("nothing was checked" in f for f in fails), str(det))

        # the same cut, with the key the readers actually read
        _tl(GOOD)
        fails, det = gates.gate_clearance(wd9)
        check("clearance is silent again once the sources are readable",
              not fails and det.get("sources") == 2, str(det))

        _tl({"total": 4.0, "segments": [
            {"id": "s01", "file": "a.mov", "dur": 2.0},
            {"id": "s01", "file": "b.mov", "dur": 2.0}]})
        fails, det = gates.gate_timeline(wd9)
        check("a duplicate segment id is caught",
              any("duplicate segment id" in f for f in fails), str(fails))

        # a stale total is how every caption ends up off by the difference
        _tl({"total": 9.0, "segments": [
            {"id": "s01", "file": "a.mov", "dur": 2.0},
            {"id": "s02", "file": "b.mov", "dur": 2.0}]})
        fails, det = gates.gate_timeline(wd9)
        check("a total that disagrees with the segments is caught",
              any("sum to" in f for f in fails), str(fails))

        # ---- End card: authored, or a screenshot of your own last shot? ----
        #
        # 2026-08-23. A driver saved a still from its final clip as endcard.png.
        # File exists ✓. Last frame matches it at 0.99 ✓ — it IS that frame. The
        # video simply stopped on a shot of somebody holding snacks, and the gate
        # that exists to make sure a video has an ending said it had one.
        wd10 = os.path.join(d, "wd10")
        os.makedirs(wd10, exist_ok=True)
        from PIL import Image as _Im
        _Im.new("RGB", (1080, 1920), (40, 40, 40)).save(os.path.join(wd10, "endcard.png"))
        _json.dump({"loudness": {"value": "original", "why": "x"}, "captions": "on",
                    "end_card": {"value": "on"}, "clearance": "public"},
                   open(os.path.join(wd10, "decisions.json"), "w"))
        write_ass(os.path.join(wd10, "subtitles.ass"),
                  f"Dialogue: 5,0:00:00.10,0:00:02.50,Hook,,0,0,0,,{AT}開場")
        _json.dump({"Hook": "caption"}, open(os.path.join(wd10, "layout.json"), "w"))

        fails, det = gates.gate_structure(v_ok, wd10)
        check("an end card with no declared text is caught",
              any("endcard_meta.json" in f for f in fails), str(fails))

        _json.dump({"text": [], "source": "IMG_1866.MOV"},
                   open(os.path.join(wd10, "endcard_meta.json"), "w"))
        fails, det = gates.gate_structure(v_ok, wd10)
        check("a declaration with an EMPTY text list is caught",
              any("declares no text" in f for f in fails), str(fails))

        _json.dump({"text": ["全身濕透", "還是拍了一張"], "source": "end.HEIC"},
                   open(os.path.join(wd10, "endcard_meta.json"), "w"))
        fails, det = gates.gate_structure(v_ok, wd10)
        check("a card that says something is accepted",
              not any("end card" in f.lower() and "meta" in f.lower() for f in fails),
              str(fails))
        check("the gate reports what the card says",
              det.get("end_card_says") == ["全身濕透", "還是拍了一張"], str(det))

        # and the module refuses to render one with nothing on it at all
        import endcard as _ec
        _Im.new("RGB", (900, 1200), (90, 90, 90)).save(os.path.join(wd10, "photo.jpg"))
        try:
            _ec.build(os.path.join(wd10, "photo.jpg"), "", "",
                      os.path.join(wd10, "blank.png"))
            check("endcard.build refuses an empty card", False, "it rendered one")
        except ValueError as e:
            check("endcard.build refuses an empty card", "not an end card" in str(e), str(e))

        path, lines = _ec.build(os.path.join(wd10, "photo.jpg"), "夜跑派對",
                                "2026.7.18 · 10K", os.path.join(wd10, "made.png"))
        made = _json.load(open(os.path.join(wd10, "endcard_meta.json")))
        check("endcard.build declares what it drew",
              made["text"] == ["夜跑派對", "2026.7.18 · 10K"], str(made))

    print("-" * 46)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
