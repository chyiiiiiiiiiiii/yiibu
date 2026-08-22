"""What is actually ON a segment's audio track — voice, a sound event, or hum.

Why this exists: on a food/event 花絮 nobody narrates, and the honest instinct
("the room IS the soundtrack") was applied to EVERY segment. The result was
48 seconds of continuous restaurant hum with a music bed fighting it the whole
way, and the user's verdict was the correct one — "音樂反而變得很小聲，但實際上
影片裡根本沒有人在說話".

Room hum is not the soundtrack. The SIZZLE is. The boil is. Someone laughing
is. The 40 dB of air-conditioning between them is what buries the music.

So the audio bed becomes a per-segment editorial decision, and this module is
the evidence that decision is made from — the same role plan.py plays for
length. It measures three things a spectrogram cannot be eyeballed for:

  voiced   fraction of frames with a real glottal pitch (normalised
           autocorrelation peak in the 75-350 Hz lag range, on a 200-3500 Hz
           band). Speech and laughter score high; clatter, hiss and hum do not.
           This is the measure that separates "someone is talking" from "the
           room is loud", which RMS alone cannot do and which is exactly the
           mistake that shipped.

  sizzle   sustained 4-10 kHz energy with LOW temporal variance. A hot iron
           plate, a rolling boil and a pour all look like this; a plate being
           put down does not (that is a transient, see below), and neither does
           hum (which has no top end at all).

  events   onsets per second in the 1-8 kHz band — cutlery, a lid, a ladle
           against the pot. Sparse and loud is a sound worth keeping; dense and
           quiet is a busy room.

Nothing here decides anything. It reports numbers; the build script writes down
the call and gate_audio_policy checks that a call was written down at all.

    python3 -m modules.audio_scout SEGMENT_DIR
    python3 audio_scout.py seg1.mov seg2.mov ...
"""
import json
import os
import subprocess
import sys

SR = 16000                 # everything here lives below 8 kHz

# Thresholds are ADVISORY — they colour the report, they do not make the call.
# Calibrated on the 0820 莫宰羊 build: the six segments a human confirmed carry
# speech scored 0.21-0.52 voiced; the pure-hum segments scored 0.00-0.06.
VOICED_HINT = 0.15
SIZZLE_HINT = 0.10
EVENT_HINT = 2.0


def _decode(path):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
                          "-ac", "1", "-ar", str(SR), "-"],
                         stdin=subprocess.DEVNULL, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(float)


def _frames(y, win, hop):
    import numpy as np
    n = max((len(y) - win) // hop, 0)
    if not n:
        return np.zeros((0, win))
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    return y[idx]


def voiced_fraction(y):
    """Fraction of 32 ms frames carrying a glottal pitch.

    Autocorrelation, not a spectral flatness measure: hiss and hum are both
    "unvoiced" but sit at opposite ends of every spectral statistic, whereas
    the pitch test answers the one question that matters here — is a human
    making this sound.
    """
    import numpy as np
    win, hop = 512, 256                      # 32 ms / 16 ms
    F = _frames(y, win, hop)
    if not len(F):
        return 0.0
    # 200-3500 Hz: drops the hum and the hiss, keeps the voice
    spec = np.fft.rfft(F * np.hanning(win), axis=1)
    fr = np.fft.rfftfreq(win, 1 / SR)
    spec[:, (fr < 200) | (fr > 3500)] = 0
    band = np.fft.irfft(spec, axis=1)

    lo, hi = int(SR / 350), int(SR / 75)     # 75-350 Hz pitch range
    ok = 0
    energy = (band ** 2).sum(axis=1)
    live = energy > np.percentile(energy, 40)   # ignore the gaps between words
    for i in np.where(live)[0]:
        f = band[i] - band[i].mean()
        ac = np.correlate(f, f, "full")[win - 1:]
        if ac[0] <= 1e-12:
            continue
        ac = ac / ac[0]
        if len(ac) > hi and ac[lo:hi].max() > 0.35:
            ok += 1
    return ok / max(len(F), 1)


def sizzle(y):
    """Sustained high-band hiss: energy 4-8 kHz, weighted by how STEADY it is."""
    import numpy as np
    win, hop = 512, 256
    F = _frames(y, win, hop)
    if not len(F):
        return 0.0
    S = np.abs(np.fft.rfft(F * np.hanning(win), axis=1))
    fr = np.fft.rfftfreq(win, 1 / SR)
    hi = S[:, fr > 4000].mean(axis=1)
    tot = S.mean(axis=1) + 1e-12
    ratio = (hi / tot)
    if not len(ratio) or ratio.mean() <= 0:
        return 0.0
    # steadiness: 1 when the hiss is continuous, ->0 when it is a burst
    steady = 1.0 / (1.0 + ratio.std() / (ratio.mean() + 1e-9))
    return float(ratio.mean() * steady)


def event_rate(y, dur):
    """Onsets per second in the 1-8 kHz band — cutlery, lids, ladles."""
    import numpy as np
    win, hop = 512, 128
    F = _frames(y, win, hop)
    if not len(F):
        return 0.0
    S = np.abs(np.fft.rfft(F * np.hanning(win), axis=1))
    fr = np.fft.rfftfreq(win, 1 / SR)
    e = S[:, fr > 1000].mean(axis=1)
    d = np.maximum(0, np.diff(e))
    if not len(d) or d.std() == 0:
        return 0.0
    thr = d.mean() + 2.5 * d.std()
    peaks = [i for i in range(1, len(d) - 1)
             if d[i] > thr and d[i] >= d[i - 1] and d[i] > d[i + 1]]
    return len(peaks) / max(dur, 1e-6)


def scout(path):
    import numpy as np
    y = _decode(path)
    dur = len(y) / SR
    if dur < 0.05:
        return {"file": os.path.basename(path), "dur": round(dur, 2),
                "voiced": 0.0, "sizzle": 0.0, "events": 0.0, "dbfs": -99.0}
    return {
        "file": os.path.basename(path),
        "dur": round(dur, 2),
        "voiced": round(voiced_fraction(y), 3),
        "sizzle": round(sizzle(y), 3),
        "events": round(event_rate(y, dur), 2),
        "dbfs": round(20 * np.log10(np.sqrt((y ** 2).mean()) + 1e-12), 1),
    }


def report(paths):
    rows = [scout(p) for p in paths]
    print(f"  {'segment':<14}{'dur':>6}{'dBFS':>8}{'voiced':>9}"
          f"{'sizzle':>9}{'events/s':>10}   reads as")
    for r in rows:
        tags = []
        if r["voiced"] >= VOICED_HINT:
            tags.append("VOICE")
        if r["sizzle"] >= SIZZLE_HINT:
            tags.append("sizzle/boil")
        if r["events"] >= EVENT_HINT:
            tags.append("sound events")
        print(f"  {r['file']:<14}{r['dur']:>6.2f}{r['dbfs']:>8.1f}{r['voiced']:>9.3f}"
              f"{r['sizzle']:>9.3f}{r['events']:>10.2f}   "
              f"{', '.join(tags) if tags else '— room tone only'}")
    print("\n  These are MEASUREMENTS, not a decision. What a shot's audio is FOR "
          "is\n  an editorial call — write it down in the segment list and let "
          "gate_audio_policy\n  check that every segment got one.")
    return rows


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and os.path.isdir(args[0]):
        args = [os.path.join(args[0], f) for f in sorted(os.listdir(args[0]))
                if f.lower().endswith((".mov", ".mp4", ".m4a", ".wav"))]
    rows = report(args)
    if os.environ.get("YIIBU_SCOUT_JSON"):
        json.dump(rows, open(os.environ["YIIBU_SCOUT_JSON"], "w"), indent=1)
