#!/usr/bin/env python3
"""Per-segment duck report: is the music actually getting out of the way?

The Duck gate answers "did it duck" with ONE number for the whole render. This
answers "which segments" — which is what you need when speakers sit at different
distances from the camera and the bed steps back for some of them and not others.
That is the shape of the 2026-08-19 defect: a close mic ducked 7-9 dB, two
room-distance speakers 2-3 dB, and a shot of paper being turned 8.5 dB, with
twelve gates green.

Measured by DIFFERENCING the music render against its no-music sibling: what is
left is the bed alone, so its level can be compared inside and outside each
segment. Reading the duck out of the code would only prove the code was called,
not that it fired on the quiet speakers.

    python3 references/duck_check.py MUSIC.mp4 NOMUSIC.mp4 WORK_DIR
"""
import argparse
import json
import pathlib
import subprocess

import numpy as np

SR = 48000

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music", help="the music render")
    ap.add_argument("nomusic", help="its no-music sibling")
    ap.add_argument("work_dir", help="directory holding timeline.json")
    ap.add_argument("--duck-threshold", type=float, default=0.12,
                    help="speech peak above which a duck is expected (default 0.12)")
    a = ap.parse_args()

    MUSIC, NOMUS = pathlib.Path(a.music), pathlib.Path(a.nomusic)
    W = pathlib.Path(a.work_dir)
    DUCK_THRESHOLD = a.duck_threshold


    def dec(p):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le",
                              "-ac", "1", "-ar", str(SR), "-"],
                             stdin=subprocess.DEVNULL, capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.float32)


    m, s = dec(MUSIC), dec(NOMUS)
    n = min(len(m), len(s))
    m, s = m[:n], s[:n]
    bed = m - s                                   # the music alone

    HOP = SR // 10                                # 100 ms
    k = n // HOP


    def db(x):
        return 20 * np.log10(max(float(x), 1e-9))


    bed_db = np.array([db(np.sqrt((bed[i*HOP:(i+1)*HOP] ** 2).mean())) for i in range(k)])
    sp_pk = np.array([float(np.abs(s[i*HOP:(i+1)*HOP]).max()) for i in range(k)])

    tl = json.load(open(W / "timeline.json"))
    print(f"{'seg':5s} {'window':>13s} {'speech pk':>10s} {'bed dBFS':>9s} {'vs quiet':>9s}  note")

    # reference: bed level in frames where the speech is clearly below the duck threshold
    quiet = bed_db[(sp_pk < 0.05) & (np.arange(k) * 0.1 > 3.3)]
    ref = float(np.median(quiet)) if len(quiet) else float(np.median(bed_db))
    print(f"\nbed level with no speech under it: {ref:.1f} dBFS  "
          f"({len(quiet)} frames)\n")

    for seg in tl["segments"]:
        a, b = seg["start"], seg["start"] + seg["dur"]
        i0, i1 = int(a * 10), int(b * 10)
        if i1 <= i0 or i0 >= k:
            continue
        bd = float(np.median(bed_db[i0:min(i1, k)]))
        pk = float(np.max(sp_pk[i0:min(i1, k)]))
        frac = float((sp_pk[i0:min(i1, k)] > DUCK_THRESHOLD).mean())
        mark = "DUCKED" if bd < ref - 3 else ("partial" if bd < ref - 1 else "-- no duck")
        print(f"{seg['id']:5s} {a:6.1f}-{b:5.1f} {pk:10.3f} {bd:9.1f} {bd-ref:+9.1f}  "
              f"{mark}  over-thresh {frac:.0%}  {seg['note']}")


if __name__ == "__main__":
    main()
