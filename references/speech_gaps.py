#!/usr/bin/env python3
"""Report speech gaps in a clip, for planning cuts by hand.

`silencedetect` is useless on outdoor footage — traffic and wind hold the noise
floor above any fixed dB threshold, so it reports nothing. This profiles the
speech band and thresholds relative to the clip's own quiet quartile instead.

    python3 speech_gaps.py CLIP [CLIP ...] [--min-gap 0.7] [--pad 0.18]

Prints each silent run and a suggested keep-list: gaps longer than --min-gap are
cut, everything else is left alone so the delivery keeps its natural rhythm.
"""
import argparse
import os
import subprocess
import sys
import wave

import numpy as np

HOP_SEC = 0.05
THRESHOLD_OVER_P25_DB = 8.0


def speech_envelope(path: str) -> tuple[np.ndarray, float]:
    """Return per-hop dB in the speech band, and the clip duration."""
    wav = f"/tmp/_gaps_{os.path.basename(path)}.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000",
         "-af", "highpass=f=250,lowpass=f=3400", wav],
        check=True,
    )
    with wave.open(wav) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    a = a.astype(np.float32) / 32768
    hop = int(16000 * HOP_SEC)
    rms = np.array([np.sqrt((a[i:i + hop] ** 2).mean() + 1e-12)
                    for i in range(0, len(a) - hop, hop)])
    return 20 * np.log10(rms + 1e-9), len(a) / 16000


def silent_runs(db: np.ndarray, min_gap: float) -> list[tuple[float, float]]:
    voiced = db > (np.percentile(db, 25) + THRESHOLD_OVER_P25_DB)
    runs, i = [], 0
    while i < len(voiced):
        if voiced[i]:
            i += 1
            continue
        j = i
        while j < len(voiced) and not voiced[j]:
            j += 1
        if (j - i) * HOP_SEC >= min_gap:
            runs.append((round(i * HOP_SEC, 2), round(j * HOP_SEC, 2)))
        i = j
    return runs


def keeps(runs, duration, pad):
    """Invert the cut list into keep ranges, padded back toward the speech."""
    out, cur = [], 0.0
    for s, e in runs:
        out.append((round(max(0.0, cur), 2), round(s + pad, 2)))
        cur = e - pad
    out.append((round(max(0.0, cur), 2), round(duration, 2)))
    return [(s, e) for s, e in out if e - s > 0.15]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--min-gap", type=float, default=0.7,
                    help="only cut silences at least this long (seconds)")
    ap.add_argument("--pad", type=float, default=0.18,
                    help="silence left at each cut (seconds)")
    args = ap.parse_args()

    for path in args.clips:
        db, duration = speech_envelope(path)
        runs = silent_runs(db, args.min_gap)
        keep = keeps(runs, duration, args.pad)
        kept = sum(e - s for s, e in keep)
        print(f"== {os.path.basename(path)}  {duration:.2f}s "
              f"→ {kept:.2f}s over {len(keep)} piece(s)")
        print(f"   cut : {runs}")
        print(f"   keep: {keep}")
        print("   NOTE: verify the last kept word survives — re-run ASR on the "
              "cut span and pad the out-point if it is clipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
