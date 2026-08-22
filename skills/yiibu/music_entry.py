#!/usr/bin/env python3
"""WHERE in a track to start the bed — the chorus, not the loudest bit.

resolve_music.py answers *which* track. Nothing answered *where*, and SKILL.md
told you to "enter on the chorus" as prose. Prose is not a method: on 2026-08-21
that instruction was followed by picking the hottest sustained window, reported
to the user as a chorus entry, and it was six seconds early — the tail of the
pre-chorus. The user asked directly ("你現在是不是沒有從副歌開始？") and the
honest answer was no.

So this is the command that makes the claim checkable.

WHAT DOES NOT WORK, and why it is worth knowing:

  * ENERGY. Modern masters are compressed flat; a chorus, a busy verse and a
    bridge all sit within a decibel or two. The 2026-08-21 track's whole
    energy curve was ▇▇▇▇▇ end to end.
  * CHROMA REPETITION. The textbook method — a chorus is the section whose
    harmony recurs — collapses on anything built over one chord loop. On that
    same track every candidate scored 174-179 repeats out of 196 possible.
    Indistinguishable, and confidently so.

WHAT DOES: timbre. A chorus is where the ARRANGEMENT fills in — bass, doubled
vocals, hats. Foote checkerboard novelty over log-mel features finds the section
boundaries; the fullest-arrangement section is the chorus; a kick-onset grid
snaps the entry to a downbeat so the bed does not come in mid-bar.

    python3 music_entry.py TRACK [--length 48]

Reports the section map, the chorus candidates, and downbeat-snapped entries.
It reports; you choose. A section map is evidence, not a decision — the right
entry also has to keep the video's OPENING clear (a quiet bar of the song
landing under the hook reads as "the music is broken", which is its own
2026-08-21 defect), and only you know where the hook is.
"""
import argparse
import subprocess
import sys

SR = 22050


def load(path, sr=SR):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "-"],
                       stdin=subprocess.DEVNULL, capture_output=True)
    if not r.stdout:
        raise SystemExit(f"could not decode audio from {path}")
    return np.frombuffer(r.stdout, dtype=np.float32).astype(float)


def _frames(y, win, hop):
    import numpy as np
    n = max((len(y) - win) // hop, 0)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    return y[idx] * np.hanning(win)


def sections(y, sr=SR, nb=24):
    """Section boundaries by timbre novelty, one feature vector per second."""
    import numpy as np
    win, hop = 2048, 1024
    S = np.abs(np.fft.rfft(_frames(y, win, hop), axis=1)) ** 2
    fr = np.fft.rfftfreq(win, 1 / sr)
    mel = lambda f: 2595 * np.log10(1 + f / 700)                # noqa: E731
    inv = lambda m: 700 * (10 ** (m / 2595) - 1)                # noqa: E731
    edges = inv(np.linspace(mel(40), mel(sr / 2), nb + 2))
    M = np.stack([S[:, (fr >= edges[b]) & (fr < edges[b + 2])].sum(1)
                  for b in range(nb)], axis=1)
    M = np.log(M + 1e-10)
    fps = sr / hop
    N = int(len(M) / fps)
    Ms = np.stack([M[int(i * fps):int((i + 1) * fps)].mean(0) for i in range(N)])
    Z = (Ms - Ms.mean(0)) / (Ms.std(0) + 1e-9)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
    SS = Z @ Z.T

    L = 8
    K = np.zeros((2 * L, 2 * L))
    K[:L, :L] = K[L:, L:] = 1
    K[:L, L:] = K[L:, :L] = -1
    K *= np.outer(np.hanning(2 * L), np.hanning(2 * L))
    nov = np.zeros(N)
    for i in range(L, N - L):
        nov[i] = (SS[i - L:i + L, i - L:i + L] * K).sum()
    nov = (nov - nov.min()) / (nov.max() - nov.min() + 1e-9)
    bs = []
    for i in range(L, N - L):
        if nov[i] > 0.45 and nov[i] == nov[max(0, i - 6):i + 7].max():
            if not bs or i - bs[-1] >= 12:
                bs.append(i)
    return [0] + bs + [N], N


def bands(y, N, sr=SR):
    """Per-second bass / vocal / air energy, normalised — arrangement fullness."""
    import numpy as np
    win, hop = 2048, 1024
    S = np.abs(np.fft.rfft(_frames(y, win, hop), axis=1))
    fr = np.fft.rfftfreq(win, 1 / sr)
    fps = sr / hop

    def per_sec(lo, hi):
        b = S[:, (fr > lo) & (fr < hi)].mean(1)
        v = np.array([b[int(i * fps):int((i + 1) * fps)].mean()
                      for i in range(min(N, int(len(b) / fps)))])
        return (v - v.min()) / (v.max() - v.min() + 1e-9)
    return per_sec(40, 140), per_sec(400, 3000), per_sec(6000, 10000)


def downbeats(path, around, span=16.0, sr=44100):
    """Kick onsets near `around`, and the bar grid that best explains them."""
    import numpy as np
    t0 = max(around - span / 2, 0)
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0}", "-t", f"{span}",
                        "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       stdin=subprocess.DEVNULL, capture_output=True)
    y = np.frombuffer(r.stdout, dtype=np.float32).astype(float)
    win, hop = 2048, 256
    fps = sr / hop
    S = np.abs(np.fft.rfft(_frames(y, win, hop), axis=1))
    fr = np.fft.rfftfreq(win, 1 / sr)
    kick = S[:, (fr > 45) & (fr < 110)].mean(1)
    w = max(int(fps * 0.6), 1)
    k = kick - np.convolve(kick, np.ones(w) / w, "same")
    thr = k.std() * 1.5
    peaks, last = [], -9
    for i in range(2, len(k) - 2):
        if k[i] > thr and k[i] == max(k[i - 2:i + 3]) and (i / fps) - last > 0.12:
            peaks.append(t0 + i / fps)
            last = i / fps
    if len(peaks) < 4:
        return [], 0.0
    beat = float(np.median(np.diff(peaks)))
    bar = beat * 4
    best = max(((sum(1 for p in peaks if min(abs((p - ph) % bar),
                                             bar - abs((p - ph) % bar)) < 0.09), ph)
                for ph in np.arange(0, bar, 0.02)), key=lambda x: x[0])
    grid = [g for g in np.arange(t0 + (best[1] - t0) % bar, t0 + span, bar)]
    return grid, 60.0 / beat


def main():
    import numpy as np
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("--length", type=float, default=48.0,
                    help="how many seconds the bed has to cover")
    a = ap.parse_args()

    y = load(a.track)
    bounds, N = sections(y)
    bass, voc, air = bands(y, N)
    hop = SR
    rms = np.array([np.sqrt((y[i * hop:(i + 1) * hop] ** 2).mean() + 1e-12)
                    for i in range(N)])
    ldb = 20 * np.log10(rms / rms.max())

    rows = []
    for s, e in zip(bounds[:-1], bounds[1:]):
        if e - s < 6:
            continue
        m = slice(s, min(e, len(air)))
        rows.append((s, e - s, ldb[s:e].mean(), bass[m].mean(), voc[m].mean(),
                     air[m].mean(), (bass[m].mean() + voc[m].mean() + air[m].mean()) / 3))
    if not rows:
        raise SystemExit("no sections found — track too short?")

    print(f"\n  {a.track.split('/')[-1]}   {N}s   {len(rows)} sections\n")
    print(f"  {'start':>7}{'len':>6}{'loud':>7}{'bass':>7}{'vocal':>7}"
          f"{'air':>7}{'fullness':>10}")
    top = max(r[6] for r in rows)
    for s, ln, ld, b, v, ar, f in rows:
        print(f"  {s:>6}s{ln:>5}s{ld:>7.1f}{b:>7.2f}{v:>7.2f}{ar:>7.2f}{f:>10.2f}"
              + ("   <- fullest arrangement" if f == top else ""))

    cands = sorted(rows, key=lambda r: -r[6])[:3]
    print("\n  chorus candidates (fullest arrangement, most-likely first):")
    for s, ln, ld, b, v, ar, f in cands:
        grid, bpm = downbeats(a.track, s)
        near = sorted((g for g in grid if abs(g - s) < 3.0), key=lambda g: abs(g - s))
        entry = near[0] if near else float(s)
        # A quiet bar of the song landing right after the hook reads as a
        # broken bed. Report the opening 10s so the choice is made with it.
        head = ldb[int(entry):int(entry) + 10]
        print(f"    section {s:>4}s  fullness {f:.2f}  ->  enter at "
              f"{entry:7.2f}s  ({bpm:.1f} BPM grid)")
        print(f"        first 10s of the bed: min {head.min():+.1f} dB, "
              f"median {np.median(head):+.1f} dB"
              + ("   <- has a hole in it" if head.min() < np.median(ldb) - 8
                 else "   <- clear"))
        end = entry + a.length
        after = [r for r in rows if r[0] > end - 6]
        print(f"        covers {entry:.1f}-{end:.1f}s"
              + (f", next boundary at {after[0][0]}s" if after else ""))
    print("\n  Reports, does not decide: the entry also has to keep the video's")
    print("  OPENING clear, and only you know where the hook is.\n")


if __name__ == "__main__":
    main()
