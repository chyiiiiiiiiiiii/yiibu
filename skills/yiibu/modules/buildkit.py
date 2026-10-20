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
import sys
import time

W, H, FPS = 1080, 1920, 30
SR = 48000
# A cut of N frames carries exactly N * this many samples, or concat drifts.
SAMPLES_PER_FRAME = SR // FPS


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
AENC_PCM = ["-c:a", "pcm_s16le", "-ar", str(SR), "-ac", "2"]

VF_FILL = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
           f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p")


def _record_timing(path, cmd, elapsed, outcome, returncode):
    executable = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else ""
    row = {
        "command_kind": os.path.basename(str(executable)) or "unknown",
        "elapsed_seconds": round(elapsed, 6),
        "outcome": outcome,
        "returncode": returncode,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception as e:
        print(f"buildkit: could not write timing log: {e}", file=sys.stderr)


def run(cmd, timing_log=None, **kw):
    started = time.perf_counter()
    r = None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, **kw)
        if r.returncode:
            raise RuntimeError(f"FAILED: {' '.join(map(str, cmd))}\n{r.stderr[-2500:]}")
        return r
    finally:
        path = timing_log or os.environ.get("YIIBU_TIMING_LOG")
        if path:
            success = r is not None and r.returncode == 0
            _record_timing(
                path,
                cmd,
                time.perf_counter() - started,
                "success" if success else "failure",
                r.returncode if r is not None else None,
            )


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


def av_length(p):
    """(video frames, audio samples), each counted on its own stream.

    The container's duration is the LONGER of the two, so it cannot see the gap
    between them — and that gap is the one thing concat cares about. Frames are
    counted packets; samples are decoded, never read off a header.

    Not the csv writer: a stream that carries side data (a display rotation, an
    iPhone's ambient-viewing block) gets it printed as an extra empty column,
    `84,`, and int() refused it (2026-10-14).
    """
    frames = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-count_packets", "-show_entries", "stream=nb_read_packets",
                  "-of", "default=nw=1:nk=1", p]).stdout.strip()
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-map", "0:a:0?",
                          "-f", "s16le", "-ac", "1", "-"],
                         stdin=subprocess.DEVNULL, capture_output=True).stdout
    return int(frames or 0), len(pcm) // 2


def _assert_lockstep(p, frames, what):
    got = av_length(p)
    want = (frames, frames * SAMPLES_PER_FRAME)
    if got != want:
        raise RuntimeError(f"{what} has {got[0]} frames / {got[1]} samples, "
                           f"wanted {want[0]} / {want[1]} ({frames / FPS:.4f}s)")


def prep_segment(src, tin, tout, dst, gain=1.0, vf=VF_FILL, af_extra=None):
    """One cut: trim, normalise geometry, PCM audio. Asserts both streams.

    The cut is round(d * FPS) frames over exactly that many frames of samples,
    and both ends are cut INSIDE the graph, because both bounds outside it came
    out wrong on a 30 fps iPhone MOV cut at 29.95s for 2.8667s (2026-10-05):

      - an output `-t` under `-r 30`: after an input seek the first frame is
        not at exactly 0, so `-r` duplicated one — 87 frames (2.900s) over
        2.867s of audio. The container reports the longer stream, so a ±0.10s
        check on it passed, and concat (which starts each file where the last
        container ended) left a gap per cut that the final asetpts closed up:
        the audio ran 50 ms early against the picture by the end.
      - `-frames:v N`: ends the file before the audio is complete.

    `apad` lets a source whose audio stops short still fill the cut; `atrim`
    is what bounds it (a bare apad never EOFs — delivery-traps #6). A source
    with too few FRAMES is refused, not padded: the timeline would run long.

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
    n = max(round(d * FPS), 1)
    af = f"asetpts=N/SR/TB,aresample={SR},volume={gain:.4f}"
    if af_extra:
        af += "," + af_extra
    af += f",apad,atrim=end_sample={n * SAMPLES_PER_FRAME}"
    # fps= again so end_frame counts FPS frames even under a caller's own vf;
    # setpts resets the seek's off-zero start that made -r duplicate a frame.
    vcut = f",fps={FPS},trim=end_frame={n},setpts=PTS-STARTPTS"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{tin:.3f}", "-i", src,
         "-vf", vf + vcut, "-af", af, *VENC, *AENC_PCM, dst])
    _assert_lockstep(dst, n, f"segment {dst} ({tin:.3f}-{tout:.3f}s of {src})")
    return dst


def concat(parts, dst):
    """Concat-demux copy. Asserts every part, and the total, stream by stream.

    The concat demuxer starts each file where the previous CONTAINER ended. A
    part whose audio is shorter than its picture leaves a gap there that the
    final asetpts=N/SR/TB closes up, so every later word lands early against
    its mouth — with every duration check green. Such a part is refused here
    by name, before it can shift the ones after it.
    """
    lengths = [av_length(p) for p in parts]
    for p, (frames, samples) in zip(parts, lengths):
        if samples != frames * SAMPLES_PER_FRAME:
            raise RuntimeError(
                f"concat part {p}: {frames} frames ({frames / FPS:.4f}s) over "
                f"{samples} samples ({samples / SR:.4f}s) — every part after it "
                f"would drift. Cut it with prep_segment().")
    lst = dst + ".txt"
    open(lst, "w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in parts))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", dst])
    _assert_lockstep(dst, sum(f for f, _ in lengths), f"concat {dst}")
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


def caption_window(first_start, last_end, next_start=None, work_dir=None):
    """(start, end) for a verbatim caption: on with the first word, padding after.

    A short quote has to be held to the dwell floor, and the padding has to go
    somewhere. Hand-timed builds put it in FRONT, so the line was on screen
    before anyone spoke — up to 0.99s on one finished build, and a viewer noticed
    (2026-10-21). Here it goes after the last word, up to the next caption.
    Only when the next line leaves no room does the start move earlier, and
    never past the lead gate_sync allows; a window still under the floor is
    returned as it is, so the Dwell gate says to merge the line with a neighbour.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gates import house
    spec = house(work_dir)
    floor = spec["captions"]["min_dwell_s"]
    max_lead = spec["sync"]["max_onset_lead_s"]
    start, end = first_start, max(last_end, first_start + floor)
    if next_start is not None and end > next_start:
        end = max(next_start, last_end)
        start = max(first_start - (max_lead - 0.05), end - floor)
        start = min(start, first_start)
    return round(start, 3), round(end, 3)


def _ass_t(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def spotlight_styles(work_dir=None):
    """The two `Style:` lines a Spotlight caption needs: the text, and its box.

    The box colour lives in its style, never in a `\\1c` tag: the Typography
    palette check reads every colour tag in the file and black is not a caption
    colour.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gates import house
    spec = house(work_dir)
    sp, base = spec["captions"]["spotlight"], spec["captions"]["styles"]
    size = base[sp["base_style"]]["size"]
    return [
        f"Style: {sp['style']},{sp['family']},{size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,0,5,8,60,60,0,1",
        f"Style: {sp['box_style']},{spec['font']['family']},20,{sp['box_colour']},"
        f"{sp['box_colour']},&HFF000000,&HFF000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
    ]


def spotlight_caption(start, end, text, english=None, work_dir=None, cy=None):
    """Dialogue lines for one 重點 caption: a rounded box (layer 0) and its text.

    `text` is ONE spoken phrase, verbatim, with `**gold**` around its keyword.
    Its size is derived, never chosen: as large as max_scale times the base
    caption's glyphs, as small as the box fitting in max_w_ratio of the frame
    allows, and a phrase that would come out under min_scale raises instead of
    shrinking — a long sentence is split, and only its key phrase is spotlit.
    The English line sits under the box in the house face, unscaled.
    """
    from PIL import ImageFont
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gates import house
    from title import _find_font, libass_em, spotlight_font
    spec = house(work_dir)
    cap = spec["captions"]
    sp, kw = cap["spotlight"], cap["keyword"]
    if "\\N" in text or "\n" in text:
        raise ValueError(f"Spotlight is one line: {text!r}")
    plain = text.replace("**", "")
    face = spotlight_font()
    base_glyph = cap["styles"][sp["base_style"]]["size"] / libass_em(_find_font())
    width_em = ImageFont.truetype(face, 100).getlength(plain) / 100
    fit = sp["max_w_ratio"] * W / (width_em + 2 * sp["pad_x_em"])
    glyph = min(sp["max_scale"] * base_glyph, fit)
    if glyph < sp["min_scale"] * base_glyph:
        raise ValueError(
            f"「{plain}」 fits only {glyph / base_glyph:.2f}x, under the Spotlight "
            f"minimum {sp['min_scale']}x: split the sentence and spotlight only its "
            f"key phrase")
    glyph = int(glyph)
    fs = round(glyph * libass_em(face))
    cy = round(cap["baseline_pct"] * H) if cy is None else cy

    gold = kw["colour"]
    parts = text.split("**")
    body = "".join(f"{{\\1c&H{gold[2:]}&}}{t}{{\\1c&HFFFFFF&}}" if i % 2 else t
                   for i, t in enumerate(parts) if t)
    line = f"{{\\an8\\pos({W // 2},{cy - fs // 2})\\fs{fs}}}{body}"
    if english:
        bl = spec["bilingual"]
        # an empty line of this height keeps the English clear of the box edge
        gap = round(glyph * (0.5 + sp["pad_y_em"] + 0.15) - fs / 2)
        line += (f"\\N{{\\fs{max(gap, 1)}}}\u3000"
                 f"\\N{{\\fn{spec['font']['family']}\\fs{bl['english_font_size']}"
                 f"\\c{bl['english_colour']}&}}{english}")

    w = ImageFont.truetype(face, glyph).getlength(plain) + 2 * sp["pad_x_em"] * glyph
    h = glyph * (1 + 2 * sp["pad_y_em"])
    x0, x1 = round((W - w) / 2), round((W + w) / 2)
    y0, y1 = round(cy - h / 2), round(cy + h / 2)
    r = round(min(sp["radius_em"] * glyph, h / 2))
    k = round(r * 0.448)               # cubic handle for a quarter circle
    box = (f"m {x0 + r} {y0} l {x1 - r} {y0} b {x1 - k} {y0} {x1} {y0 + k} {x1} {y0 + r} "
           f"l {x1} {y1 - r} b {x1} {y1 - k} {x1 - k} {y1} {x1 - r} {y1} "
           f"l {x0 + r} {y1} b {x0 + k} {y1} {x0} {y1 - k} {x0} {y1 - r} "
           f"l {x0} {y0 + r} b {x0} {y0 + k} {x0 + k} {y0} {x0 + r} {y0}")
    t0, t1 = _ass_t(start), _ass_t(end)
    return [
        f"Dialogue: 0,{t0},{t1},{sp['box_style']},,0,0,0,,"
        f"{{\\an7\\pos(0,0)\\p1}}{box}{{\\p0}}",
        f"Dialogue: 1,{t0},{t1},{sp['style']},,0,0,0,,{line}",
    ]


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
             ramp_s=0.30, speech_until="words"):
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

    The automatic mode cannot tell a voice from the room, so after the last
    word, crowd noise or footsteps on the closing shots kept it ducked and the
    ending sat ~17 dB under the cut (2026-10-20, caught by the critic, not a
    gate). ``speech_until`` releases the duck from that second on: the default
    ``"words"`` reads the last word's end from ``work_dir/words.json``
    (TIMELINE time, as the Sync gate reads it), a number sets it, and ``None``
    keeps the envelope-only behaviour. Ignored with ``speech_spans``, which
    already says where speech ends.
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
        if speech_until == "words":
            wp = os.path.join(work_dir, "words.json")
            ends = ([float(w["end"]) for w in json.load(open(wp, encoding="utf-8"))
                     if "end" in w] if os.path.exists(wp) else [])
            speech_until = max(ends) if ends else None
        if speech_until is not None:
            target[max(int(speech_until * sr / hop), 0):] = 1.0
            print(f"duck_mix: duck released after the last word at "
                  f"{speech_until:.2f}s")

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


def stage_delivery(work_dir, files, dest=".."):
    """Declare the finished set and where it goes — WITHOUT putting it there.

    Build the deliverables into the work dir under whatever names the script
    already uses, then call this, then gate EVERY video in the set. `gates.py`
    moves the whole set out to `dest` under the final names on the clean exit 0
    that completes it — every declared video passed, on the files as they are
    now. Until then a passing run reports what it is waiting for and moves
    nothing: on 2026-09-27 one version's pass published its never-gated sibling,
    which then failed Duck. Nothing else in this toolchain copies a file to the
    project's first level, so a build whose gates were never run leaves no
    postable file behind — it leaves a work dir.

        bk.stage_delivery(WORK, {"vp_music.mp4":   "devjam-recap.mp4",
                                 "vp_nomusic.mp4": "devjam-recap-nomusic.mp4",
                                 "cover.jpg":      "cover.jpg"})

    Writing a mapping rather than a naming convention is deliberate: the
    staging names are the build's business and the posted names are the
    user's, and inferring one from the other is how a rename goes silent.
    """
    if not isinstance(files, dict) or not files:
        raise ValueError("stage_delivery needs {staged_name: final_name}, "
                         "and an empty delivery is not a delivery")
    for staged, final in files.items():
        if os.path.sep in final or final in (".", ".."):
            raise ValueError(f"final name {final!r} must be a bare filename — "
                             f"the directory is the `dest` argument")
        if not os.path.exists(os.path.join(work_dir, staged)):
            raise FileNotFoundError(
                f"{staged} is not in {work_dir}. Declare the set AFTER building "
                f"it, so a missing file is a build error and not a publish one.")
    path = os.path.join(work_dir, "delivery.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"dir": dest, "files": files}, f, ensure_ascii=False, indent=1)
    print(f"  staged {len(files)} file(s) -> published by gates.py once every "
          f"video in the set has passed")
    return path


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
