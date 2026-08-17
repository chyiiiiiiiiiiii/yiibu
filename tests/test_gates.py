#!/usr/bin/env python3
"""Regression test for the shipping gates.

Each case reconstructs a defect that actually shipped and asserts the gate
catches it. Without this, the gates themselves can rot silently — a threshold
edited to make a build pass would go unnoticed, which is the same failure mode
they exist to prevent.

    python3 tests/test_gates.py
"""
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
                    "captions": "on", "end_card": "on"},
                   open(os.path.join(dec, "decisions.json"), "w"))
        fails, det = gates.gate_decisions(None, dec)
        check("a recorded, reasoned decision passes", not fails, str(fails))

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

    print("-" * 46)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
