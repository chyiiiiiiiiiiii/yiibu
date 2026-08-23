#!/usr/bin/env python3
"""Make NOT looking at the finished video difficult.

`gates.py` ends with a sentence this repo has repeated since the beginning:

    Say "it passes the gates", never "it is finished", until someone has
    watched it.

Across three benchmark rounds and nine builds, nobody did. Every gate was green
every time, and a person watching afterwards found, in one sitting: a cover
whose picture was rotated 90°, a hook that was a stats screenshot with the
caption drawn on top of the numbers already printed on it, and a 63-second piece
of someone talking cut into eleven fragments totalling ten seconds. Seventeen
blocking gates; none of them can see any of that.

So the missing step is not another check. It is evidence that somebody looked,
and this makes producing that evidence one command:

    python3 review.py WORK_DIR --output FINAL.mp4

It writes a contact sheet — frame 1, the frame under every caption, the last
frame — and prints the numbers that describe the SHAPE of the cut. Then it
stops. It does not grade anything and it never fails: every judgement on this
page is one no threshold can make, which is exactly why a person has to make it.

Why a script and not the `edit-critic` subagent: agents are a Claude Code
feature, and the standard has to be reachable by any driver
(`AGENTS.md`). `edit-critic` remains the accelerator; this is the command
underneath it, and it is what its "portable equivalent" column should have
pointed at all along.
"""
import argparse
import json
import os
import re
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]

W, H = 1080, 1920
TILE_W = 300


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path]).stdout.strip()
    return float(out) if out else 0.0


def captions(work_dir):
    """Every caption with its style, timing and text — the things to check
    against the picture underneath."""
    for name in ("captions.ass", "subtitles.ass"):
        p = os.path.join(work_dir, name)
        if os.path.exists(p):
            break
    else:
        return []
    rows = []
    for line in open(p, encoding="utf-8", errors="ignore").read().splitlines():
        if not line.startswith("Dialogue:"):
            continue
        f = line.split(",", 9)
        def secs(t):
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        rows.append({"start": secs(f[1]), "end": secs(f[2]), "style": f[3],
                     "text": re.sub(r"\{[^}]*\}", "", f[9]).replace("\\N", " / ").strip()})
    return sorted(rows, key=lambda r: r["start"])


def shape(work_dir, video):
    """The measurements that describe the cut. Printed, never judged — every one
    of them has a legitimate value that looks alarming on a different video."""
    out = {"duration_s": round(dur(video), 2)}
    p = os.path.join(work_dir, "timeline.json")
    if os.path.exists(p):
        segs = json.load(open(p, encoding="utf-8")).get("segments", [])
        d = [float(s.get("dur") or 0) for s in segs if s.get("dur")]
        if d:
            out.update(segments=len(d), shortest_s=round(min(d), 2),
                       mean_s=round(sum(d) / len(d), 2),
                       cuts_per_s=round(len(d) / max(out["duration_s"], 1e-6), 2))
        # How a single source was used. A take chopped into many pieces is a
        # normal edit AND the signature of a performance destroyed; the numbers
        # cannot tell you which, and that is the point of printing them.
        by_src = {}
        for s in segs:
            k = os.path.basename(str(s.get("file") or s.get("path") or "?"))
            e = by_src.setdefault(k, {"pieces": 0, "kept_s": 0.0})
            e["pieces"] += 1
            e["kept_s"] += float(s.get("dur") or 0)
        out["sources"] = sorted(
            ({"file": k, **v, "kept_s": round(v["kept_s"], 1)}
             for k, v in by_src.items()),
            key=lambda r: -r["pieces"])
    return out


def audio(work_dir, video):
    """How loud the finished thing is, and how loud the bed is inside it.

    Neither is gated and neither should be. `decisions.json loudness: original`
    protects the FOOTAGE's level on purpose — a personal vlog ships at the level
    it was recorded. But the music bed's level is a choice the build makes, and
    nothing measures whether that choice produced a bed anyone can hear.

    Measured 2026-08-24 across five builds: beds at -16.1, -18.5, -24.5, -30.0
    and -34.0 dBFS, all declaring `original`, all passing Duck and MusicBed. The
    viewer's note on the -34.0 one was 「音樂都快聽不到了」. There is no defensible
    line in that spread — the -30.0 build drew no complaint — so the numbers are
    printed next to each other and a person decides.
    """
    import re
    out = {}
    r = _run(["ffmpeg", "-hide_banner", "-i", video, "-af",
              "volumedetect,ebur128=framelog=verbose", "-f", "null", "-"]).stderr
    m = re.search(r"mean_volume: (\S+)", r)
    lu = re.findall(r"I:\s+(\S+) LUFS", r)
    if m:
        out["mean_dbfs"] = float(m.group(1))
    if lu:
        out["lufs"] = float(lu[-1])
    # the bed, recovered the way the gates recover it: music minus no-music
    d = os.path.dirname(os.path.abspath(video))
    sib = [os.path.join(d, f) for f in sorted(os.listdir(d))
           if re.search(r"-nomusic\.(mp4|mov|m4v)$", f)]
    if sib and not re.search(r"-nomusic\.\w+$", os.path.basename(video)):
        try:
            import numpy as np
            import gates as _g
            a, sr = _g._decode(sib[0])
            b, _ = _g._decode(video)
            n = min(len(a), len(b))
            bed = b[:n] - a[:n]
            win = sr // 4
            lv = np.array([np.sqrt((bed[i * win:(i + 1) * win] ** 2).mean())
                           for i in range((n - win) // win)])
            live = lv[lv > np.percentile(lv, 15)]
            if len(live):
                out["bed_dbfs"] = round(float(20 * np.log10(np.median(live) + 1e-12)), 1)
        except Exception:                                     # noqa: BLE001
            pass
    return out


def contact_sheet(work_dir, video, out_path):
    """Frame 1, every caption moment, the last frame — tiled and labelled.

    This is the artifact. Reading a caption list tells you what it SAYS; the
    only way to know whether it describes what is under it is to put them in the
    same picture.
    """
    from PIL import Image, ImageDraw, ImageFont
    tmp = os.path.join(work_dir, "_review")
    os.makedirs(tmp, exist_ok=True)
    total = dur(video)
    marks = [(0.04, "COVER (frame 1)")]
    for c in captions(work_dir):
        mid = min(max((c["start"] + c["end"]) / 2, 0.05), max(total - 0.05, 0.05))
        marks.append((mid, f"{c['start']:.1f}s [{c['style']}] {c['text']}"))
    marks.append((max(total - 0.15, 0.05), "END CARD (last frame)"))

    try:
        from title import _find_font
        font = ImageFont.truetype(_find_font(), 19)
    except Exception:                                         # noqa: BLE001
        font = ImageFont.load_default()

    tiles = []
    for i, (t, label) in enumerate(marks):
        f = os.path.join(tmp, f"r{i:03d}.png")
        _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video,
              "-frames:v", "1", "-vf", f"scale={TILE_W}:-1", f])
        if not os.path.exists(f):
            continue
        im = Image.open(f).convert("RGB")
        strip = Image.new("RGB", (im.width, im.height + 46), (17, 17, 17))
        strip.paste(im, (0, 0))
        d = ImageDraw.Draw(strip)
        text = label if len(label) <= 34 else label[:33] + "…"
        d.text((7, im.height + 6), text, font=font, fill=(240, 220, 120))
        d.text((7, im.height + 26), f"{t:.2f}s", font=font, fill=(140, 150, 160))
        tiles.append(strip)

    if not tiles:
        return None
    cols = min(6, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    tw, th = tiles[0].width, tiles[0].height
    sheet = Image.new("RGB", (cols * (tw + 8) + 8, rows * (th + 8) + 8), (10, 10, 10))
    for i, t in enumerate(tiles):
        sheet.paste(t, (8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 8)))
    sheet.save(out_path, quality=92)
    return out_path


# The list is short on purpose. Every line is something that shipped green at
# least once in this repo's history, and none of them is checkable.
LOOK_FOR = [
    "the cover: is the picture the right way up, and readable at thumbnail size?",
    "the hook: would a stranger keep watching, or does it only name the scene?",
    "any caption sitting over text the footage already has — two texts, one place",
    "each caption: does it describe what is actually under it, or an inference?",
    "the ending: does it land, or does it just stop?",
    "turn the volume to where you would actually watch: can you hear the music?",
    "anyone recognisable who did not agree to be in this",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("work_dir")
    ap.add_argument("--output", required=True, help="the finished video")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    wd = os.path.abspath(os.path.expanduser(a.work_dir))
    video = os.path.abspath(os.path.expanduser(a.output))

    if not os.path.isdir(wd):
        sys.exit(f"no such work dir: {wd}")
    sh = shape(wd, video)
    caps = captions(wd)
    # Say it. Locating the .ass by searching would risk reading a different
    # build's captions and reporting them as this one's, which is worse than
    # reporting none — but reporting none in silence is how you review the
    # wrong thing and feel fine about it.
    if not caps:
        print(f"\n  ! no captions.ass or subtitles.ass in {wd}")
        print("    (if this build keeps them elsewhere, point --work-dir there — "
              "the sheet below\n     will otherwise show only the cover and the "
              "last frame)")
    sheet = os.path.join(wd, "review_sheet.jpg")
    made = contact_sheet(wd, video, sheet)

    if a.json:
        print(json.dumps({"shape": sh, "audio": audio(wd, video),
                          "captions": caps, "sheet": made},
                         ensure_ascii=False, indent=1))
        return

    print(f"\n  REVIEW — {os.path.basename(video)}")
    print("  " + "-" * 62)
    print(f"    {sh.get('duration_s')}s · {sh.get('segments','—')} segments · "
          f"mean {sh.get('mean_s','—')}s · shortest {sh.get('shortest_s','—')}s · "
          f"{sh.get('cuts_per_s','—')} cuts/s")
    styles = {}
    for c in caps:
        styles[c["style"]] = styles.get(c["style"], 0) + 1
    breakdown = ", ".join(f"{k}×{v}" for k, v in styles.items()) or "—"
    print(f"    {len(caps)} caption(s): {breakdown}")
    if sh.get("sources"):
        top = [s for s in sh["sources"] if s["pieces"] > 1][:3]
        if top:
            print("    a single clip used more than once:")
            for s in top:
                print(f"      {s['file'][:34]:36} {s['pieces']:2} pieces, {s['kept_s']:5.1f}s kept")
    au = audio(wd, video)
    if au:
        bits = []
        if "lufs" in au:
            bits.append(f"{au['lufs']:.1f} LUFS")
        if "mean_dbfs" in au:
            bits.append(f"mean {au['mean_dbfs']:.1f} dBFS")
        if "bed_dbfs" in au:
            bits.append(f"music bed {au['bed_dbfs']:.1f} dBFS")
        print(f"    audio: {' · '.join(bits)}")
    if made:
        print(f"\n    contact sheet -> {made}")
    print("\n  OPEN IT, AND LOOK FOR:")
    for line in LOOK_FOR:
        print(f"    · {line}")
    print("\n  Nothing here is a verdict. Every line above shipped past a full "
          "green board\n  at least once, and none of it is checkable — which is "
          "why you have to look.\n")


if __name__ == "__main__":
    main()
