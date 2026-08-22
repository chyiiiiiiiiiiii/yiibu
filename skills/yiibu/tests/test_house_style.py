#!/usr/bin/env python3
"""The house style must be MACHINE-checked, not described.

Every case here is a defect that shipped in a real rebuild while the old gates
were all green — the look drifted because nothing checked the look. If one of
these ever passes silently, the next agent (any model, no memory of this session)
will re-derive a different video and be told it is fine.

    python3 tests/test_house_style.py
"""
import json
import os
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

import gates  # noqa: E402

W, H = 1080, 1920
PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  — {detail}" if detail and not cond else ""))


HEAD = """[Script Info]
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""
GOOD_STYLES = (
    "Style: Speech,演示斜黑体,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,"
    "0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1\n"
    "Style: Hook,演示斜黑体,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,"
    "0,0,0,0,100,100,0,0,1,0,7,5,60,60,0,1"
)
AT = r"{\an5\pos(540,1344)}"
# The house look includes the gold keyword layer (min 3 spans) — a "good"
# fixture with all-white captions is itself the 2026-08-17 defect.
GOLD, WHITE = r"{\fs90\c&H66DBF6&}", r"{\fs84\c&HFFFFFF&}"
GOOD_SPEECH = (f"均速{GOLD}4:51{WHITE}整，{GOLD}5K{WHITE}路線"
               f"{GOLD}PB{WHITE}達成")


def write_ass(wd, styles=GOOD_STYLES, events=None):
    events = events or [
        f"Dialogue: 5,0:00:00.15,0:00:02.50,Hook,,0,0,0,,{AT}開場",
        f"Dialogue: 4,0:00:03.00,0:00:05.00,Speech,,0,0,0,,{AT}{GOOD_SPEECH}",
    ]
    open(os.path.join(wd, "captions.ass"), "w", encoding="utf-8").write(
        HEAD.format(styles=styles, events="\n".join(events)))
    json.dump({"Speech": "caption", "Hook": "free"},
              open(os.path.join(wd, "layout.json"), "w"))


def make_pill(wd, text="測試", square=False, fade=False):
    """Render a house pill, or the two things people build instead of it."""
    from PIL import Image, ImageDraw
    import title
    # Read the house position instead of repeating it: this test hardcoded 0.23
    # and would have kept passing against a house_style.json that had moved.
    pct = json.load(open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "house_style.json")))["pill"]["centre_pct"]
    os.makedirs(os.path.join(wd, "pills"), exist_ok=True)
    png = os.path.join(wd, "pills", "p00.png")
    if square:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        y = int(pct * H)
        d.rectangle([340, y - 40, 740, y + 40], fill=(0, 0, 0, 175))   # ASS-style box
        im.save(png)
    else:
        title.render_title_png(text, png, pct=pct, font_size=56)
    json.dump([{"text": text, "start": 0.2, "end": 2.0}],
              open(os.path.join(wd, "pills.json"), "w"), ensure_ascii=False)
    mov = os.path.join(wd, "pills", "p00.mov")
    vf = "fps=30,format=rgba"
    if fade:
        vf += ",fade=t=in:st=0:d=0.4:alpha=1"
    subprocess.run(["ffmpeg", "-v", "error", "-loop", "1", "-i", png, "-t", "1.8",
                    "-vf", vf, "-c:v", "qtrle", "-y", mov], check=True)


def main():
    print("\n HOUSE STYLE GATES\n" + "-" * 46)

    # ── Typography: the exact drift that shipped ──────────────
    with tempfile.TemporaryDirectory() as wd:
        write_ass(wd)
        fails, _ = gates.gate_typography(wd)
        check("house typography passes", not fails, str(fails))

        write_ass(wd, styles=GOOD_STYLES.replace(",84,", ",62,"))
        fails, _ = gates.gate_typography(wd)
        check("62pt caption is rejected", any("62pt" in f for f in fails), str(fails))

        # outline 6 instead of a drop shadow — field 16 of the Style line
        bad = GOOD_STYLES.replace("0,0,1,0,5,5,60,60,0,1",
                                  "0,0,1,6,3,5,60,60,0,1")
        write_ass(wd, styles=bad)
        fails, _ = gates.gate_typography(wd)
        check("black outline instead of drop shadow is rejected",
              any("outline" in f for f in fails), str(fails))

        write_ass(wd, styles=GOOD_STYLES.replace("演示斜黑体", "Helvetica"))
        fails, _ = gates.gate_typography(wd)
        check("wrong font is rejected", any("house font" in f for f in fails), str(fails))

        write_ass(wd, events=[
            f"Dialogue: 5,0:00:00.15,0:00:02.50,Hook,,0,0,0,,{{\\fad(140,120)}}{AT}開場"])
        fails, _ = gates.gate_typography(wd)
        check("\\fad on a caption is rejected", any("fad" in f for f in fails), str(fails))

    # ── Bilingual: half-translated must not pass ──────────────
    with tempfile.TemporaryDirectory() as wd:
        json.dump({"bilingual": {"required": True, "english_font_size": 48,
                                 "english_colour": "&H00EAEAEA"}},
                  open(os.path.join(wd, "house_style.local.json"), "w"))
        en = r"\N{\fs48\c&H00EAEAEA}English"
        write_ass(wd, events=[
            f"Dialogue: 5,0:00:00.15,0:00:02.50,Hook,,0,0,0,,{AT}開場{en}",
            f"Dialogue: 4,0:00:03.00,0:00:05.00,Speech,,0,0,0,,{AT}一句話"])
        fails, det = gates.gate_typography(wd)
        check("caption missing its English line is rejected",
              any("English line" in f for f in fails), str(fails))
        check("project override is reported", det.get("overrides") == "bilingual",
              str(det))

        write_ass(wd, events=[
            f"Dialogue: 5,0:00:00.15,0:00:02.50,Hook,,0,0,0,,{AT}開場{en}",
            f"Dialogue: 4,0:00:03.00,0:00:05.00,Speech,,0,0,0,,{AT}{GOOD_SPEECH}{en}"])
        fails, _ = gates.gate_typography(wd)
        check("fully bilingual passes", not fails, str(fails))

    # ── Pill: absence, square corners, fades ──────────────────
    with tempfile.TemporaryDirectory() as wd:
        fails, det = gates.gate_pill(wd)
        check("MISSING pills.json is a FAILURE, not a skip", bool(fails), str(det))

        make_pill(wd)
        fails, _ = gates.gate_pill(wd)
        check("house PIL capsule passes", not fails, str(fails))

    with tempfile.TemporaryDirectory() as wd:
        make_pill(wd, square=True)
        fails, _ = gates.gate_pill(wd)
        check("square-cornered (ASS box) pill is rejected",
              any("square corners" in f for f in fails), str(fails))

    with tempfile.TemporaryDirectory() as wd:
        make_pill(wd, fade=True)
        fails, _ = gates.gate_pill(wd)
        check("faded-in pill clip is rejected", any("fade in" in f for f in fails),
              str(fails))

    # ── Structure: hook and end card ──────────────────────────
    with tempfile.TemporaryDirectory() as wd:
        write_ass(wd, events=[
            f"Dialogue: 4,0:00:03.00,0:00:05.00,Speech,,0,0,0,,{AT}一句話"])
        fails, _ = gates.gate_structure("/dev/null", wd)
        check("no hook is rejected", any("Hook" in f or "hook" in f for f in fails),
              str(fails))

        write_ass(wd, events=[
            f"Dialogue: 5,0:00:04.00,0:00:06.00,Hook,,0,0,0,,{AT}太晚了"])
        fails, _ = gates.gate_structure("/dev/null", wd)
        check("hook starting at 4s is rejected",
              any("must be inside" in f for f in fails), str(fails))

        write_ass(wd)
        fails, _ = gates.gate_structure("/dev/null", wd)
        check("missing end card is rejected",
              any("endcard" in f for f in fails), str(fails))

    # ── Cover: metrics sidecar and subtitle width match ───────
    with tempfile.TemporaryDirectory() as wd:
        from PIL import Image
        import cover
        src = os.path.join(wd, "src.png")
        Image.new("RGB", (W, H), (40, 40, 60)).save(src)
        out = os.path.join(wd, "cover.jpg")
        cover.build(src, "這不是掌機\n還會翻英文", "GoGBA・手機上的 GBA 模擬器", out)
        meta = json.load(open(os.path.join(wd, "cover_meta.json")))
        gap = abs(meta["title_w"] - meta["subtitle_w"])
        tol = gates.house(wd)["cover"]["subtitle_width_match_tol_px"]
        check("cover.build writes measurable metrics", meta["title_pt"] > 0, str(meta))
        check(f"subtitle tracks the title width (gap {gap}px <= {tol})", gap <= tol,
              str(meta))
        hs = gates.house(wd)["cover"]
        cap = W * hs["title_max_w_ratio"] + hs["title_ink_overhang_tol_px"]
        check(f"title stays inside {hs['title_max_w_ratio']:.0%} of the frame (+ink tol)",
              meta["title_w"] <= cap, str(meta))

    # ── Sync: a verbatim caption must match the audio under it ─
    # These four are the defects a human found by hand-diffing a table; the
    # position and typography gates are all green for every one of them.
    def words(shift=0.0):
        seq = [("然", 1.00), ("後", 1.20), ("我", 1.40), ("用", 1.60), ("過", 1.80),
               ("這", 3.00), ("個", 3.20), ("就", 3.40), ("是", 3.60), ("跟", 3.80),
               ("一", 4.00), ("些", 4.20),
               ("可", 6.00), ("以", 6.20), ("直", 6.40), ("接", 6.60),
               ("快", 6.80), ("速", 7.00), ("存", 7.20), ("檔", 7.40),
               ("很", 9.00), ("順", 9.20), ("耶", 9.40),
               ("它", 11.00), ("有", 11.20), ("一", 11.40), ("千", 11.60),
               ("多", 11.80), ("個", 12.00)]
        return [{"text": t, "start": round(x + shift, 2), "end": round(x + shift + .18, 2),
                 "probability": 0.95} for t, x in seq]

    def sync_wd(wd, events, shift=0.0):
        write_ass(wd, events=events)
        json.dump(words(shift), open(os.path.join(wd, "words.json"), "w"),
                  ensure_ascii=False)

    OK_EVENTS = [
        f"Dialogue: 5,0:00:00.10,0:00:00.90,Hook,,0,0,0,,{AT}開場",
        f"Dialogue: 4,0:00:01.00,0:00:02.00,Speech,,0,0,0,,{AT}然後我用過",
        f"Dialogue: 4,0:00:03.00,0:00:04.40,Speech,,0,0,0,,{AT}這個就是跟一些",
        f"Dialogue: 4,0:00:06.00,0:00:07.60,Speech,,0,0,0,,{AT}可以直接快速存檔",
        f"Dialogue: 4,0:00:09.00,0:00:09.90,Speech,,0,0,0,,{AT}很順耶",
        f"Dialogue: 4,0:00:11.00,0:00:12.30,Speech,,0,0,0,,{AT}它有一千多個",
    ]
    with tempfile.TemporaryDirectory() as wd:
        sync_wd(wd, OK_EVENTS)
        fails, det = gates.gate_sync(wd)
        check("aligned verbatim captions pass", not fails, str(fails))
        check("sync reports what it checked", det["verbatim_captions"] == 5, str(det))

    with tempfile.TemporaryDirectory() as wd:                 # defect: 1.3s late
        late = list(OK_EVENTS)
        late[3] = late[3].replace("0:00:06.00,0:00:07.60", "0:00:07.30,0:00:08.90")
        sync_wd(wd, late)
        fails, _ = gates.gate_sync(wd)
        check("caption 1.3s late is rejected", any("off by more than" in f for f in fails),
              str(fails))

    with tempfile.TemporaryDirectory() as wd:                 # defect: opens on a cut word
        head = list(OK_EVENTS)
        head[2] = head[2].replace("這個就是跟一些", "從剛剛這個就是跟一些")
        sync_wd(wd, head)
        fails, _ = gates.gate_sync(wd)
        check("caption opening on words the cut removed is rejected",
              any("not in the audio" in f for f in fails), str(fails))

    with tempfile.TemporaryDirectory() as wd:                 # defect: wrong audio under it
        wrong = list(OK_EVENTS)
        wrong[1] = wrong[1].replace("然後我用過", "模型本身就很大")
        sync_wd(wd, wrong)
        fails, _ = gates.gate_sync(wd)
        check("caption over audio that says something else is rejected",
              any("not what the audio says" in f for f in fails), str(fails))

    with tempfile.TemporaryDirectory() as wd:                 # defect: stale word map
        sync_wd(wd, OK_EVENTS, shift=-0.8)
        fails, det = gates.gate_sync(wd)
        check("a stale words.json (whole map shifted) is rejected",
              any("stale" in f for f in fails), f"{det} {fails}")

    with tempfile.TemporaryDirectory() as wd:                 # verbatim claim, no evidence
        write_ass(wd, events=OK_EVENTS)
        fails, _ = gates.gate_sync(wd)
        check("verbatim captions with no words.json are rejected",
              any("no words.json" in f for f in fails), str(fails))

    with tempfile.TemporaryDirectory() as wd:                 # authored-only edit needs none
        write_ass(wd, events=[
            f"Dialogue: 5,0:00:00.10,0:00:00.90,Hook,,0,0,0,,{AT}開場"])
        fails, det = gates.gate_sync(wd)
        check("an authored-caption edit needs no words.json", not fails, str(det))

    # ── legibility must measure the TITLE, not the background ─
    with tempfile.TemporaryDirectory() as wd:
        from PIL import Image as _I
        import cover as _cover
        bright = os.path.join(wd, "bright.png")
        _I.new("RGB", (W, H), (250, 250, 250)).save(bright)   # the case that broke it
        seen = []
        for t in ("五字標題\n第二行呢", "七個字的標題啦\n第二行"):
            out = os.path.join(wd, "cover.jpg")
            _, pt, _ = _cover.build(bright, t, "副標題", out)
            leg = _cover.legibility(out)
            seen.append((pt, leg["title_line_ratio"], leg.get("source")))
        check("legibility reads font metrics, not a pixel scan",
              all(s == "font-metrics" for _, _, s in seen), str(seen))
        check("legibility tracks title size on a BRIGHT background",
              seen[0][1] > seen[1][1], str(seen))

    print("-" * 46)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed\n")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
