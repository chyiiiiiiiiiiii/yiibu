# EXAMPLE — companion to captions.py in this folder; see its header.
#!/usr/bin/env python3
"""Build the music mix: original audio ONLY where someone is actually talking,
music bed everywhere else, ducked under the talking.

Why an authored envelope instead of a sidechain compressor: the expo ambience never
drops below any usable compressor threshold (band-limited key RMS is 0.044 even in
the quietest fifth of the video), so a sidechain either pins the music down for the
whole runtime or does nothing. Silero VAD doesn't separate them either — it scores
82% of this video as "speech" because it hears the crowd babble.

So the gate is editorial and per-segment: SPEECH_SEGMENTS lists the segments where
someone we want to hear is talking (booth staff explaining, session speakers, the
XR walkthrough). Everywhere else the original is muted and the music plays clean.

Music starts at the chorus. Lyrics were transcribed to locate it rather than guessed
from the energy profile — the master is too compressed to show structure:
    0:11.5 verse 1   0:43.5 CHORUS   1:05.5 break
    1:17.5 verse 2   1:49.5 CHORUS   2:11.5 CHORUS/outro
"""
import json
import os
import subprocess
import sys

import numpy as np

_SKILL = os.environ.get("YIIBU_SKILL_DIR") or next(
    (d for d in (os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * n))
                 for n in range(4))
     if os.path.exists(os.path.join(d, "house_style.json"))),
    os.path.expanduser("~/.claude/skills/yiibu"))
sys.path[:0] = [_SKILL, os.path.join(_SKILL, "modules")]
from bgm import derive_tail_fade, measure_audible_end  # tested in the skill

B = os.path.dirname(os.path.abspath(__file__))
SR = 48000

# Track + chorus offset are overridable so two songs can be A/B'd without edits:
#   MUSIC=<wav> CHORUS_AT=<sec> python3 mix_bgm.py
MUSIC = os.environ.get("MUSIC", f"{B}/bgm/track.wav")
CHORUS_AT = float(os.environ.get("CHORUS_AT", 43.5))
# Music enters on the cut to the venue sign. IMG_2864/IMG_2865 carry no speech at
# all (VAD finds none; they are -25 dBFS hall ambience), so muting them and letting
# the chorus land on the title card beats holding room tone under it.
MUSIC_IN = 2.60
# Where the source track actually stops making sound. This one is 159.8s long but its
# last audible moment is 157.2s — starting at the 43.5s chorus leaves it 7s SHORT
# of the video, which is how a silent closing card shipped. If the track runs out,
# wrap back to its instrumental intro instead of playing digital silence.
MUSIC_LOOP_FROM = float(os.environ.get("MUSIC_LOOP_FROM", 0.0))

VOICE_ON = 0.86       # original audio where someone is talking
VOICE_OFF = 0.03      # elsewhere: effectively muted, no expo rumble under the music
MUSIC_DUCK = 0.075    # music under talking
MUSIC_FULL = 0.20     # music with the floor to itself
RAMP = 0.30           # seconds, raised-cosine, on every envelope transition
# TAIL_FADE is DERIVED from the closing shot below — never a constant. It was
# 3.0s, chosen when the closing shot was 4.2s long; the shot later shrank to 2.0s
# and the fade swallowed the whole payoff card. Two nodes changed, no edge
# connected them, and it shipped.

# Segments where a person we want to hear is speaking: the friend's greeting, the
# booth presenters, the XR staff walkthrough, and every session speaker.
SPEECH_SEGMENTS = {
    "s01",                                  # opening XR shot: real venue sound + staff voice
    "s04",                                  # a friend's greeting
    "s13", "s15",                           # HTML-in-canvas presenter + translate demo
    "s16", "s17",                           # Web AI / LiteRT-LM.js presenter
    "s18",                                  # accessibility-plugin booth explanation
    "x1", "x2", "x3", "x4", "x5",           # XR gesture walkthrough
    "s26", "s27", "s28", "s28b",            # accessibility keynote
    "s29",                                  # LiteRT session
    "s31", "s32",                           # Project Montage session + its demo film
    "s28c", "s33",                          # keynote testimonial + closing line
}


def envelope(spans, total, hi, lo):
    """Step envelope with raised-cosine ramps at each edge."""
    n = int(total * SR) + 1
    env = np.full(n, lo, dtype=np.float32)
    for a, b in spans:
        i, j = int(a * SR), int(b * SR)
        env[i:j] = hi
    # smooth every transition
    r = int(RAMP * SR)
    ramp = (1 - np.cos(np.linspace(0, np.pi, r))) / 2
    edges = np.flatnonzero(np.diff(env)) + 1
    for e in edges:
        s, t = max(0, e - r // 2), min(n, e - r // 2 + r)
        if t - s < 2:
            continue
        a, b = env[s], env[t - 1]
        env[s:t] = a + (b - a) * ramp[:t - s]
    return env


def write_wav(env, path):
    st = np.repeat(env[:, None], 2, axis=1).astype(np.float32).tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2",
                    "-i", "pipe:0", "-c:a", "pcm_f32le", "-y", path],
                   input=st, check=True)


def main():
    tl = json.load(open(f"{B}/timeline.json"))
    total = tl["total"]
    spans = [(s["start"], s["start"] + s["dur"])
             for s in tl["segments"] if s["id"] in SPEECH_SEGMENTS]
    # merge touching spans so adjacent speech segments don't ramp against each other
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] < 0.05:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    talk = sum(b - a for a, b in merged)
    print(f"talking: {talk:.1f}s of {total:.1f}s ({talk/total*100:.0f}%) "
          f"across {len(merged)} spans; the rest is music-only")

    closing = tl["segments"][-1]["dur"]
    tail_fade = round(derive_tail_fade(closing), 3)
    audible_end = round(measure_audible_end(MUSIC), 2)
    print(f"  derived: closing shot {closing:.2f}s -> tail fade {tail_fade}s; "
          f"track audible to {audible_end}s")

    write_wav(envelope(merged, total, VOICE_ON, VOICE_OFF), f"{B}/env_voice.wav")
    write_wav(envelope(merged, total, MUSIC_DUCK, MUSIC_FULL), f"{B}/env_music.wav")

    music_len = total - MUSIC_IN
    have = audible_end - CHORUS_AT
    # inputs: 0 rough, 1 music, 2 music again, 3 env_voice, 4 env_music.
    # The track is opened TWICE on purpose: asplit cannot feed two different time
    # ranges (the second branch would have to rewind), and it silently yields a
    # zero-length stream instead of failing.
    if have < music_len:
        short = music_len - have + 1.2
        print(f"  track is {music_len - have:.1f}s short from the chorus -> "
              f"wrapping {short:.1f}s from {MUSIC_LOOP_FROM:.1f}s")
        pre = (f"[1:a]atrim={CHORUS_AT}:{audible_end},asetpts=N/SR/TB[p1];"
               f"[2:a]atrim={MUSIC_LOOP_FROM}:{MUSIC_LOOP_FROM + short:.3f},"
               f"asetpts=N/SR/TB[p2];"
               f"[p1][p2]acrossfade=d=1.2:c1=tri:c2=tri[mraw];")
        src = "[mraw]"
    else:
        pre = ""
        src = f"[1:a]atrim={CHORUS_AT}:{CHORUS_AT + music_len:.3f},asetpts=N/SR/TB,"
    fc = (
        pre + src +
        f"aresample={SR}:resampler=soxr:precision=28,"
        f"adelay={int(MUSIC_IN*1000)}|{int(MUSIC_IN*1000)},"
        f"afade=t=in:st={MUSIC_IN}:d=0.6,"
        f"afade=t=out:st={total - tail_fade:.3f}:d={tail_fade},"
        f"apad=whole_dur={total:.3f}[mus];"
        f"[0:a]aresample={SR}[org];"
        f"[org][3:a]amultiply[v];"
        f"[mus][4:a]amultiply[m];"
        f"[v][m]amix=inputs=2:duration=first:normalize=0[out]"
    )
    subprocess.run(["ffmpeg", "-v", "error",
                    "-i", f"{B}/rough.mov", "-i", MUSIC, "-i", MUSIC,
                    "-i", f"{B}/env_voice.wav", "-i", f"{B}/env_music.wav",
                    "-filter_complex", fc, "-map", "[out]",
                    "-t", f"{total:.3f}",
                    "-c:a", "pcm_s16le", "-ar", str(SR), "-ac", "2",
                    "-y", f"{B}/mixed.wav"], check=True)
    print(f"wrote {B}/mixed.wav")


if __name__ == "__main__":
    main()
