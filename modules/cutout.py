"""Cutout compositing — person segmentation overlay on B-roll background.

Uses MediaPipe selfie segmenter to extract person from selfie video,
then composites onto B-roll. Two variants:
- center-large: person fills most of frame, B-roll as atmospheric background
- bottom-left-small: person small at bottom-left, B-roll prominent
"""
import cv2
import numpy as np
import os
import subprocess
from typing import Dict, Tuple

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from config import OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS

# --- Config ---
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite"
import tempfile
MODEL_PATH = os.path.join(tempfile.gettempdir(), "selfie_segmenter.tflite")

# The only two variants render_cutout_segment knows how to draw. These are NOT
# the BROLL_LAYOUT names — "cutout-large" / "cutout-small" are what a caller
# says, and compose._prerender_cutout_segments maps those onto these.
VARIANTS = ("center-large", "bottom-left-small")

# Center-large variant
CL_FADE_START = 0.65   # start fading person at 65% of frame height
CL_FADE_END = 0.85     # fully B-roll at 85%

# Bottom-left-small variant
BLS_SCALE = 0.45        # person scaled to 45% of frame width
BLS_X_OFFSET = 40       # px from left edge
BLS_Y_BOTTOM_MARGIN = 80  # px from bottom
BLS_FADE_START = 0.75   # relative to person height
BLS_FADE_END = 0.95

# Frame-skip: run segmenter every Nth frame, reuse mask for skipped frames
SEGMENTER_SKIP_FRAMES = 2  # process every 2nd frame (50% speedup)


def _ensure_model():
    """Download selfie segmenter model if not cached.

    Raises RuntimeError with a readable message on network failure so the
    caller's layout fallback can catch it, instead of a raw urllib traceback.
    """
    if os.path.exists(MODEL_PATH):
        return
    import urllib.request
    print("  Downloading selfie segmenter model...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    except Exception as e:
        raise RuntimeError(f"selfie segmenter model download failed: {e}") from e


def _build_gradient(h: int, w: int, fade_start_ratio: float, fade_end_ratio: float) -> np.ndarray:
    """Build vertical gradient mask: 1.0 above fade_start, 0.0 below fade_end."""
    fade_start = int(h * fade_start_ratio)
    fade_end = int(h * fade_end_ratio)
    gradient = np.ones((h, w), dtype=np.float32)
    for y in range(fade_start, min(fade_end, h)):
        gradient[y, :] = 1.0 - (y - fade_start) / max(fade_end - fade_start, 1)
    gradient[min(fade_end, h):, :] = 0.0
    return gradient


def _check_variant(variant: str) -> str:
    """Reject a variant name the renderer cannot draw, before it draws anything.

    The renderer branches `if variant == "bottom-left-small": ... else: ...`,
    so ANY other string silently rendered the center-large composite and
    returned success. Passing the BROLL_LAYOUT names — "cutout-large" and
    "cutout-small" — is the obvious way to get this wrong, and it produced two
    identical clips from two calls asking for two different things. Nothing
    failed; the only symptom was output that looked wrong to a person.
    """
    if variant not in VARIANTS:
        raise ValueError(
            f"unknown cutout variant {variant!r}; expected one of "
            f"{' / '.join(VARIANTS)}. If you have a BROLL_LAYOUT value "
            f"(cutout-large, cutout-small), map it first — see "
            f"compose._prerender_cutout_segments."
        )
    return variant


def render_cutout_segment(
    selfie_path: str,
    broll_path: str,
    broll_is_image: bool,
    start_time: float,
    duration: float,
    variant: str,
    output_path: str,
) -> str:
    """Render a cutout composite clip for one B-roll segment.

    Args:
        selfie_path: Path to the selfie video (silence_removed.mp4).
        broll_path: Path to the B-roll asset (video or image).
        broll_is_image: True if B-roll is a still image.
        start_time: Start time in selfie video (seconds).
        duration: Duration of the segment (seconds).
        variant: "center-large" or "bottom-left-small".
        output_path: Where to write the composited clip.

    Returns:
        Path to the rendered clip.
    """
    _check_variant(variant)

    # Early-return: if broll asset is a pre-rendered cutout composite,
    # just copy it through. Marker: filename starts with "prerendered_cutout_".
    if os.path.basename(broll_path).startswith("prerendered_cutout_"):
        import shutil
        shutil.copy(broll_path, output_path)
        return output_path

    _ensure_model()

    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    # Init segmenter
    segmenter = vision.ImageSegmenter.create_from_options(
        vision.ImageSegmenterOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=MODEL_PATH),
            output_category_mask=True,
            running_mode=vision.RunningMode.IMAGE,
        )
    )

    # Open selfie
    cap_selfie = cv2.VideoCapture(selfie_path)
    fps = cap_selfie.get(cv2.CAP_PROP_FPS) or OUTPUT_FPS
    cap_selfie.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000)

    # Open B-roll
    if broll_is_image:
        broll_frame = cv2.imread(broll_path)
        broll_static = cv2.resize(broll_frame, (W, H))
        cap_broll = None
        broll_fps_ratio = 0.0
    else:
        cap_broll = cv2.VideoCapture(broll_path)
        broll_static = None
        broll_fps = cap_broll.get(cv2.CAP_PROP_FPS) or fps
        broll_fps_ratio = broll_fps / fps  # e.g., 24/60 = 0.4

    # Setup output (raw, then re-encode)
    raw_path = output_path + ".raw.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, fps, (W, H))

    total_frames = int(duration * fps)

    if variant == "bottom-left-small":
        person_w = int(W * BLS_SCALE)
        person_h = int(H * BLS_SCALE)
        person_y_top = H - BLS_Y_BOTTOM_MARGIN - person_h
        gradient = _build_gradient(person_h, person_w, BLS_FADE_START, BLS_FADE_END)
    else:
        gradient = _build_gradient(H, W, CL_FADE_START, CL_FADE_END)

    broll_accum = 0.0
    current_broll = None
    cached_person_f = None  # reuse mask for skipped frames
    frame_idx = 0

    for _ in range(total_frames):
        ret, selfie = cap_selfie.read()
        if not ret:
            break

        # Get B-roll frame — advance at B-roll's native FPS, not selfie FPS
        if cap_broll is not None:
            broll_accum += broll_fps_ratio
            while broll_accum >= 1.0:
                ret2, frame = cap_broll.read()
                if ret2:
                    current_broll = frame
                # If B-roll ends, hold last frame (no loop)
                broll_accum -= 1.0
            if current_broll is None:
                ret2, current_broll = cap_broll.read()
                if not ret2:
                    break
            broll_r = cv2.resize(current_broll, (W, H))
        else:
            broll_r = broll_static.copy()

        # Segment person (skip frames: reuse mask for intermediate frames)
        if frame_idx % SEGMENTER_SKIP_FRAMES == 0 or cached_person_f is None:
            rgb = cv2.cvtColor(selfie, cv2.COLOR_BGR2RGB)
            result = segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            cat_mask = result.category_mask.numpy_view()

            mask_u8 = (cat_mask == 0).astype(np.uint8) * 255
            mask_u8 = cv2.erode(mask_u8, kernel, iterations=2)
            mask_smooth = cv2.GaussianBlur(mask_u8, (11, 11), 5)
            person_f = mask_smooth.astype(np.float32) / 255.0
            cached_person_f = person_f
        else:
            person_f = cached_person_f
        frame_idx += 1

        if variant == "bottom-left-small":
            # Scale down person + mask, overlay at bottom-left
            selfie_small = cv2.resize(selfie, (person_w, person_h))
            mask_small = cv2.resize(person_f, (person_w, person_h))
            mask_small = mask_small * gradient
            mask_3 = np.stack([mask_small] * 3, axis=-1)

            comp = broll_r.astype(np.float32)
            y1 = max(0, person_y_top)
            y2 = min(H, person_y_top + person_h)
            sy1 = y1 - person_y_top
            sy2 = sy1 + (y2 - y1)
            roi = comp[y1:y2, BLS_X_OFFSET:BLS_X_OFFSET + person_w]
            person_roi = selfie_small[sy1:sy2].astype(np.float32)
            mask_roi = mask_3[sy1:sy2]
            comp[y1:y2, BLS_X_OFFSET:BLS_X_OFFSET + person_w] = (
                person_roi * mask_roi + roi * (1 - mask_roi)
            )
            out.write(comp.astype(np.uint8))
        else:
            # Center-large: person fills frame with bottom gradient
            person_f = person_f * gradient
            person_3 = np.stack([person_f] * 3, axis=-1)
            comp = (selfie.astype(np.float32) * person_3 +
                    broll_r.astype(np.float32) * (1 - person_3))
            out.write(comp.astype(np.uint8))

    cap_selfie.release()
    if cap_broll:
        cap_broll.release()
    out.release()
    segmenter.close()

    # Re-encode with H.264 for FFmpeg compatibility
    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_path,
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", output_path],
        capture_output=True, check=True,
    )
    os.remove(raw_path)
    return output_path
