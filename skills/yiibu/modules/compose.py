"""FFmpeg video composition -- final assembly of selfie + B-roll + subtitles."""
import json
import os
import subprocess
from typing import List, Dict, Optional, Tuple

from config import (
    OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS,
    BROLL_FADE_DURATION,
    PIP_SIZE, PIP_MARGIN, PIP_MARGIN_TOP, PIP_POSITION, PIP_BORDER_WIDTH,
    BROLL_LAYOUT, SPLIT_RATIO, SPLIT_BLUR_HEIGHT,
    BG_BROLL_RATIO, BG_BLUR_SIGMA, BG_GRADIENT_HEIGHT,
    ENCODING_PREFER_HARDWARE,
    BROLL_TRANSITION_TYPES, BROLL_TRANSITION_DURATION,
    BROLL_KENBURNS_ZOOM, BROLL_KENBURNS_DIRECTIONS,
    CTA_IMAGE_PATH, CTA_IMAGE_WIDTH_RATIO, CTA_IMAGE_TOP_MARGIN,
    CTA_IMAGE_FADE_IN, CTA_IMAGE_FADE_OUT,
    CTA_PHRASE_START, CTA_PHRASE_END,
    CUTOUT_LARGE_ENABLED,
)


def _get_video_codec_args() -> list:
    """Get video codec args, preferring hardware encoder on macOS.

    Returns list of FFmpeg codec arguments like ['-c:v', 'h264_videotoolbox']
    or ['-c:v', 'libx264', '-preset', 'fast'] as fallback.
    """
    if not ENCODING_PREFER_HARDWARE:
        return ["-c:v", "libx264", "-preset", "fast"]

    import platform
    if platform.system() == "Darwin":
        # Check if h264_videotoolbox is available
        try:
            result = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True, text=True, timeout=5,
            )
            if "h264_videotoolbox" in result.stdout:
                print("  Encoder: h264_videotoolbox (hardware)")
                return ["-c:v", "h264_videotoolbox", "-q:v", "65", "-allow_sw", "1"]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return ["-c:v", "libx264", "-preset", "fast"]


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _pip_xy(position: str = None) -> tuple:
    """Calculate PiP overlay x, y based on position string.

    For 'top-alternate' mode, call with explicit 'top-right' or 'top-left'.
    """
    pos = position or PIP_POSITION
    total = PIP_SIZE + PIP_BORDER_WIDTH * 2
    if pos == "bottom-right":
        x = OUTPUT_WIDTH - total - PIP_MARGIN
        y = OUTPUT_HEIGHT - total - PIP_MARGIN
    elif pos == "bottom-left":
        x = PIP_MARGIN
        y = OUTPUT_HEIGHT - total - PIP_MARGIN
    elif pos == "top-right":
        x = OUTPUT_WIDTH - total - PIP_MARGIN
        y = PIP_MARGIN_TOP
    else:  # top-left
        x = PIP_MARGIN
        y = PIP_MARGIN_TOP
    return x, y


def _build_pip_enable(
    active_broll: List[Dict],
    total_duration: float,
    indices: List[int] = None,
) -> str:
    """Build FFmpeg enable expression: show PiP only during B-roll segments.

    If indices is provided, only include segments at those indices (for alternating mode).
    """
    parts = []
    for i, seg in enumerate(active_broll):
        if indices is not None and i not in indices:
            continue
        start = seg["start_hint"]
        end = min(start + seg["duration"], total_duration)
        parts.append(f"between(t,{start:.3f},{end:.3f})")
    return "+".join(parts) if parts else "0"


def _get_transition_for_segment(index: int) -> str:
    """Get deterministic transition type for a B-roll segment."""
    return BROLL_TRANSITION_TYPES[index % len(BROLL_TRANSITION_TYPES)]


def _get_kenburns_direction(index: int) -> str:
    """Get deterministic Ken Burns direction for a still image segment."""
    return BROLL_KENBURNS_DIRECTIONS[index % len(BROLL_KENBURNS_DIRECTIONS)]


def _build_kenburns_zoompan(direction: str, dur: float, width: int, height: int) -> str:
    """Build zoompan filter string for Ken Burns effect on still images."""
    fps = OUTPUT_FPS
    dur_frames = max(int(dur * fps), 1)
    zoom = BROLL_KENBURNS_ZOOM
    step = (zoom - 1.0) / dur_frames

    if direction == "zoom_in_center":
        z = f"min(1.0+on*{step:.6f},{zoom})"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif direction == "zoom_out_center":
        z = f"max({zoom}-on*{step:.6f},1.0)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif direction == "pan_left":
        z = str(zoom)
        x = f"(iw-iw/zoom)*(1-on/{dur_frames})"
        y = "(ih-ih/zoom)/2"
    else:  # pan_right
        z = str(zoom)
        x = f"(iw-iw/zoom)*on/{dur_frames}"
        y = "(ih-ih/zoom)/2"

    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':"
        f"d={dur_frames}:s={width}x{height}:fps={fps}"
    )


def detect_cta_timing(words_path: str) -> Optional[Tuple[float, float]]:
    """Detect CTA phrase timing from word-level transcript.

    Searches from CTA_PHRASE_START to CTA_PHRASE_END (config.py) in the
    transcript. Image appears at the start marker, disappears at the end one.
    Returns (start_time, end_time) or None if not found.
    """
    if not words_path or not os.path.exists(words_path):
        return None

    with open(words_path, "r", encoding="utf-8") as f:
        words = json.load(f)

    start_time = None
    end_time = None

    # Search from the end backwards for "詳細" (CTA is always near closing)
    # Only require "詳" to appear in the last 30% of the video — handles Whisper char-level splits
    total_duration = words[-1].get("end", 0) if words else 0
    cta_search_start = max(30, total_duration * 0.7)
    cta_start_char = CTA_PHRASE_START[0]  # "詳" — first char is enough to trigger
    for i in range(len(words) - 1, -1, -1):
        text = words[i].get("text", "")
        if (CTA_PHRASE_START in text or text == cta_start_char) and words[i]["start"] > cta_search_start:
            start_time = words[i]["start"] - 0.2  # slight lead-in
            break

    if start_time is None:
        return None

    # Find end: word containing CTA_PHRASE_END ("追蹤") or starting char "追" after start
    cta_end_char = CTA_PHRASE_END[0]  # "追"
    for w in words:
        if w["start"] > start_time and (CTA_PHRASE_END in w.get("text", "") or w.get("text", "") == cta_end_char):
            end_time = w["start"]
            break

    if end_time is None:
        # Fallback: use last word's end time
        end_time = words[-1].get("end", start_time + 4)

    # Cap to max duration if configured
    try:
        from config import CTA_MAX_DURATION_SEC
        if CTA_MAX_DURATION_SEC > 0:
            end_time = min(end_time, start_time + CTA_MAX_DURATION_SEC)
    except ImportError:
        pass

    return (start_time, end_time)


def _build_split_filter(
    active_broll: List[Dict],
    subtitle_path: str,
    broll_input_offset: int,
    total_duration: float,
) -> str:
    """Build filter_complex for split layout: B-roll top, selfie bottom, gradient blend."""
    fade_d = BROLL_FADE_DURATION
    split_h = int(OUTPUT_HEIGHT * SPLIT_RATIO)
    blur_h = SPLIT_BLUR_HEIGHT

    # Step 1: Scale base video to 9:16
    filter_parts = [
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}[base]"
    ]

    # Step 2: For each B-roll, scale + transition + gradient alpha
    prev = "base"
    for i, seg in enumerate(active_broll):
        idx = i + broll_input_offset
        start = seg["start_hint"]
        dur = seg["duration"]
        end = min(start + dur, total_duration)
        is_image = seg.get("asset_type") != "video"

        transition = _get_transition_for_segment(i)
        trans_d = BROLL_TRANSITION_DURATION
        fade_out_st = max(end - fade_d, start + fade_d)

        # Build base scale/transform chain
        if is_image and BROLL_KENBURNS_ZOOM > 1.0:
            kb_dir = _get_kenburns_direction(i)
            kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, split_h)
            # Scale source to 2x output for smooth zoompan interpolation
            up_w = OUTPUT_WIDTH * 2
            up_h = split_h * 2
            base_chain = (
                f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={up_w}:{up_h},"
                f"{kb},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )
        elif transition == "zoom_in":
            zw = int(OUTPUT_WIDTH * 1.08)
            zh = int(split_h * 1.08)
            base_chain = (
                f"[{idx}:v]scale={zw}:{zh}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{split_h},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )
        else:
            base_chain = (
                f"[{idx}:v]scale={OUTPUT_WIDTH}:{split_h}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{split_h},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )

        # Gradient alpha for split blending
        geq_tail = (
            f"geq="
            f"lum='p(X,Y)':"
            f"cb='p(X,Y)':"
            f"cr='p(X,Y)':"
            f"a='if(lt(Y\\,{split_h - blur_h})\\,p(X\\,Y)\\,"
            f"p(X\\,Y)*({split_h}-Y)/{blur_h})'"
        )

        # Append fades + geq — slides skip fade-in (entry via motion)
        if transition in ("slide_left", "slide_up"):
            scale_filter = (
                base_chain
                + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1,"
                + geq_tail
                + f"[broll{idx}]"
            )
        else:
            entry_d = trans_d if transition == "zoom_in" else fade_d
            scale_filter = (
                base_chain
                + f"fade=t=in:st={start:.3f}:d={entry_d}:alpha=1,"
                + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1,"
                + geq_tail
                + f"[broll{idx}]"
            )
        filter_parts.append(scale_filter)

        # Build overlay — slides animate position, others static
        if transition == "slide_left":
            ovr = (
                f"[{prev}][broll{idx}]overlay="
                f"x='if(lt(t-{start:.3f},{trans_d}),"
                f"{OUTPUT_WIDTH}*(1-(t-{start:.3f})/{trans_d}),0)':"
                f"y=0:"
                f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
            )
        elif transition == "slide_up":
            ovr = (
                f"[{prev}][broll{idx}]overlay="
                f"x=0:"
                f"y='if(lt(t-{start:.3f},{trans_d}),"
                f"{split_h}*(1-(t-{start:.3f})/{trans_d}),0)':"
                f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
            )
        else:
            ovr = (
                f"[{prev}][broll{idx}]overlay=0:0:"
                f"enable='between(t,{start:.3f},{end:.3f})':"
                f"format=auto"
            )

        next_label = f"ovr{idx}"
        filter_parts.append(f"{ovr}[{next_label}]")
        prev = next_label

    # Step 3: Burn subtitles (no PiP needed — speaker visible in bottom half)
    filter_parts.append(f"[{prev}]ass={subtitle_path}[out]")
    return ";\n".join(filter_parts)


def _assign_segment_layouts(segments) -> List[str]:
    """Assign each B-roll segment a layout mode.

    Available modes: 'fullscreen', 'background', 'cutout-small'.
    ('cutout-large' is defined but disabled by default — set CUTOUT_LARGE_ENABLED=True to re-enable.)
    Weighted distribution: FS == CS > BG (background appears less frequently).
    Uses deterministic pseudo-random with constraints:
    - Never more than 2 consecutive same layout
    - A segment's explicit 'layout' field (dict input) forces that mode.

    Accepts either a segment list (to honor per-segment 'layout' overrides) or an int count.
    """
    import random
    if isinstance(segments, int):
        count = segments
        forced = [None] * count
    else:
        count = len(segments)
        forced = [(s.get("layout") if isinstance(s, dict) else None) for s in segments]
    rng = random.Random(count * 7)  # deterministic seed
    # Weighted pool: FS and CS appear 2x more than BG
    modes = ["fullscreen", "background", "cutout-small"]
    weights = [3, 1, 3]  # FS:BG:CS = 3:1:3
    if CUTOUT_LARGE_ENABLED:
        modes.append("cutout-large")
        weights.append(2)
    layouts = []
    for i in range(count):
        if forced[i]:
            layouts.append(forced[i])
            continue
        if i < 2:
            # First two segments: always non-cutout (avoid slow start)
            choice = "fullscreen" if i % 2 == 0 else "cutout-small"
        else:
            prev2 = layouts[-2:]
            if len(prev2) == 2 and prev2[0] == prev2[1]:
                # Force switch after 2 consecutive same
                candidates = [(m, w) for m, w in zip(modes, weights) if m != prev2[0]]
                c_modes, c_weights = zip(*candidates) if candidates else (modes, weights)
                choice = rng.choices(list(c_modes), weights=list(c_weights), k=1)[0]
            else:
                choice = rng.choices(modes, weights=weights, k=1)[0]
        layouts.append(choice)
    return layouts


def _build_mixed_filter(
    active_broll: List[Dict],
    subtitle_path: str,
    broll_input_offset: int,
    total_duration: float,
) -> str:
    """Build filter_complex that mixes fullscreen and background layouts per segment.

    Each B-roll segment is randomly assigned either:
    - fullscreen: B-roll covers entire frame + PiP circle for selfie
    - background: B-roll blurred in top half behind full-frame selfie

    PiP only appears during fullscreen segments (with alternating L/R).
    """
    fade_d = BROLL_FADE_DURATION
    pip_d = PIP_SIZE
    border = PIP_BORDER_WIDTH
    pip_total = pip_d + border * 2
    bg_h = int(OUTPUT_HEIGHT * BG_BROLL_RATIO)
    grad_h = BG_GRADIENT_HEIGHT
    blur_sig = BG_BLUR_SIGMA

    # Reuse layouts from pre-render (if available), otherwise assign fresh
    if active_broll and "_layout" in active_broll[0]:
        seg_layouts = [seg["_layout"] for seg in active_broll]
    else:
        seg_layouts = _assign_segment_layouts(active_broll)
    fs_indices = [i for i, l in enumerate(seg_layouts) if l == "fullscreen"]
    bg_indices = [i for i, l in enumerate(seg_layouts) if l == "background"]
    cl_indices = [i for i, l in enumerate(seg_layouts) if l == "cutout-large"]
    cs_indices = [i for i, l in enumerate(seg_layouts) if l == "cutout-small"]
    abbrev = {"fullscreen": "FS", "background": "BG", "cutout-large": "CL", "cutout-small": "CS", "split-1to1": "S1"}
    layout_str = " ".join(abbrev.get(l, l) for l in seg_layouts)
    print(f"  Mixed layout: {layout_str} "
          f"({len(fs_indices)}FS {len(bg_indices)}BG {len(cl_indices)}CL {len(cs_indices)}CS)")

    # Step 1: Scale base selfie to 9:16 (always present)
    filter_parts = [
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}[base]"
    ]

    # Step 1b: Create PiP circle (needed for fullscreen segments)
    has_fullscreen = len(fs_indices) > 0
    if has_fullscreen:
        face_crop_y = OUTPUT_HEIGHT // 6
        filter_parts.append(
            f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_WIDTH}:0:{face_crop_y},"
            f"scale={pip_d}:{pip_d},"
            f"format=yuva420p,"
            f"geq="
            f"lum='p(X,Y)':"
            f"cb='p(X,Y)':"
            f"cr='p(X,Y)':"
            f"a='if(lte(hypot(X-{pip_d}/2,Y-{pip_d}/2),{pip_d}/2-1),255,0)'"
            f"[pip_circle]"
        )
        filter_parts.append(
            f"color=white:{pip_total}x{pip_total},format=yuva420p,"
            f"geq="
            f"lum='p(X,Y)':"
            f"cb='p(X,Y)':"
            f"cr='p(X,Y)':"
            f"a='if(lte(hypot(X-{pip_total}/2,Y-{pip_total}/2),{pip_total}/2),255,0)'"
            f"[pip_border]"
        )
        filter_parts.append(
            f"[pip_border][pip_circle]overlay={border}:{border}:format=auto[pip_full]"
        )

    # Step 2: Chain B-roll overlays — each segment uses its assigned layout
    prev = "base"
    for i, seg in enumerate(active_broll):
        idx = i + broll_input_offset
        start = seg["start_hint"]
        dur = seg["duration"]
        end = min(start + dur, total_duration)
        is_image = seg.get("asset_type") != "video"
        fade_out_st = max(end - fade_d, start + fade_d)

        if seg_layouts[i] == "split-1to1":
            # --- Split 1:1 with gradient+blur blend at seam ---
            # B-roll fills top 960px with gradient alpha fade at bottom 250px.
            # Speaker crop extends upward to y=710, so it shows through the fading
            # B-roll for a smooth dissolve.
            broll_h = OUTPUT_HEIGHT // 2     # 960 (top half nominal height)
            grad_h_local = 250                # gradient blend zone (matches BG)
            blur_sig_local = BG_BLUR_SIGMA    # blur strength (0 = sharp like BG)
            face_y_src = 900                  # face center in source (1080x1920)
            spkr_top = broll_h - grad_h_local # speaker overlay starts at y=710
            spkr_h = OUTPUT_HEIGHT - spkr_top # speaker overlay height = 1210
            spkr_crop_top = max(0, min(1920 - spkr_h, face_y_src - 610))

            # B-roll chain — scale to 1080x960, blur+gradient alpha at bottom
            if is_image and BROLL_KENBURNS_ZOOM > 1.0:
                kb_dir = _get_kenburns_direction(i)
                kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, broll_h)
                up_w = OUTPUT_WIDTH * 2
                up_h = broll_h * 2
                broll_chain = (
                    f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                    f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                    f"crop={up_w}:{up_h},"
                    f"{kb},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )
            else:
                broll_chain = (
                    f"[{idx}:v]scale={OUTPUT_WIDTH}:{broll_h}:"
                    f"force_original_aspect_ratio=increase,"
                    f"crop={OUTPUT_WIDTH}:{broll_h},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )
            geq_alpha_local = (
                f"geq="
                f"lum='p(X,Y)':"
                f"cb='p(X,Y)':"
                f"cr='p(X,Y)':"
                f"a='if(lt(Y\\,{broll_h - grad_h_local})\\,p(X\\,Y)\\,"
                f"p(X\\,Y)*({broll_h}-Y)/{grad_h_local})'"
            )
            blur_part = f"gblur=sigma={blur_sig_local}," if blur_sig_local > 0 else ""
            scale_filter = (
                broll_chain
                + blur_part
                + f"fade=t=in:st={start:.3f}:d={fade_d}:alpha=1,"
                + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1,"
                + geq_alpha_local
                + f"[broll{idx}]"
            )
            filter_parts.append(scale_filter)

            # Cropped speaker overlay (1080×1210, extends up to y=710)
            speaker_crop = (
                f"[0:v]scale={OUTPUT_WIDTH}:1920:force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:1920,"
                f"crop={OUTPUT_WIDTH}:{spkr_h}:0:{spkr_crop_top},"
                f"format=yuva420p,"
                f"fade=t=in:st={start:.3f}:d={fade_d}:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1"
                f"[spkr{idx}]"
            )
            filter_parts.append(speaker_crop)

            # Order: speaker FIRST (so B-roll's fading bottom reveals speaker)
            ovr_spkr = (
                f"[{prev}][spkr{idx}]overlay=0:{spkr_top}:"
                f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
                f"[ovrS{idx}]"
            )
            filter_parts.append(ovr_spkr)
            ovr_broll = (
                f"[ovrS{idx}][broll{idx}]overlay=0:0:"
                f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
            )
            next_label = f"ovr{idx}"
            filter_parts.append(f"{ovr_broll}[{next_label}]")
            prev = next_label
            continue

        if seg_layouts[i] == "background":
            # --- Background mode: blurred top-half with gradient alpha ---
            if is_image and BROLL_KENBURNS_ZOOM > 1.0:
                kb_dir = _get_kenburns_direction(i)
                kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, bg_h)
                up_w = OUTPUT_WIDTH * 2
                up_h = bg_h * 2
                base_chain = (
                    f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                    f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                    f"crop={up_w}:{up_h},"
                    f"{kb},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )
            else:
                base_chain = (
                    f"[{idx}:v]scale={OUTPUT_WIDTH}:{bg_h}:"
                    f"force_original_aspect_ratio=increase,"
                    f"crop={OUTPUT_WIDTH}:{bg_h},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )

            geq_alpha = (
                f"geq="
                f"lum='p(X,Y)':"
                f"cb='p(X,Y)':"
                f"cr='p(X,Y)':"
                f"a='if(lt(Y\\,{bg_h - grad_h})\\,p(X\\,Y)\\,"
                f"p(X\\,Y)*({bg_h}-Y)/{grad_h})'"
            )

            blur_part = f"gblur=sigma={blur_sig}," if blur_sig > 0 else ""
            scale_filter = (
                base_chain
                + blur_part
                + f"fade=t=in:st={start:.3f}:d={fade_d}:alpha=1,"
                + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1,"
                + geq_alpha
                + f"[broll{idx}]"
            )
            filter_parts.append(scale_filter)

            ovr = (
                f"[{prev}][broll{idx}]overlay=0:0:"
                f"enable='between(t,{start:.3f},{end:.3f})':"
                f"format=auto"
            )

        else:
            # --- Fullscreen mode: B-roll covers entire frame ---
            transition = _get_transition_for_segment(i)
            trans_d = BROLL_TRANSITION_DURATION

            if is_image and BROLL_KENBURNS_ZOOM > 1.0:
                kb_dir = _get_kenburns_direction(i)
                kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                up_w = OUTPUT_WIDTH * 2
                up_h = OUTPUT_HEIGHT * 2
                base_chain = (
                    f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                    f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                    f"crop={up_w}:{up_h},"
                    f"{kb},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )
            elif transition == "zoom_in":
                zw = int(OUTPUT_WIDTH * 1.08)
                zh = int(OUTPUT_HEIGHT * 1.08)
                base_chain = (
                    f"[{idx}:v]scale={zw}:{zh}:"
                    f"force_original_aspect_ratio=increase,"
                    f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )
            else:
                base_chain = (
                    f"[{idx}:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                    f"force_original_aspect_ratio=increase,"
                    f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
                    f"format=yuva420p,"
                    f"setpts=PTS+{start:.3f}/TB,"
                )

            if transition in ("slide_left", "slide_up"):
                scale_filter = (
                    base_chain
                    + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1"
                    + f"[broll{idx}]"
                )
            else:
                entry_d = trans_d if transition == "zoom_in" else fade_d
                scale_filter = (
                    base_chain
                    + f"fade=t=in:st={start:.3f}:d={entry_d}:alpha=1,"
                    + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1"
                    + f"[broll{idx}]"
                )
            filter_parts.append(scale_filter)

            if transition == "slide_left":
                ovr = (
                    f"[{prev}][broll{idx}]overlay="
                    f"x='if(lt(t-{start:.3f},{trans_d}),"
                    f"{OUTPUT_WIDTH}*(1-(t-{start:.3f})/{trans_d}),0)':"
                    f"y=0:"
                    f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
                )
            elif transition == "slide_up":
                ovr = (
                    f"[{prev}][broll{idx}]overlay="
                    f"x=0:"
                    f"y='if(lt(t-{start:.3f},{trans_d}),"
                    f"{OUTPUT_HEIGHT}*(1-(t-{start:.3f})/{trans_d}),0)':"
                    f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
                )
            else:
                ovr = (
                    f"[{prev}][broll{idx}]overlay=0:0:"
                    f"enable='between(t,{start:.3f},{end:.3f})'"
                    f":format=auto"
                )

        next_label = f"ovr{idx}"
        filter_parts.append(f"{ovr}[{next_label}]")
        prev = next_label

    # Step 3: PiP overlay — only during fullscreen segments
    if has_fullscreen:
        if PIP_POSITION == "top-alternate" and len(fs_indices) > 1:
            import random
            rng = random.Random(len(fs_indices))
            right_fs = []
            left_fs = []
            last_side = None
            for fi in fs_indices:
                if last_side == "right":
                    side = "left" if rng.random() < 0.6 else "right"
                elif last_side == "left":
                    side = "right" if rng.random() < 0.6 else "left"
                else:
                    side = "right"
                if last_side == side:
                    check = right_fs if side == "right" else left_fs
                    if len(check) >= 1 and check[-1] == fs_indices[fs_indices.index(fi) - 1]:
                        side = "left" if side == "right" else "right"
                if side == "right":
                    right_fs.append(fi)
                else:
                    left_fs.append(fi)
                last_side = side

            right_x, right_y = _pip_xy("top-right")
            left_x, left_y = _pip_xy("top-left")
            right_enable = _build_pip_enable(active_broll, total_duration, right_fs)
            left_enable = _build_pip_enable(active_broll, total_duration, left_fs)
            filter_parts.append(f"[pip_full]split[pip_r][pip_l]")
            filter_parts.append(
                f"[{prev}][pip_r]overlay={right_x}:{right_y}:"
                f"enable='{right_enable}':format=auto[pip_right]"
            )
            filter_parts.append(
                f"[pip_right][pip_l]overlay={left_x}:{left_y}:"
                f"enable='{left_enable}':format=auto[pip_ovr]"
            )
            prev = "pip_ovr"
        else:
            pip_x, pip_y = _pip_xy()
            fs_enable = _build_pip_enable(active_broll, total_duration, fs_indices)
            filter_parts.append(
                f"[{prev}][pip_full]overlay={pip_x}:{pip_y}:"
                f"enable='{fs_enable}':format=auto[pip_ovr]"
            )
            prev = "pip_ovr"

    # Step 4: Burn ASS subtitles
    filter_parts.append(f"[{prev}]ass={subtitle_path}[out]")
    return ";\n".join(filter_parts)


def _build_split_1to1_filter(
    active_broll: List[Dict],
    subtitle_path: str,
    broll_input_offset: int,
    total_duration: float,
    face_y_source: int = 900,
) -> str:
    """50/50 split: B-roll fills top half, speaker head+shoulders bottom half.

    Source video (1080x1920) cropped around face_y_source to show head+shoulders,
    placed in bottom half of output. B-roll fills top half edge-to-edge with
    fade in/out per segment.
    """
    fade_d = BROLL_FADE_DURATION
    half_h = OUTPUT_HEIGHT // 2   # 960
    # Source crop: 1080x960 centered ~360px above face center so face lands
    # at upper third of bottom half
    crop_top = max(0, face_y_source - 360)
    if crop_top + half_h > 1920:
        crop_top = 1920 - half_h

    # Step 1: Base = cropped speaker placed at bottom half, top half black
    filter_parts = [
        # Take source 1080x1920, crop the 1080x960 region around the face,
        # then pad the top half with black to make 1080x1920
        f"[0:v]scale={OUTPUT_WIDTH}:1920:force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:1920,"
        f"crop={OUTPUT_WIDTH}:{half_h}:0:{crop_top},"
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:0:{half_h}:black"
        f"[base]"
    ]

    prev = "base"
    for i, seg in enumerate(active_broll):
        idx = i + broll_input_offset
        start = seg["start_hint"]
        dur = seg["duration"]
        end = min(start + dur, total_duration)
        is_image = seg.get("asset_type") != "video"
        fade_out_st = max(end - fade_d, start + fade_d)

        # B-roll scaled to fit top half 1080x960
        if is_image and BROLL_KENBURNS_ZOOM > 1.0:
            kb_dir = _get_kenburns_direction(i)
            kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, half_h)
            up_w = OUTPUT_WIDTH * 2
            up_h = half_h * 2
            base_chain = (
                f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={up_w}:{up_h},"
                f"{kb},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )
        else:
            base_chain = (
                f"[{idx}:v]scale={OUTPUT_WIDTH}:{half_h}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{half_h},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )

        scale_filter = (
            base_chain
            + f"fade=t=in:st={start:.3f}:d={fade_d}:alpha=1,"
            + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1"
            + f"[broll{idx}]"
        )
        filter_parts.append(scale_filter)

        # Overlay at top of frame (y=0)
        ovr = (
            f"[{prev}][broll{idx}]overlay=0:0:"
            f"enable='between(t,{start:.3f},{end:.3f})':"
            f"format=auto"
        )
        next_label = f"ovr{idx}"
        filter_parts.append(f"{ovr}[{next_label}]")
        prev = next_label

    filter_parts.append(f"[{prev}]ass={subtitle_path}[out]")
    return ";\n".join(filter_parts)


def _build_background_filter(
    active_broll: List[Dict],
    subtitle_path: str,
    broll_input_offset: int,
    total_duration: float,
) -> str:
    """Build filter_complex for background layout: B-roll blurred behind selfie.

    Selfie is the main foreground (full frame). B-roll appears blurred in the
    top portion with a gradient fade into the selfie below. Gives a premium
    'news anchor' feel without needing green screen.
    """
    fade_d = BROLL_FADE_DURATION
    bg_h = int(OUTPUT_HEIGHT * BG_BROLL_RATIO)
    grad_h = BG_GRADIENT_HEIGHT
    blur_sig = BG_BLUR_SIGMA

    # Step 1: Scale base selfie video to 9:16 (always visible as foreground)
    filter_parts = [
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}[base]"
    ]

    # Step 2: For each B-roll, scale to top portion, blur, gradient alpha, overlay
    prev = "base"
    for i, seg in enumerate(active_broll):
        idx = i + broll_input_offset
        start = seg["start_hint"]
        dur = seg["duration"]
        end = min(start + dur, total_duration)
        is_image = seg.get("asset_type") != "video"
        fade_out_st = max(end - fade_d, start + fade_d)

        # Scale B-roll to fill top portion width, crop to bg_h
        if is_image and BROLL_KENBURNS_ZOOM > 1.0:
            kb_dir = _get_kenburns_direction(i)
            kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, bg_h)
            up_w = OUTPUT_WIDTH * 2
            up_h = bg_h * 2
            base_chain = (
                f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={up_w}:{up_h},"
                f"{kb},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )
        else:
            base_chain = (
                f"[{idx}:v]scale={OUTPUT_WIDTH}:{bg_h}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{bg_h},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )

        # Apply Gaussian blur + gradient alpha fade at bottom edge
        # Alpha: full at top, fades to 0 at bottom over grad_h pixels
        geq_alpha = (
            f"geq="
            f"lum='p(X,Y)':"
            f"cb='p(X,Y)':"
            f"cr='p(X,Y)':"
            f"a='if(lt(Y\\,{bg_h - grad_h})\\,p(X\\,Y)\\,"
            f"p(X\\,Y)*({bg_h}-Y)/{grad_h})'"
        )

        blur_part = f"gblur=sigma={blur_sig}," if blur_sig > 0 else ""
        scale_filter = (
            base_chain
            + blur_part
            + f"fade=t=in:st={start:.3f}:d={fade_d}:alpha=1,"
            + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1,"
            + geq_alpha
            + f"[broll{idx}]"
        )
        filter_parts.append(scale_filter)

        # Overlay at top of frame (y=0)
        ovr = (
            f"[{prev}][broll{idx}]overlay=0:0:"
            f"enable='between(t,{start:.3f},{end:.3f})':"
            f"format=auto"
        )
        next_label = f"ovr{idx}"
        filter_parts.append(f"{ovr}[{next_label}]")
        prev = next_label

    # Step 3: Burn ASS subtitles (no PiP — selfie is foreground)
    filter_parts.append(f"[{prev}]ass={subtitle_path}[out]")
    return ";\n".join(filter_parts)


def _build_fullscreen_filter(
    active_broll: List[Dict],
    subtitle_path: str,
    broll_input_offset: int,
    total_duration: float,
) -> str:
    """Build filter_complex for fullscreen layout: B-roll covers all + PiP circle."""
    fade_d = BROLL_FADE_DURATION
    pip_d = PIP_SIZE
    border = PIP_BORDER_WIDTH
    pip_total = pip_d + border * 2
    pip_x, pip_y = _pip_xy()
    pip_enable = _build_pip_enable(active_broll, total_duration)

    # Step 1: Scale base video to 9:16
    filter_parts = [
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}[base]"
    ]

    # Step 1b: Create PiP circle from base video
    face_crop_y = OUTPUT_HEIGHT // 6
    filter_parts.append(
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_WIDTH}:0:{face_crop_y},"
        f"scale={pip_d}:{pip_d},"
        f"format=yuva420p,"
        f"geq="
        f"lum='p(X,Y)':"
        f"cb='p(X,Y)':"
        f"cr='p(X,Y)':"
        f"a='if(lte(hypot(X-{pip_d}/2,Y-{pip_d}/2),{pip_d}/2-1),255,0)'"
        f"[pip_circle]"
    )

    # Step 1c: Create white circle border
    filter_parts.append(
        f"color=white:{pip_total}x{pip_total},format=yuva420p,"
        f"geq="
        f"lum='p(X,Y)':"
        f"cb='p(X,Y)':"
        f"cr='p(X,Y)':"
        f"a='if(lte(hypot(X-{pip_total}/2,Y-{pip_total}/2),{pip_total}/2),255,0)'"
        f"[pip_border]"
    )

    # Step 1d: Compose border + circle into one PiP element
    filter_parts.append(
        f"[pip_border][pip_circle]overlay={border}:{border}:format=auto[pip_full]"
    )

    # Step 2: Chain B-roll overlays with varied transitions + Ken Burns
    prev = "base"
    for i, seg in enumerate(active_broll):
        idx = i + broll_input_offset
        start = seg["start_hint"]
        dur = seg["duration"]
        end = min(start + dur, total_duration)
        is_image = seg.get("asset_type") != "video"

        transition = _get_transition_for_segment(i)
        trans_d = BROLL_TRANSITION_DURATION
        fade_out_st = max(end - fade_d, start + fade_d)

        # Build base scale/transform chain — Ken Burns for images
        if is_image and BROLL_KENBURNS_ZOOM > 1.0:
            kb_dir = _get_kenburns_direction(i)
            kb = _build_kenburns_zoompan(kb_dir, dur, OUTPUT_WIDTH, OUTPUT_HEIGHT)
            # Scale source to 2x output for smooth zoompan interpolation
            up_w = OUTPUT_WIDTH * 2
            up_h = OUTPUT_HEIGHT * 2
            base_chain = (
                f"[{idx}:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={up_w}:{up_h},"
                f"{kb},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )
        elif transition == "zoom_in":
            zw = int(OUTPUT_WIDTH * 1.08)
            zh = int(OUTPUT_HEIGHT * 1.08)
            base_chain = (
                f"[{idx}:v]scale={zw}:{zh}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )
        else:
            base_chain = (
                f"[{idx}:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
                f"format=yuva420p,"
                f"setpts=PTS+{start:.3f}/TB,"
            )

        # Append alpha fades — slides skip fade-in (entry via motion)
        if transition in ("slide_left", "slide_up"):
            scale_filter = (
                base_chain
                + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1"
                + f"[broll{idx}]"
            )
        else:
            entry_d = trans_d if transition == "zoom_in" else fade_d
            scale_filter = (
                base_chain
                + f"fade=t=in:st={start:.3f}:d={entry_d}:alpha=1,"
                + f"fade=t=out:st={fade_out_st:.3f}:d={fade_d}:alpha=1"
                + f"[broll{idx}]"
            )
        filter_parts.append(scale_filter)

        # Build overlay — slides animate position, others static
        if transition == "slide_left":
            ovr = (
                f"[{prev}][broll{idx}]overlay="
                f"x='if(lt(t-{start:.3f},{trans_d}),"
                f"{OUTPUT_WIDTH}*(1-(t-{start:.3f})/{trans_d}),0)':"
                f"y=0:"
                f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
            )
        elif transition == "slide_up":
            ovr = (
                f"[{prev}][broll{idx}]overlay="
                f"x=0:"
                f"y='if(lt(t-{start:.3f},{trans_d}),"
                f"{OUTPUT_HEIGHT}*(1-(t-{start:.3f})/{trans_d}),0)':"
                f"enable='between(t,{start:.3f},{end:.3f})':format=auto"
            )
        else:
            ovr = (
                f"[{prev}][broll{idx}]overlay=0:0:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
                f":format=auto"
            )

        next_label = f"ovr{idx}"
        filter_parts.append(f"{ovr}[{next_label}]")
        prev = next_label

    # Step 3: Overlay PiP circle during B-roll segments
    if PIP_POSITION == "top-alternate" and len(active_broll) > 1:
        # Pseudo-random PiP position: randomly assign right/left but never same side twice
        import random
        rng = random.Random(len(active_broll))  # deterministic seed for reproducibility
        right_indices = []
        left_indices = []
        last_side = None
        for i in range(len(active_broll)):
            if last_side == "right":
                # Must go left, or 50% chance to go left
                side = "left" if rng.random() < 0.6 else "right"
            elif last_side == "left":
                side = "right" if rng.random() < 0.6 else "left"
            else:
                side = "right"  # first segment starts right
            # Prevent 3 consecutive same-side
            if last_side == side:
                same_count = 1
                check_list = right_indices if side == "right" else left_indices
                if len(check_list) >= 2 and check_list[-1] == i - 1:
                    side = "left" if side == "right" else "right"
            if side == "right":
                right_indices.append(i)
            else:
                left_indices.append(i)
            last_side = side
        right_x, right_y = _pip_xy("top-right")
        left_x, left_y = _pip_xy("top-left")
        right_enable = _build_pip_enable(active_broll, total_duration, right_indices)
        left_enable = _build_pip_enable(active_broll, total_duration, left_indices)
        # Split pip_full for two overlays
        filter_parts.append(f"[pip_full]split[pip_r][pip_l]")
        filter_parts.append(
            f"[{prev}][pip_r]overlay={right_x}:{right_y}:"
            f"enable='{right_enable}':format=auto[pip_right]"
        )
        filter_parts.append(
            f"[pip_right][pip_l]overlay={left_x}:{left_y}:"
            f"enable='{left_enable}':format=auto[pip_ovr]"
        )
        prev = "pip_ovr"
        sides = ["R" if i in right_indices else "L" for i in range(len(active_broll))]
        print(f"  PiP pseudo-random: {' '.join(sides)} ({len(right_indices)}R {len(left_indices)}L)")
    else:
        pip_label = "pip_ovr"
        filter_parts.append(
            f"[{prev}][pip_full]overlay={pip_x}:{pip_y}:"
            f"enable='{pip_enable}':format=auto[{pip_label}]"
        )
        prev = pip_label

    # Step 4: Burn ASS subtitles
    filter_parts.append(f"[{prev}]ass={subtitle_path}[out]")
    return ";\n".join(filter_parts)


def _build_cta_overlay_filter(
    cta_input_idx: int,
    cta_timing: Tuple[float, float],
    prev_label: str,
    total_duration: float,
) -> Tuple[str, str]:
    """Build filter chain for CTA image overlay (e.g. Substack screenshot).

    Returns (filter_string, output_label).
    """
    start, end = cta_timing
    target_w = int(OUTPUT_WIDTH * CTA_IMAGE_WIDTH_RATIO)
    fade_in_st = start
    fade_out_st = max(end - CTA_IMAGE_FADE_OUT, start + CTA_IMAGE_FADE_IN)

    out_label = "cta_ovr"
    filters = (
        f"[{cta_input_idx}:v]scale={target_w}:-1:flags=lanczos,format=rgba,"
        f"fade=t=in:st={fade_in_st:.3f}:d={CTA_IMAGE_FADE_IN}:alpha=1,"
        f"fade=t=out:st={fade_out_st:.3f}:d={CTA_IMAGE_FADE_OUT}:alpha=1"
        f"[cta_scaled];\n"
        f"[{prev_label}][cta_scaled]overlay=x=(W-w)/2:y={CTA_IMAGE_TOP_MARGIN}:"
        f"enable='between(t,{start:.3f},{end:.3f})':format=auto[{out_label}]"
    )
    return filters, out_label


def _prerender_cutout_segments(
    active_broll: List[Dict],
    selfie_path: str,
    broll_input_offset: int,
) -> None:
    """Pre-render cutout segments using MediaPipe person segmentation.

    Cutout segments are rendered as full-frame composite videos (person + B-roll),
    then swapped into active_broll so FFmpeg treats them as regular fullscreen overlays.
    """
    # Respect pre-set _layout from broll_plan.json (e.g. user override), fill gaps with auto
    if any("_layout" in seg for seg in active_broll):
        auto_layouts = _assign_segment_layouts(active_broll)
        seg_layouts = [
            seg.get("_layout", auto_layouts[i]) for i, seg in enumerate(active_broll)
        ]
    else:
        seg_layouts = _assign_segment_layouts(active_broll)
    # Store assigned layout on each segment for _build_mixed_filter to reuse
    for i, seg in enumerate(active_broll):
        seg["_layout"] = seg_layouts[i]
    cutout_indices = [
        i for i, l in enumerate(seg_layouts)
        if l in ("cutout-large", "cutout-small")
    ]
    if not cutout_indices:
        return

    try:
        from modules.cutout import render_cutout_segment
    except ImportError:
        # cutout needs cv2 + mediapipe; without them those segments degrade to
        # the fullscreen layout instead of crashing mid-compose.
        print("  cutout layouts need opencv-python + mediapipe — "
              "falling back to fullscreen for those segments.")
        for i in cutout_indices:
            active_broll[i]["_layout"] = "fullscreen"
        return
    import time

    print(f"  Pre-rendering {len(cutout_indices)} cutout segment(s)...")
    t0 = time.time()

    work_dir = os.path.dirname(active_broll[0]["asset_path"]) if active_broll else "/tmp"

    for i in cutout_indices:
        seg = active_broll[i]
        layout = seg_layouts[i]
        variant = "center-large" if layout == "cutout-large" else "bottom-left-small"
        broll_path = seg["asset_path"]
        is_image = seg.get("asset_type") != "video"
        start = seg["start_hint"]
        dur = seg["duration"]

        out_path = os.path.join(work_dir, f"cutout_{i:02d}.mp4")
        try:
            render_cutout_segment(
                selfie_path=selfie_path,
                broll_path=broll_path,
                broll_is_image=is_image,
                start_time=start,
                duration=dur,
                variant=variant,
                output_path=out_path,
            )
        except Exception as e:
            # e.g. segmenter model download failed offline — that segment
            # degrades to fullscreen; a layout is never worth a dead build.
            print(f"  cutout segment {i} failed ({e}); using fullscreen instead")
            seg["_layout"] = "fullscreen"
            continue

        # Replace the B-roll asset with the pre-rendered cutout composite
        seg["asset_path"] = out_path
        seg["asset_type"] = "video"
        seg["_cutout_variant"] = variant

    elapsed = time.time() - t0
    print(f"  Cutout pre-render: {elapsed:.1f}s")


def compose_video(
    trimmed_video: str,
    subtitle_path: str,
    broll_segments: List[Dict],
    output_path: str,
    bgm_audio: str = None,
    cta_image: str = None,
    words_path: str = None,
) -> str:
    """Compose the final video: selfie + B-roll overlays + subtitle burn-in.

    Layout modes (config BROLL_LAYOUT):
    - "mixed" (default): randomly alternates fullscreen + background per segment
    - "fullscreen": B-roll covers entire frame + circular PiP of selfie
    - "background": B-roll blurred in top half behind full-frame selfie
    - "split": B-roll in top 55%, selfie in bottom, gradient blend (no PiP needed)

    Args:
        trimmed_video: Path to the silence-removed selfie video.
        subtitle_path: Path to the .ass subtitle file.
        broll_segments: List of dicts with keys 'asset_path', 'asset_type',
            'start_hint', 'duration'. Segments without 'asset_path' are skipped.
        output_path: Where to write the final MP4.
        bgm_audio: Optional path to pre-mixed BGM audio (speech + ducked BGM).
        cta_image: Optional path to CTA overlay image (e.g. Substack screenshot).
        words_path: Optional path to words.json for CTA timing detection.

    Returns:
        Path to the output video file.
    """
    total_duration = get_video_duration(trimmed_video)

    # Detect CTA timing from transcript
    cta_timing = None
    if cta_image and os.path.exists(cta_image):
        cta_timing = detect_cta_timing(words_path)
        if cta_timing:
            print(f"  CTA overlay: {cta_timing[0]:.1f}s - {cta_timing[1]:.1f}s")
        else:
            print("  CTA overlay: phrase not found in transcript, skipping")

    active_broll = [
        s for s in broll_segments
        if s.get("asset_path") and os.path.exists(s["asset_path"])
    ]

    # Cap each B-roll segment's planned duration to the actual asset duration.
    # Veo 3 videos are always ~8s but plans may assign longer durations (e.g. 9.9s),
    # causing the last frame to freeze. This auto-fixes it via ffprobe.
    for seg in active_broll:
        if seg.get("asset_type") == "video":
            try:
                actual_dur = get_video_duration(seg["asset_path"])
                if seg["duration"] > actual_dur:
                    print(f"  B-roll duration cap: {seg.get('title', '?')} "
                          f"{seg['duration']:.1f}s → {actual_dur:.1f}s (actual)")
                    seg["duration"] = actual_dur
            except (subprocess.CalledProcessError, ValueError):
                pass  # ffprobe failed — keep original duration

    if not active_broll and not cta_timing:
        # Simple case: just crop + subtitles
        cmd = ["ffmpeg", "-y", "-i", trimmed_video]
        if bgm_audio:
            cmd.extend(["-i", bgm_audio])
        codec_args = _get_video_codec_args()
        cmd.extend([
            "-vf", (
                f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
                f"ass={subtitle_path}"
            ),
            "-map", "0:v",
            "-map", f"{'1' if bgm_audio else '0'}:a",
        ] + codec_args + [
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ])
        subprocess.run(cmd, check=True)
        return output_path

    # Pre-render cutout segments BEFORE building input list (replaces asset paths)
    broll_input_offset = 2 if bgm_audio else 1
    if BROLL_LAYOUT == "mixed":
        _prerender_cutout_segments(active_broll, trimmed_video, broll_input_offset)

    # Build input list: main video + optional BGM + each B-roll asset + optional CTA
    inputs = ["-i", trimmed_video]
    bgm_input_idx = None
    if bgm_audio:
        bgm_input_idx = 1
        inputs.extend(["-i", bgm_audio])

    for seg in active_broll:
        is_video = seg.get("asset_type") == "video"
        if is_video:
            inputs.extend(["-t", str(seg["duration"]), "-i", seg["asset_path"]])
        else:
            inputs.extend(["-loop", "1", "-t", str(seg["duration"]), "-i", seg["asset_path"]])

    # Add CTA image input (looped to cover the full duration for proper time axis)
    cta_input_idx = None
    if cta_timing and cta_image:
        cta_input_idx = broll_input_offset + len(active_broll)
        inputs.extend(["-loop", "1", "-t", f"{total_duration:.3f}", "-i", cta_image])

    # Build filter chain based on layout mode
    layout = BROLL_LAYOUT
    print(f"  Layout: {layout}")
    if layout == "split":
        filter_complex = _build_split_filter(
            active_broll, subtitle_path, broll_input_offset, total_duration
        )
    elif layout == "split-1to1":
        filter_complex = _build_split_1to1_filter(
            active_broll, subtitle_path, broll_input_offset, total_duration
        )
    elif layout == "background":
        filter_complex = _build_background_filter(
            active_broll, subtitle_path, broll_input_offset, total_duration
        )
    elif layout == "mixed":
        filter_complex = _build_mixed_filter(
            active_broll, subtitle_path, broll_input_offset, total_duration
        )
    else:
        filter_complex = _build_fullscreen_filter(
            active_broll, subtitle_path, broll_input_offset, total_duration
        )

    # Insert CTA overlay before subtitle burn-in
    if cta_timing and cta_input_idx is not None:
        # Replace the final [out] label: insert CTA between last overlay and subtitle
        # The current filter ends with: ...[prev_label]ass=subtitle[out]
        # We need: ...[prev_label_pre_sub] -> CTA -> [cta_ovr]ass=subtitle[out]
        ass_marker = f"ass={subtitle_path}[out]"
        if ass_marker in filter_complex:
            # Find the label before ass= and replace
            pre_sub_label = filter_complex.split(ass_marker)[0].rsplit("[", 1)[-1].rstrip("]")
            # Remove the ass line
            filter_complex = filter_complex.rsplit(f"[{pre_sub_label}]ass={subtitle_path}[out]", 1)[0]
            # Add CTA scale/fade + overlay (full filter chain)
            cta_filter, cta_label = _build_cta_overlay_filter(
                cta_input_idx, cta_timing, pre_sub_label, total_duration
            )
            filter_complex += cta_filter
            # Re-add subtitle burn-in
            filter_complex += f";\n[{cta_label}]ass={subtitle_path}[out]"

    codec_args = _get_video_codec_args()
    audio_map = f"{bgm_input_idx}:a" if bgm_audio else "0:a"
    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", audio_map,
            "-t", f"{total_duration:.3f}",
        ]
        + codec_args
        + [
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]
    )

    subprocess.run(cmd, check=True)
    return output_path
