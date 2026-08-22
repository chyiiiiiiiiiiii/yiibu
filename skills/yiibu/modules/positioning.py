"""Smart subtitle positioning using face detection.

cv2 (opencv-python) is optional: without it, face detection is skipped and
captions land at the house default position instead of erroring.
"""
from typing import Optional, Tuple, Dict

try:
    import cv2
except ImportError:
    cv2 = None


def detect_face_mediapipe(frame) -> Optional[Tuple[int, int, int, int]]:
    """Detect face using MediaPipe (higher accuracy than Haar).

    Returns (x, y, w, h) or None.
    """
    try:
        import mediapipe as mp
        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5) as face_det:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_det.process(rgb)
            if not results.detections:
                return None
            # Pick the detection with highest confidence
            best = max(results.detections, key=lambda d: d.score[0])
            bbox = best.location_data.relative_bounding_box
            h, w = frame.shape[:2]
            x = int(bbox.xmin * w)
            y = int(bbox.ymin * h)
            bw = int(bbox.width * w)
            bh = int(bbox.height * h)
            return (x, y, bw, bh)
    except Exception:
        # mediapipe missing OR incompatible API (e.g. 0.10+ dropped mp.solutions)
        # → fall through to Haar cascade fallback in detect_face()
        return None


def detect_face_haar(frame) -> Optional[Tuple[int, int, int, int]]:
    """Detect the largest face in a frame using Haar cascade (fallback).

    Returns (x, y, w, h) or None.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
    if len(faces) == 0:
        return None
    largest = max(faces, key=lambda f: f[2] * f[3])
    return tuple(largest)


def detect_face(frame) -> Optional[Tuple[int, int, int, int]]:
    """Detect face using MediaPipe (primary) with Haar cascade fallback.

    Returns (x, y, w, h) or None.
    """
    result = detect_face_mediapipe(frame)
    if result is not None:
        return result
    return detect_face_haar(frame)


_FACE_PADDING = 0.15       # 15% extra space around face bounding box
_MIN_CLEAR_ZONE = 0.12     # subtitle zone must be at least 12% of frame height


def calculate_subtitle_position(
    face_box: Optional[Tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
) -> Dict:
    """Determine optimal subtitle position based on face location.

    Returns dict with:
      - 'y_ratio': float (0.0=top, 1.0=bottom) — center of subtitle zone
      - 'alignment': int (ASS alignment code: 2=bottom-center, 8=top-center)
      - 'clear_top' / 'clear_bottom': float ratios bounding the face-free band
        (the safe zone big emphasis/hero captions must stay inside)
    """
    if face_box is None:
        # Default: bottom, centered. Face-free band = lower ~half of the frame.
        return {
            "y_ratio": 0.88,
            "alignment": 2,  # ASS: bottom-center
            "clear_top": 0.50,
            "clear_bottom": 0.98,
        }

    _, fy, _, fh = face_box

    # Face extent as ratios (0.0=top, 1.0=bottom)
    face_top_ratio = fy / frame_h
    face_bottom_ratio = (fy + fh) / frame_h

    # Add padding around face
    padded_top = max(0.0, face_top_ratio - _FACE_PADDING)
    padded_bottom = min(1.0, face_bottom_ratio + _FACE_PADDING)

    # Compute clear zone sizes
    clear_above = padded_top                  # space from frame top to face top
    clear_below = 1.0 - padded_bottom         # space from face bottom to frame bottom

    # Prefer bottom (natural viewer position), pick largest zone >= _MIN_CLEAR_ZONE
    if clear_below >= _MIN_CLEAR_ZONE:
        # Place subtitle at midpoint of clear zone below face
        y_ratio = padded_bottom + clear_below / 2
        return {
            "y_ratio": y_ratio, "alignment": 2,
            "clear_top": padded_bottom, "clear_bottom": 1.0,
        }
    elif clear_above >= _MIN_CLEAR_ZONE:
        # Place subtitle at midpoint of clear zone above face
        y_ratio = clear_above / 2
        return {
            "y_ratio": y_ratio, "alignment": 8,
            "clear_top": 0.0, "clear_bottom": padded_top,
        }
    else:
        # Face covers most of frame — force bottom with small margin
        return {
            "y_ratio": 0.90, "alignment": 2,
            "clear_top": 0.72, "clear_bottom": 0.98,
        }


def analyze_video_for_positioning(video_path: str) -> Dict:
    """Sample frames from video and determine consistent subtitle position.

    Samples 5 evenly-spaced frames, detects face in each, uses majority vote.
    """
    if cv2 is None:
        print("  opencv-python not installed — using default caption position "
              "(no face detection).")
        return calculate_subtitle_position(None, 1080, 1920)
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    sample_indices = [int(total_frames * i / 6) for i in range(1, 6)]
    face_positions = []

    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        face = detect_face(frame)
        if face:
            face_positions.append(face)

    cap.release()

    if not face_positions:
        return calculate_subtitle_position(None, frame_w, frame_h)

    # Use median face position
    median_face = face_positions[len(face_positions) // 2]
    return calculate_subtitle_position(median_face, frame_w, frame_h)
