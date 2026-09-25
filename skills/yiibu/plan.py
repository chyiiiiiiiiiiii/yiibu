#!/usr/bin/env python3
"""Plan the edit before cutting: what to KEEP, and how long the result should be.

Division of labour: **the user shoots, the editor selects.** They hand over a
folder; deciding which shots earn a place, in what order, and how long the whole
thing runs is the edit. This script does the arithmetic for that decision and
prints something the user can argue with in one line.

LENGTH COMES FROM RETENTION, NOT FROM FOOTAGE VOLUME
----------------------------------------------------
The wrong model — the one this file used to implement — is
"clips × average shot length". It makes the video as long as the material
allows, which is backwards: every extra segment is another chance to scroll.

The right model is additive from the things worth watching:

    length = hook + Σ(payload beats) + connective tissue + ending

  * **Hook (~2-3s).** The opening shot has one job: show the most unusual thing
    in the whole folder. Not context, not a sign, not walking in. If the strangest
    image is at 4:51 of a five-minute clip, that is frame one.
  * **Payload beat (8-14s).** One thing worth understanding: set up, show,
    land it. Fewer than three payloads and there is no reason to watch; more
    than six and none of them get room to breathe.
  * **Connective tissue (~25% of payload time).** Establishing shots and
    reactions that carry you between payloads. This is the first thing to cut
    when the video feels long — it is never the payloads.
  * **Ending (4-6s).** Long enough to read the closing card, short enough that
    it is not dead time.

PROVENANCE OF THE NUMBERS — read this before trusting them
----------------------------------------------------------
  * The shot-length bands and the payload band are **measured** from one edit
    the user reviewed and accepted (2026-08-13, 39 segments, 2:02). They are a
    calibrated starting point, not a law.
  * The platform ranges are **conventions**, not research findings. I do not
    have verified retention data for these platforms and have not invented any.
    Treat them as "where most of this format lives", and override them freely.
  * The structural claims (hook decides the scroll; length costs completion)
    are the reasoning behind the model. If you disagree with them, change the
    model — do not quietly pad the output.

    python3 plan.py SOURCE_DIR [--platform reels|shorts|linkedin]
                               [--payloads N] [--json]
                               [--sheets-dir PATH] [--no-sheets]

It also BUILDS what you are supposed to look at: a contact sheet plus a
six-frame filmstrip per clip, into SOURCE_DIR_sheets/. That used to be a
sentence in the food template and was therefore skipped.
"""
import argparse
import json
import os
import subprocess

VIDEO_EXT = (".mov", ".mp4", ".m4v", ".avi")

SHEET_FRAMES = 6          # per clip; the food template has asked for 6 since 08-10
SHEET_TILE_W = 400        # wide enough to judge FRAMING, which 300px is not


def build_sheets(src_dir, out_dir, per_clip=SHEET_FRAMES, tile_w=SHEET_TILE_W):
    """One filmstrip per clip, plus one folder-wide contact sheet.

    references/food-vlog-template.md §1 has asked for exactly this since
    2026-08-10 — "a 6-frame filmstrip per clip you might use", with a worked
    example of a price board that was invisible in the contact sheet and only
    surfaced in a filmstrip. It was prose, so on 2026-09-01 it was skipped: that
    build picked its hook off ONE mid-frame per clip rendered 300px wide, and
    chose a shot that is a neck and an ear for the whole of its 2.9s. The user
    replaced it. A 6-frame strip shows a botched take is botched in every frame;
    a single mid-frame cannot. So the rule stops being advice and becomes what
    `plan.py` does before it prints anything.

    Frames come out through ffmpeg, which applies the display matrix. Pulling
    them any other way re-derives the rotation trap: a clip that DISPLAYS
    portrait reports 1920x1080 coded, and the frame arrives on its side.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:                                   # pragma: no cover
        return None
    clips = scan(src_dir)
    if not clips:
        return None
    os.makedirs(out_dir, exist_ok=True)
    strips_dir = os.path.join(out_dir, "filmstrips")
    os.makedirs(strips_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "_f.jpg")
    tile_h = int(tile_w * 16 / 9)
    mids, made = [], []

    for c in clips:
        d = c["dur"]
        # skip the outer 6%: the first and last frames of a phone clip are the
        # hand reaching for the button, not the shot
        times = [d * (0.06 + 0.88 * i / max(per_clip - 1, 1)) for i in range(per_clip)]
        tiles = []
        for t in times:
            subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}",
                            "-i", os.path.join(src_dir, c["file"]),
                            "-frames:v", "1", "-y", tmp],
                           stdin=subprocess.DEVNULL, capture_output=True)
            if not os.path.exists(tmp):
                continue
            im = Image.open(tmp).convert("RGB")
            im.thumbnail((tile_w, tile_h))
            tiles.append((im.copy(), t))
        if not tiles:
            continue
        w = max(im.width for im, _ in tiles)
        h = max(im.height for im, _ in tiles)
        strip = Image.new("RGB", (len(tiles) * (w + 4) + 4, h + 26), (18, 18, 18))
        dr = ImageDraw.Draw(strip)
        for i, (im, t) in enumerate(tiles):
            strip.paste(im, (i * (w + 4) + 4, 4))
            dr.text((i * (w + 4) + 6, h + 8), f"{t:.2f}s", fill=(220, 220, 220))
        stem = os.path.splitext(c["file"])[0]
        path = os.path.join(strips_dir, f"{stem}.jpg")
        strip.save(path, quality=88)
        made.append(path)
        mids.append((stem, tiles[len(tiles) // 2][0]))

    sheet_path = None
    if mids:
        cols = min(6, len(mids))
        rows = (len(mids) + cols - 1) // cols
        w = max(im.width for _, im in mids)
        h = max(im.height for _, im in mids)
        sheet = Image.new("RGB", (cols * (w + 6) + 6, rows * (h + 26) + 6), (18, 18, 18))
        dr = ImageDraw.Draw(sheet)
        for i, (stem, im) in enumerate(mids):
            x, y = (i % cols) * (w + 6) + 6, (i // cols) * (h + 26) + 6
            sheet.paste(im, (x, y))
            dr.text((x, y + h + 6), stem[:26], fill=(230, 230, 230))
        sheet_path = os.path.join(out_dir, "contact_sheet.jpg")
        sheet.save(sheet_path, quality=88)
    if os.path.exists(tmp):
        os.remove(tmp)
    return {"dir": out_dir, "contact_sheet": sheet_path,
            "filmstrips": made, "frames_per_clip": per_clip}

HOOK_S = (2.0, 3.0)
PAYLOAD_S = (8.0, 14.0)
ENDING_S = (4.0, 6.0)
CONNECTIVE_RATIO = 0.25

# Measured from the accepted edit.
SHOT = {
    "hook":         (2.0, 3.0),
    "establishing": (1.6, 2.6),
    "beat":         (1.8, 3.2),
    "explainer":    (3.5, 6.0),
    "payload":      (5.0, 9.0),
}

# Conventions, not findings. Where this format usually lives.
PLATFORM = {
    "reels":    (75, 150),
    "shorts":   (75, 180),
    "linkedin": (90, 210),
}

PAYLOAD_MIN, PAYLOAD_MAX = 3, 6
MIN_CAPTION_S = 1.8
CJK_READ_CPS = 4.5


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


TOPIC_STOPWORDS = {"img", "mov", "mp4", "dsc", "vid", "video", "clip", "final"}


def topics(clips):
    """Group clips by the topic token in their filename.

    A payload is not the same thing as a long take: three 2-second clips of one
    booth are one payload, and a five-minute clip of a queue is none. People name
    their exports for what is in them (IMG_2907_ai_booth, ..._html_in_canvas), so
    the filename is the strongest cheap signal for "distinct thing worth
    explaining". Falls back to long-take detection when names carry nothing.
    """
    import re
    groups = {}
    for c in clips:
        stem = os.path.splitext(c["file"])[0]
        toks = [t for t in re.split(r"[^A-Za-z]+", stem.lower())
                if t and not t.isdigit() and t not in TOPIC_STOPWORDS and len(t) > 2]
        key = "_".join(toks) if toks else None
        if key:
            groups.setdefault(key, []).append(c)
    return groups


def scan(src_dir):
    clips = []
    for f in sorted(os.listdir(src_dir)):
        if f.lower().endswith(VIDEO_EXT) and not f.startswith("."):
            d = probe(os.path.join(src_dir, f))
            if d:
                clips.append({"file": f, "dur": round(d, 1)})
    return clips


def plan(src_dir, platform="reels", payloads=None, sheets_dir=None):
    clips = scan(src_dir)
    if not clips:
        raise SystemExit(f"no video files in {src_dir}")

    ranked = sorted(clips, key=lambda c: -c["dur"])
    groups = topics(clips)
    # Rank topics by total footage spent on them — that is what "I stopped and
    # paid attention to this" looks like in a folder.
    by_time = sorted(groups.items(), key=lambda kv: -sum(c["dur"] for c in kv[1]))
    if by_time:
        suggested = max(PAYLOAD_MIN, min(PAYLOAD_MAX, len(by_time)))
        topic_names = [k for k, _ in by_time]
    else:
        suggested = max(PAYLOAD_MIN,
                        min(PAYLOAD_MAX, sum(1 for c in clips if c["dur"] >= 20)))
        topic_names = []
    n_pay = payloads or suggested

    pay_lo = HOOK_S[0] + n_pay * PAYLOAD_S[0] + ENDING_S[0]
    pay_hi = HOOK_S[1] + n_pay * PAYLOAD_S[1] + ENDING_S[1]
    lo = round(pay_lo * (1 + CONNECTIVE_RATIO))
    hi = round(pay_hi * (1 + CONNECTIVE_RATIO))
    plo, phi = PLATFORM.get(platform, PLATFORM["reels"])

    target = max(lo, min(hi, phi))
    keep_est = 1 + n_pay + round(n_pay * 2.5)      # hook + payloads + tissue

    sheets = build_sheets(src_dir, sheets_dir) if sheets_dir else None

    return {
        "sheets": sheets,
        "source_clips": len(clips),
        "raw_footage_s": round(sum(c["dur"] for c in clips), 1),
        "platform": platform,
        "platform_convention_s": [plo, phi],
        "payload_beats": n_pay,
        "payload_suggested_from_material": suggested,
        "length_from_retention_s": [lo, hi],
        "recommended_s": target,
        "recommended_mmss": f"{target//60}:{target%60:02d}",
        "segments_to_keep_est": keep_est,
        "clips_likely_unused": max(0, len(clips) - keep_est),
        # NOT "hook_candidates". This is a duration sort, and it was printed
        # under the words "全資料夾最奇怪的畫面" until 2026-09-02 — the code
        # ranked by length while the label promised strangeness. On the 0901
        # folder it returned the three LONGEST clips and the hook the user
        # actually chose was 1.49s, 4th shortest of 23: the list could never
        # have contained the answer. Renamed rather than re-implemented,
        # because nothing measurable here predicts a good hook — see report().
        "longest_clips": [c["file"] for c in ranked[:3]],
        "topics_found": len(groups),
        "payload_candidates": (topic_names[:n_pay]
                               or [c["file"] for c in ranked[:n_pay]]),
        "shortest_clips": [c["file"] for c in sorted(clips, key=lambda c: c["dur"])[:5]],
        "shot_lengths_s": SHOT,
        "caption_budget": {
            "min_on_screen_s": MIN_CAPTION_S,
            "max_chars_on_shortest_shot": int(SHOT["beat"][0] * CJK_READ_CPS),
        },
    }


def report(p):
    print(f"\n  素材：{p['source_clips']} 個檔案 / {p['raw_footage_s']:.0f} 秒"
          f"（使用者拍好的，接下來是二次選擇）")
    print(f"\n  ★ 建議長度 {p['recommended_mmss']}（{p['recommended_s']}s）")
    print(f"    由留存推導：{p['payload_beats']} 個 payload → "
          f"{p['length_from_retention_s'][0]}–{p['length_from_retention_s'][1]}s")
    print(f"    平台慣例區間 {p['platform_convention_s'][0]}–"
          f"{p['platform_convention_s'][1]}s（{p['platform']}）")
    print(f"\n  結構 = hook {HOOK_S[0]:.0f}-{HOOK_S[1]:.0f}s"
          f" + payload×{p['payload_beats']} 各 {PAYLOAD_S[0]:.0f}-{PAYLOAD_S[1]:.0f}s"
          f" + 過場 {int(CONNECTIVE_RATIO*100)}%"
          f" + 結尾 {ENDING_S[0]:.0f}-{ENDING_S[1]:.0f}s")
    print(f"\n  預計用 {p['segments_to_keep_est']} 段，"
          f"約 {p['clips_likely_unused']} 個素材不會用到 — 這是正常的")
    print(f"\n  最長的三支（就只是最長，不是 hook 建議）：")
    for f in p["longest_clips"]:
        print(f"    {f}")
    if p.get("sheets"):
        print(f"\n  ★ hook：先看 {p['sheets']['dir']}/filmstrips/"
              f"（每支 {p['sheets']['frames_per_clip']} 格），再問使用者。")
    else:
        print(f"\n  ★ hook：每支 clip 拉一條 filmstrip 再看，別用單張縮圖判斷構圖。")
    print("    不要只看單張中間格 —— 廢鏡在六格裡格格都廢，在一格裡看不出來。")
    print("    然後問使用者哪個瞬間最精彩：這是全片槓桿最大的一顆，")
    print("    而臉多大、動多少、銳不銳利都量過了，沒有一個預測得到它。")
    print(f"  payload 候選（依檔名主題分組，共找到 {p['topics_found']} 個主題；"
          f"花最多時間拍的排前面）：")
    for f in p["payload_candidates"]:
        print(f"    {f}")
    c = p["caption_budget"]
    print(f"\n  字幕：至少停留 {c['min_on_screen_s']}s；"
          f"最短鏡頭最多 {c['max_chars_on_shortest_shot']} 字")
    print("\n  覺得太長時砍過場，不要砍 payload。"
          "\n  節奏由內容決定：先剪無配樂版，能看了再考慮鋪音樂。\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src_dir")
    ap.add_argument("--platform", default="reels", choices=sorted(PLATFORM))
    ap.add_argument("--payloads", type=int, default=None,
                    help="override the number of payload beats")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sheets-dir", default=None,
                    help="where to write the contact sheet and per-clip "
                         "filmstrips (default: SOURCE_DIR + '_sheets')")
    ap.add_argument("--no-sheets", action="store_true",
                    help="skip building them; you are then judging framing off "
                         "metadata alone, which is how the 0901 hook was picked "
                         "off a 300px thumbnail and had to be replaced")
    a = ap.parse_args()
    sd = None if a.no_sheets else (
        a.sheets_dir or os.path.abspath(a.src_dir.rstrip("/\\")) + "_sheets")
    p = plan(a.src_dir, a.platform, a.payloads, sheets_dir=sd)
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    else:
        report(p)


if __name__ == "__main__":
    main()
