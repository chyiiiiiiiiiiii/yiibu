#!/usr/bin/env python3
"""Is the sound you KEPT a segment's audio for actually audible under the bed?

This exists because the same wrong measurement was made twice in one session,
and reported to the user as fact both times.

audio_policy.json says a segment keeps its audio because of a VOICE, an SFX or
the FOOD itself. Whether that survives the music was checked by comparing
BROADBAND LEVELS — room -25.9 dBFS against bed -23.5 dBFS — and reported as
"the room leads". It does not work, because masking is SPECTRAL. Measured in
the band the sizzle actually occupies (4-10 kHz), the bed was already 1.7 dB
ahead of it on one shot and 7.7 dB ahead on the next, at a bed level two steps
QUIETER than the one that eventually shipped. The sizzle those two segments were
kept for had never been audible, and a broadband number said the opposite.

So: find where each kept segment's own audio actually lives, and measure there.

The `keep` label narrows the band, the signal picks inside it. VOICE and SFX
name their band outright; FOOD does not — a rolling boil and a hot iron plate
are the same label at opposite ends of the spectrum — so for FOOD the band is
measured. Deriving it for every segment was tried first and put a VOICE shot in
the hiss band, which is the same over-cleverness this file exists to replace.

    python3 mixcheck.py WORK_DIR --music FILE --nomusic FILE

Exits 0 always. This reports; whether an inaudible kept segment is a defect or
an accepted trade-off is an editorial call — sometimes the honest answer is to
flip it to music-only, sometimes the room is wanted as texture. gate_audio_policy
prints the masked count on every run so the question cannot go unnoticed.
"""
import argparse
import json
import os
import subprocess
import sys

SR = 48000
BANDS = {"low": (80, 800, "low  (boil, room)"),
         "mid": (300, 3500, "mid  (voice)"),
         "sfx": (800, 6000, "mid+ (clatter)"),
         "high": (4000, 10000, "high (sizzle, hiss)")}

# The label narrows the search; it does not replace the measurement. VOICE and
# SFX name their band outright. FOOD does not — a rolling boil and a hot iron
# plate are the same label at opposite ends of the spectrum — so for FOOD the
# band is measured. An earlier version derived the band for EVERY segment and
# put a VOICE shot in the hiss band, which is the same over-cleverness this
# file exists to replace.
KIND_BANDS = {"VOICE": ["mid"], "SFX": ["sfx"], "FOOD": ["low", "high"]}
AUDIBLE_DB = 3.0        # comfortably heard
MARGINAL_DB = 0.0       # level with the bed


def decode(path):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
                        "-ac", "1", "-ar", str(SR), "-"],
                       stdin=subprocess.DEVNULL, capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32).astype(float)


def band_db(x, lo, hi):
    import numpy as np
    win, hop = 2048, 1024
    if len(x) < win:
        return -99.0
    k = (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(k)[:, None]
    S = np.abs(np.fft.rfft(x[idx] * np.hanning(win), axis=1))
    fr = np.fft.rfftfreq(win, 1 / SR)
    return float(20 * np.log10(S[:, (fr > lo) & (fr < hi)].mean() + 1e-12))


def analyse(work_dir, music, nomusic):
    """[{id, keep, band, margin_db, verdict}] for every kept segment."""
    import numpy as np
    pol_p = os.path.join(work_dir, "audio_policy.json")
    if not os.path.exists(pol_p):
        return None
    pol = json.load(open(pol_p))
    room, mixed = decode(nomusic), decode(music)
    n = min(len(room), len(mixed))
    if n < SR:
        return None
    bed = mixed[:n] - room[:n]

    # Baseline: where the room's audio sits across the WHOLE cut. A FOOD
    # segment's band is whichever of its candidates stands out most against it.
    base = {k: band_db(room[:n], *BANDS[k][:2]) for k in BANDS}

    out = []
    for r in pol.get("segments", []):
        if not r.get("keep"):
            continue
        i0 = int(r["start"] * SR)
        i1 = min(int((r["start"] + r["dur"]) * SR), n)
        if i1 - i0 < 2048:
            continue
        cands = KIND_BANDS.get(str(r["keep"]).upper(), ["low", "mid", "high"])
        key = max(cands, key=lambda k: band_db(room[i0:i1], *BANDS[k][:2]) - base[k])
        lo, hi, name = BANDS[key]
        margin = band_db(room[i0:i1], lo, hi) - band_db(bed[i0:i1], lo, hi)
        verdict = ("audible" if margin >= AUDIBLE_DB else
                   "marginal" if margin >= MARGINAL_DB else "MASKED")
        out.append({"id": r["id"], "keep": r["keep"], "band": name,
                    "margin_db": round(margin, 1), "verdict": verdict,
                    "why": r.get("why", "")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--music", required=True)
    ap.add_argument("--nomusic", required=True)
    a = ap.parse_args()

    rows = analyse(a.work_dir, a.music, a.nomusic)
    if rows is None:
        print("  no audio_policy.json (or the pair would not decode) — "
              "nothing to check")
        return 0
    if not rows:
        print("  no segments keep their audio — nothing to check")
        return 0

    print(f"\n  {'seg':<6}{'keep':<7}{'its own band':<24}{'margin':>8}   verdict")
    for r in rows:
        print(f"  {r['id']:<6}{str(r['keep']):<7}{r['band']:<24}"
              f"{r['margin_db']:>+8.1f}   {r['verdict']}")
    masked = [r for r in rows if r["verdict"] == "MASKED"]
    print(f"\n  {len(rows) - len(masked)}/{len(rows)} kept segments are audible "
          f"over the bed.")
    if masked:
        print(f"  MASKED: {', '.join(r['id'] for r in masked)} — the music is "
              f"louder than\n  the sound each of those was kept for. Either the "
              f"bed comes down over them,\n  or they are music-only and the "
              f"policy should say so. Keeping a segment's\n  audio for a sound "
              f"nobody can hear is a note-to-self, not an edit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
