"""Proven build primitives for folder-of-clips builds.

Why this module exists: the 2026-08-17 0816-run build took ~1 hour instead of
~10 minutes, and every lost minute traced to a hand-written ffmpeg graph
re-deriving something this skill had already learned:

  - libx264 on 1080x1920 (20+ min) where videotoolbox does it in seconds —
    documented in running-vlog-template §9, hit anyway
  - a bare `-loop 1` png feeding overlay -> ffmpeg hangs forever after writing
    the file — documented in delivery-traps #6, hit anyway
  - animated crop w/h (config-time only) -> hard failure; zoompan is the filter
    that animates scale
  - chained delayed-PTS overlays -> framesync composited only the FIRST pill
  - sidechaincompress+amix dropping the music bed before the end

Prose did not prevent any of these twice-documented traps. Code does: build
scripts call these functions instead of writing graphs. A build script that
shells out to raw ffmpeg for something buildkit covers is the failure mode.

All functions raise on failure and ASSERT output durations — a silent length
drift is how captions go stale.
"""
import json
import os
import subprocess

W, H, FPS = 1080, 1920, 30


def _has_encoder(name):
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True).stdout
        return name in out
    except OSError:
        return False


# Hardware encode where it exists: ~40x faster than libx264 at this resolution
# and the quality difference is irrelevant for phone footage. videotoolbox is
# macOS-only, so a clone on Linux falls back rather than failing outright —
# libx264 is a build_lint antipattern because of what it costs, not because it
# is wrong, so the fallback says so out loud.
HW = _has_encoder("h264_videotoolbox")
if HW:
    _VCODEC = ["-c:v", "h264_videotoolbox", "-b:v", "20M"]
else:
    _VCODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    print("buildkit: h264_videotoolbox unavailable — falling back to libx264 "
          "(veryfast). Intermediates will be slower on this machine.")

VENC = [*_VCODEC, "-pix_fmt", "yuv420p", "-r", str(FPS)]

# HOUSE RULE (user, 2026-08-21): keep the picture the user shot. File size is
# THEIR call, not ours, and we do not trade quality for it uninvited.
#
# This existed as a 2400k "delivery" default that quietly threw away detail. On
# 1080x1920@30 that is 0.027 bits per pixel, and the user saw the softness on
# food texture. Measured afterwards — SSIM of the delivery encode against a
# 20 Mbps reference, on a detailed 4s stretch of that same footage:
#
#     2400k  SSIM 0.935    9.5 MB / 48s     <- what was shipping
#     4000k  SSIM 0.958   15.8 MB
#     6000k  SSIM 0.970   23.8 MB
#     8000k  SSIM 0.976   31.8 MB
#    12000k  SSIM 0.984   47.8 MB
#
# Picking any of those is still choosing a compromise on the user's behalf, which
# is the thing they asked us not to do. So the default matches the intermediate
# encode: no quality step at hand-over. A 90s reel lands around 200 MB, and that
# is fine — every platform re-encodes anyway, and feeding it a soft source only
# makes ITS encode worse.
#
# YIIBU_DELIVERY_BITRATE exists for when a smaller file genuinely matters more,
# and then it is a deliberate choice someone made.
DELIVERY_BITRATE = os.environ.get("YIIBU_DELIVERY_BITRATE", "20M")
if HW:
    DELIVERY_VENC = ["-c:v", "h264_videotoolbox", "-b:v", DELIVERY_BITRATE,
                     "-maxrate", DELIVERY_BITRATE, "-bufsize", "16000k"]
else:
    DELIVERY_VENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "21",
                     "-maxrate", DELIVERY_BITRATE, "-bufsize", "16000k"]
DELIVERY_VENC += ["-pix_fmt", "yuv420p", "-r", str(FPS)]
# Intermediates carry PCM so AAC is encoded exactly once at the final mux
# (delivery-traps #3).
AENC_PCM = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]

VF_FILL = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
           f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p")


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(f"FAILED: {' '.join(map(str, cmd))}\n{r.stderr[-2500:]}")
    return r


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", p]).stdout.strip())


def decoded_peak(p):
    """Decode the finished file and measure. Never trust the filter graph."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-f", "f32le",
                          "-ac", "1", "-ar", "48000", "-"],
                         stdin=subprocess.DEVNULL, capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    if not len(a):
        return -999.0, 0
    import math
    return 20 * math.log10(max(float(abs(a).max()), 1e-9)), int((abs(a) > 1.0).sum())


def prep_segment(src, tin, tout, dst, gain=1.0, vf=VF_FILL, af_extra=None):
    """One cut: trim, normalise geometry, PCM audio. Asserts the length.

    af_extra appends ffmpeg audio filters to this segment only. It exists for
    the fault a gain cannot fix: a fridge or display-case compressor puts a
    STEADY TONE in one shot — 6368 Hz at only 10 dB under the fundamental in the
    case that prompted this — and the ear locks onto a steady tone long after a
    broadband hiss would have disappeared under music. Attenuating the segment
    would take the room down with it; a narrow notch takes out the whine and
    leaves the shot sounding like the room it was recorded in:

        af_extra="equalizer=f=6368:width_type=q:w=30:g=-24"
    """
    d = round(tout - tin, 3)
    af = f"asetpts=N/SR/TB,aresample=48000,volume={gain:.4f}"
    if af_extra:
        af += "," + af_extra
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{tin:.3f}", "-i", src,
         "-t", f"{d:.3f}", "-vf", vf, "-af", af,
         *VENC, *AENC_PCM, dst])
    got = dur(dst)
    if abs(got - d) > 0.10:
        raise RuntimeError(f"segment {dst} is {got:.2f}s, wanted {d:.2f}s")
    return dst


def concat(parts, dst):
    """Concat-demux copy. Asserts the total."""
    lst = dst + ".txt"
    open(lst, "w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in parts))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", dst])
    want = sum(dur(p) for p in parts)
    got = dur(dst)
    if abs(got - want) > 0.15:
        raise RuntimeError(f"concat {got:.2f}s != sum of parts {want:.2f}s")
    return dst


def punch_in(d, zoom=0.08, big_w=W * 2, big_h=H * 2):
    """Slow push-in filter string. zoompan, NOT crop with animated w/h —
    crop's w/h are evaluated once at config time and animating them fails."""
    frames = max(int(d * FPS), 1)
    return (f"zoompan=z='min(1+{zoom}*on/{frames},{1 + zoom})'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={FPS}")


def overlay_pills(video_in, pills, work_dir, video_out):
    """Overlay title pills, one SEQUENTIAL pass each.

    pills: [{"start","end","png"}...]. Two traps encoded here:
    - each pill becomes a FINITE qtrle clip; a bare `-loop 1` png never EOFs
      and ffmpeg hangs forever AFTER writing the full output (delivery-traps #6)
    - one pass per pill; chaining delayed-PTS overlays in a single graph
      composited only the first pill (framesync), observed 2026-08-17
    """
    cur = video_in
    for n, p in enumerate(pills):
        d = p["end"] - p["start"]
        # max(...,1): a one-frame span is 1/30 = 0.0333s and int(0.0333*30) is
        # 0, which writes an EMPTY clip and the overlay then fails with
        # "Stream specifier ':v' matches no streams". Burning a cover onto
        # frame 1 is exactly a one-frame span.
        frames = max(int(round(d * FPS)), 1)
        clip = os.path.join(work_dir, f"_pill{n}.mov")
        run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", p["png"],
             "-t", f"{max(d, 1.0 / FPS):.3f}", "-r", str(FPS),
             "-frames:v", str(frames), "-c:v", "qtrle", clip])
        nxt = (video_out if n == len(pills) - 1
               else os.path.join(work_dir, f"_pilled{n}.mov"))
        run(["ffmpeg", "-v", "error", "-y", "-i", cur, "-i", clip,
             "-filter_complex",
             f"[1:v]setpts=PTS-STARTPTS+{p['start']}/TB,format=rgba[p];"
             f"[0:v][p]overlay=0:0:eof_action=pass"
             f":enable='between(t,{p['start']},{p['end']})'[v]",
             "-map", "[v]", "-an", *VENC, "-fps_mode", "cfr", nxt])
        cur = nxt
    if not pills:
        import shutil
        shutil.copy(video_in, video_out)
    return video_out


def burn_subtitles(video_in, ass_path, video_out):
    """Burn the .ass, having first made sure the house font is installable.

    libass does not fail on a missing font — it substitutes one and exits 0.
    Measured: an .ass naming `ThisFontDoesNotExist12345` still rendered legible
    CJK text, ffmpeg returned 0, and gate_typography stayed green because it
    reads the Fontname DECLARED in the .ass, not the face libass actually used.
    So the whole video comes out in the wrong typeface with sixteen gates green.

    `ensure_fonts()` used to be called only from postprod.py, which left every
    template-mode build — the folder-of-clips path, i.e. the one a fresh clone
    runs first — on the unprovisioned side of that. Provisioning belongs here,
    at the single point every caption burn passes through, rather than in an
    ordering rule each entry point has to remember. It is idempotent and a
    no-op once the font is in place.
    """
    from title import ensure_fonts
    ensure_fonts()
    run(["ffmpeg", "-v", "error", "-y", "-i", video_in,
         "-vf", f"subtitles='{ass_path.replace(':', chr(92) + ':')}'",
         "-an", *VENC, "-fps_mode", "cfr", video_out])
    return video_out


def mux(video_in, audio_from, dst):
    """Video from one file, untouched PCM audio from another."""
    run(["ffmpeg", "-v", "error", "-y", "-i", video_in, "-i", audio_from,
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", *AENC_PCM, dst])
    return dst


def measure_gain_db(path, target_lufs=-14.0):
    """loudnorm as a MEASURE only; the gain is applied as a constant
    (delivery-traps #4: loudnorm as a filter eats the tail and NaNs)."""
    m = run(["ffmpeg", "-v", "info", "-nostats", "-i", path,
             "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"]).stderr
    meas = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    return target_lufs - float(meas["input_i"]), meas


def afx_chain(gain_db):
    """Compressor BEFORE make-up so the limiter is not clawing back every
    transient; ceiling -3.5 dBFS; level=disabled or alimiter re-normalises."""
    return (f"acompressor=threshold=-20dB:ratio=3:attack=20:release=250:makeup=1,"
            f"volume={gain_db:.2f}dB,alimiter=limit=0.668:level=disabled")


def duck_mix(speech_video, bed_wav, work_dir, depth_db=11.0, speech_spans=None,
             ramp_s=0.30):
    """Music under speech via the numpy envelope (bgm.duck_gain semantics).

    NOT sidechaincompress+amix: that construction silently stopped passing the
    bed ~1.6s before the end while the bed file measured -23.6 dBFS
    (delivery-traps #4b). Returns a raw f32 path + sample count.

    Two modes, and on multi-speaker material you want the first:

    * ``speech_spans`` — [(start_s, end_s), ...] of the segments that CARRY a
      voice. Deterministic and inspectable, which is what the event template
      asks for ("the segment list is an editorial decision; write it down").
    * automatic — threshold derived FROM THE MATERIAL. The old absolute
      ``env > 0.12`` was calibrated for one person on a close mic: on a room
      with speakers at different distances it ducked the close mic 7-9 dB, the
      room-distance speakers only 2-3 dB, and 8.5 dB under a shot of paper
      being turned (measured 2026-08-19). Hysteresis stops the flutter that
      made those quiet speakers average out to nothing.
    """
    import numpy as np

    def rd(path):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
                              "-ac", "2", "-ar", "48000", "-"],
                             stdin=subprocess.DEVNULL, capture_output=True).stdout
        a = np.frombuffer(raw, dtype=np.float32)
        return a[: len(a) // 2 * 2].reshape(-1, 2).copy()

    sp, bd = rd(speech_video), rd(bed_wav)
    n = min(len(sp), len(bd))
    if n < len(sp) - 48000 // 2:
        raise RuntimeError(f"bed is {len(bd)/48000:.2f}s but speech is "
                           f"{len(sp)/48000:.2f}s — music would be missing "
                           f"from the ending")
    sp, bd = sp[:n], bd[:n]
    sr, hop = 48000, 480
    k = (n + hop - 1) // hop
    duck = 10 ** (-depth_db / 20)

    if speech_spans is not None:
        target = np.ones(k)
        for a_s, b_s in speech_spans:
            i0 = max(int(a_s * sr / hop), 0)
            i1 = min(int(b_s * sr / hop), k)
            if i1 > i0:
                target[i0:i1] = duck
    else:
        mono = np.abs(sp).max(axis=1)
        env = np.array([mono[i:i + hop].max() for i in range(0, n, hop)])
        edb = 20 * np.log10(env + 1e-9)
        floor, top = np.percentile(edb, 20), np.percentile(edb, 97)
        open_db = floor + 0.45 * max(top - floor, 6.0)
        close_db = open_db - 3.0            # hysteresis: no flutter at the line
        target, on = np.ones(k), False
        for i, v in enumerate(edb[:k]):
            on = v > open_db if not on else v > close_db
            target[i] = duck if on else 1.0

    # Raised-cosine ramps. A one-pole attack/release re-derives its own shape
    # from whatever the envelope did; a fixed window is the same every build.
    win = max(int(ramp_s * sr / hop), 3)
    kern = np.hanning(win * 2 + 1)
    kern /= kern.sum()
    smooth = np.convolve(np.pad(target, win, mode="edge"), kern,
                         mode="same")[win:win + k]
    gain = np.interp(np.arange(n), np.arange(k) * hop, smooth)[:, None]
    out = os.path.join(work_dir, "_duckmix.f32")
    open(out, "wb").write((sp + bd * gain).astype(np.float32).tobytes())
    return out, n


def final_encode(video_src, dst, afx, audio_f32=None, delivery=True):
    """The single AAC encode. audio_f32=None -> use video_src's own audio.

    delivery=True uses DELIVERY_VENC — same 1080x1920 picture at a bitrate a
    person can actually send. Pass delivery=False only for an archival master.
    """
    venc = DELIVERY_VENC if delivery else VENC
    if audio_f32 is None:
        run(["ffmpeg", "-v", "error", "-y", "-i", video_src,
             "-filter_complex", f"[0:a]asetpts=N/SR/TB,aresample=48000,{afx}[a]",
             "-map", "0:v", "-map", "[a]", *venc, "-fps_mode", "cfr",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", dst])
    else:
        run(["ffmpeg", "-v", "error", "-y", "-i", video_src,
             "-f", "f32le", "-ar", "48000", "-ac", "2", "-i", audio_f32,
             "-filter_complex", f"[1:a]asetpts=N/SR/TB,{afx}[a]",
             "-map", "0:v", "-map", "[a]", *venc, "-fps_mode", "cfr",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", dst])
    pk, over = decoded_peak(dst)
    if pk > 0.0 or over:
        raise RuntimeError(f"{dst} decodes above full scale ({pk:+.2f} dBFS, "
                           f"{over} samples over)")
    return dst


# ── self-lint: importing buildkit lints the build script that imported it ────
#
# build_lint.py existed but nothing made a build script run it — a documented
# step is a skipped step (the whole lesson of 2026-08-17). Importing buildkit
# is the one thing every build script does, so the lint rides on the import:
# zero hooks, zero configuration, and a script full of the slow/hang
# antipatterns refuses to start instead of stalling 20 minutes in.
# Escape hatch: YIIBU_SKIP_LINT=1 (say why in the build script if you use it).
def _self_lint():
    import sys
    if os.environ.get("YIIBU_SKIP_LINT") == "1":
        return
    script = sys.argv[0] if sys.argv and sys.argv[0].endswith(".py") else None
    if not script or not os.path.isfile(script):
        return                                  # REPL / pytest / -c
    if os.path.basename(script).startswith(("test_", "pytest")):
        return
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import build_lint
    except ImportError:
        return
    hits = build_lint.lint(script)
    if hits:
        msgs = "\n".join(f"  line {ln}: {m}" for ln, _p, m in hits)
        raise RuntimeError(
            f"build_lint: {os.path.basename(script)} contains "
            f"{len(hits)} antipattern(s) that have each burned real build time "
            f"before:\n{msgs}\n"
            f"Fix them (buildkit covers every case), or set YIIBU_SKIP_LINT=1 "
            f"with a written reason.")


_self_lint()
