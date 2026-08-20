"""Video post-production configuration.

Machine-specific knobs are overridable via YIIBU_* environment variables (listed in
docs/CONFIGURATION.md); every default below keeps working when they are unset,
so an existing setup changes nothing by upgrading.
"""
import os

# --- Paths ---
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR_PREFIX = os.environ.get("YIIBU_WORK_DIR_PREFIX", "/tmp/video-postprod")
OUTPUT_DIR = os.environ.get("YIIBU_OUTPUT_DIR", os.path.expanduser("~/Desktop"))

# --- Font ---
# Match by font NAME (fontconfig), not path. modules/title.py degrades to
# PingFang/Songti/Noto when the named font is not installed.
FONT_NAME = os.environ.get("YIIBU_FONT_NAME", "演示斜黑体")
FONT_SIZE_DEFAULT = 82
FONT_SIZE_KEYWORD = 90
FONT_SIZE_BROLL = 64
FONT_SIZE_COUNTER = 42
FONT_SIZE_TITLE = 120
FONT_SIZE_SUBTITLE_CARD = 56

# --- ASS Color Codes (AABBGGRR format: AA=alpha 00=opaque FF=transparent) ---
COLOR_WHITE = "&H00FFFFFF"
COLOR_BLACK = "&H00000000"
COLOR_DIM = "&H78FFFFFF"          # Semi-transparent white (unspoken karaoke state)
COLOR_GOLD = "&H0000D7FF"
COLOR_GOLD_SHADOW = "&H0000BFFF"  # Opaque gold for title card shadow
COLOR_OUTLINE = "&H00000000"      # Black outline
COLOR_SHADOW = "&H40000000"
COLOR_BG_SHADOW = "&H60000000"

# --- Subtitle ---
SUBTITLE_OUTLINE = 0
SUBTITLE_SHADOW = 5
SUBTITLE_BROLL_SHADOW_DEPTH = 5
SUBTITLE_FLOAT_PX = 25              # pixels to float up on appear
SUBTITLE_BOTTOM_EXTRA = 120         # extra margin from bottom edge (px)
SUBTITLE_FLOAT_MS = 250             # animation duration in ms
SUBTITLE_FADE_IN_MS = 0             # fade-in duration in ms (0 = hard cut, no fade)
KEYWORD_SCALE = 120
KEYWORD_POP_ANIMATION = False        # gold keywords scale-pop on entry; False = static

# --- Bilingual subtitles (English under the Chinese line) ---
SUBTITLE_BILINGUAL = True           # default: add an English line below each caption
FONT_SIZE_ENGLISH = 48              # English line font size (smaller than the CJK line)
COLOR_ENGLISH = "&H00EAEAEA"        # near-white, slightly dim for visual hierarchy
SUBTITLE_ENGLISH_KEYWORD_GOLD = True  # gold-highlight latin tech terms in the English line too

# --- Emphasis captions (punchline / emotional moments rendered large & staggered) ---
# Auto-detects the most emotionally-loaded / quotable lines and renders them big,
# split into stacked chunks at staggered positions (reference: IG-style hero captions).
SUBTITLE_EMPHASIS_ENABLED = True     # False → every line uses the normal caption style
FONT_SIZE_EMPHASIS = 132             # big CJK size for an emphasis moment
FONT_SIZE_EMPHASIS_ENGLISH = 60      # English line under an emphasis chunk
EMPHASIS_MAX_MOMENTS = 6             # cap emphasis moments per video (keep it special)
EMPHASIS_MAX_CHARS = 14              # only short punchy lines qualify (CJK char count)
EMPHASIS_STAGGER_X = 90              # px horizontal stagger of stacked chunks from center
EMPHASIS_BASE_Y_RATIO = 0.50         # vertical center of the first emphasis chunk (fraction of H)
EMPHASIS_BLOCK_STEP = 175            # px vertical distance between stacked chunks
EMPHASIS_MIN_CHUNK_SEC = 0.4         # merge a chunk back if it would show for less than this
EMPHASIS_MIN_PHRASE_SEC = 0.6        # phrases shorter than this stay in the normal style         # merge a chunk back if it would show for less than this

# --- Title Card ---
TITLE_CARD_DURATION = 2.5
TITLE_CARD_FADE_IN_MS = 400
TITLE_CARD_FADE_OUT_MS = 300
TITLE_CARD_OUTLINE = 5
TITLE_CARD_SHADOW = 6
TITLE_CARD_LAYER = 3
TITLE_CARD_GAP_PX = 30

# --- Phrase grouping ---
PHRASE_PAUSE_THRESHOLD = 0.3      # seconds — gap between words to trigger phrase break
PHRASE_MAX_CHARS = 10             # force break if phrase exceeds this
SUBTITLE_GAP = 0.08               # seconds gap between consecutive subtitles

# --- Layout ---
SUBTITLE_MAX_WIDTH_RATIO = 0.8    # max subtitle width as fraction of screen width

# --- Silence Cut ---
SILENCE_THRESHOLD = 0.04
SILENCE_MIN_DURATION = 0.5
CLAP_DB_THRESHOLD = -10

# --- ASR ---
WHISPER_MODEL = "large-v3"
WHISPER_LANGUAGE = "zh"
CONFIDENCE_THRESHOLD = 0.7

# --- B-roll Duration (seconds) ---
BROLL_DURATION = {
    "screenshot": 4,
    "product": 3,
    "stock_footage": 4.5,
    "generated": 3,
    "tweet_video": 5,
    "tweet_image": 4,
}
BROLL_TEXT_CHAR_RATE = 0.15
BROLL_TEXT_MIN = 2.0
BROLL_TEXT_MAX = 5.0
BROLL_FADE_DURATION = 0.3           # seconds fade in/out for B-roll overlays
BROLL_KENBURNS_ZOOM = 1.15          # end zoom factor for Ken Burns on still images

# --- PiP Circle (selfie overlay during B-roll) ---
PIP_SIZE = 260                       # diameter in pixels
PIP_MARGIN = 100                     # horizontal distance from screen edge (toward center)
PIP_MARGIN_TOP = 160                 # vertical distance from top edge
PIP_POSITION = "top-alternate"       # top-alternate | top-right | top-left | bottom-right | bottom-left
PIP_BORDER_WIDTH = 6                 # white border thickness
PIP_BORDER_COLOR = "white"

# --- B-roll Layout ---
BROLL_LAYOUT = "mixed"               # "mixed" (per-segment FS/BG/CS/split) | "fullscreen" | "background" | "split"
CUTOUT_LARGE_ENABLED = False         # True to include cutout-large (center) in mixed layout
SPLIT_RATIO = 0.55                   # B-roll occupies top 55% in split mode
SPLIT_BLUR_HEIGHT = 100              # gradient transition zone in pixels

# --- Background layout (B-roll behind full-frame selfie) ---
BG_BROLL_RATIO = 0.35                # B-roll background covers top 35% of frame (avoid face)
BG_BLUR_SIGMA = 0                    # 0 = sharp B-roll, blur only at gradient seam
BG_GRADIENT_HEIGHT = 250             # gradient blend zone height (px) between B-roll and selfie

BROLL_PEXELS_VIDEO_QUALITY = "hd"   # preferred Pexels video quality tier
AUTO_BROLL_MAX_ITEMS = 5             # max topics to extract from transcript

# --- Pixabay ---
PIXABAY_VIDEO_QUALITY = "medium"     # large | medium | small | tiny

# --- B-roll keyword alignment ---
BROLL_KEYWORD_SEARCH_WINDOW = 5.0    # seconds tolerance around timing hint for keyword search
BROLL_MIN_SEGMENT_DURATION = 2.0     # minimum duration for a single B-roll segment (seconds)

# --- AI-generated B-roll review ---
BROLL_REVIEW_MAX_RETRIES = 2         # max regeneration attempts before skipping
BROLL_REVIEW_MODEL = "gemini-2.5-flash"  # model for vision review

# --- BGM ---
BGM_LIBRARY_DIR = os.path.join(SKILL_DIR, "bgm-library")
BGM_VOLUME = 0.3                    # linear gain for ducked BGM before mixing
VOICE_VOLUME = 2.25                 # linear gain for speech/voice track (1.5 * 1.5)
BGM_CROSSFADE = 2.0                 # seconds of crossfade between segments
BGM_MOODS = ["chill", "energetic", "dramatic", "inspiring"]
BGM_DEFAULT_MOOD = "chill"
# YIIBU_BGM_TRACK overrides; otherwise a local personal default if present,
# else the first track in the default-mood folder. NO audio ships in the repo
# (see NOTICE.md / bgm-library/README.md); an empty library skips cleanly.
def _default_bgm():
    personal = os.path.join(BGM_LIBRARY_DIR, "chill", "falling_in_love.mp3")
    if os.path.exists(personal):
        return personal
    mood_dir = os.path.join(BGM_LIBRARY_DIR, BGM_DEFAULT_MOOD)
    if os.path.isdir(mood_dir):
        for f in sorted(os.listdir(mood_dir)):
            if f.lower().endswith((".mp3", ".wav", ".m4a")):
                return os.path.join(mood_dir, f)
    return personal  # missing: the bgm step already skips cleanly


BGM_DEFAULT_TRACK = os.environ.get("YIIBU_BGM_TRACK") or _default_bgm()

# Ducking parameters (sidechaincompress)
BGM_DUCK_THRESHOLD = 0.05
BGM_DUCK_RATIO = 3
BGM_DUCK_ATTACK = 200               # ms
BGM_DUCK_RELEASE = 1000             # ms

# Synth fallback frequencies (Hz) per mood
BGM_SYNTH_FREQUENCIES = {
    "chill": [261.63, 329.63, 392.00],       # C4, E4, G4 (C major)
    "energetic": [329.63, 415.30, 493.88],   # E4, G#4, B4 (E major)
    "dramatic": [261.63, 311.13, 392.00],    # C4, Eb4, G4 (C minor)
    "inspiring": [293.66, 369.99, 440.00],   # D4, F#4, A4 (D major)
}
BGM_SYNTH_PAD_DURATION = 30         # seconds per synth loop

# --- Context-aware B-roll ---
BROLL_COVERAGE_TARGET_MIN = 0.50        # target 50-70% B-roll coverage
BROLL_COVERAGE_TARGET_MAX = 0.70
BROLL_SELFIE_BREATHING_MIN = 3.0        # min selfie seconds between B-roll
BROLL_OPENING_SELFIE = 2.5              # selfie-only at video start
BROLL_CLOSING_SELFIE = 4.0              # selfie-only at video end
BROLL_PARALLEL_WORKERS = 4              # ThreadPoolExecutor workers for collection
BROLL_VALIDATE_RELEVANCE = True         # use Gemini vision to validate stock assets
BROLL_RELEVANCE_THRESHOLD = 50          # 0-100 score, >=50 approved
BROLL_MAX_VISUAL_MOMENTS = 20           # max LLM-extracted visual moments
BROLL_PRE_ARRIVAL_OFFSET = 0.5          # show visual 0.5s before keyword spoken
BROLL_ALIGN_MAX_SHIFT = 10.0            # max seconds to shift from LLM's original timing

# --- Whisper ---
WHISPER_INITIAL_PROMPT = (
    "以下是繁體中文的科技新聞播報，"
    "提到 Flutter、Dart、Rust、AI、GitHub、Gemini、Claude 等技術關鍵字。"
)

# --- Encoding ---
ENCODING_PREFER_HARDWARE = True         # prefer h264_videotoolbox on macOS

# --- Transitions ---
BROLL_TRANSITION_TYPES = ["fade", "zoom_in", "slide_left", "slide_up"]
# Generation models for the B-roll fallback chain. Defaults verified against
# the live models API 2026-08-16; override without editing code when Google
# ships newer ones. The chain fails safe: a bad model name falls through to the
# next fallback instead of erroring.
BROLL_VEO_MODEL = os.environ.get("YIIBU_VEO_MODEL", "veo-3.1-fast-generate-preview")
# Veo is the FIRST rung of the B-roll ladder and it is PAID — it needs the user's
# own Gemini API key, and there is no free tier for any Veo model. That order is
# deliberate: generated video is content-matched to the segment, where stock is
# only thematically close. Set YIIBU_VEO_ENABLED=0 to keep the rest of the ladder
# and skip the paid rung; with no key resolvable it skips itself anyway.
BROLL_VEO_ENABLED = os.environ.get("YIIBU_VEO_ENABLED", "1") not in ("0", "false", "no")
BROLL_GEMINI_IMAGE_MODEL = os.environ.get("YIIBU_GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
# Second image fallback via the OpenAI images API (needs an OpenAI key —
# YIIBU_OPENAI_KEY / ~/.zshrc / env). Skips cleanly with no key.
BROLL_OPENAI_IMAGE_MODEL = os.environ.get("YIIBU_OPENAI_IMAGE_MODEL", "gpt-image-2")

BROLL_TRANSITION_DURATION = 0.4         # seconds for entry/exit transitions
BROLL_KENBURNS_DIRECTIONS = ["zoom_in_center", "zoom_out_center", "pan_left", "pan_right"]

# --- CTA Image Overlay ---
# Personal newsletter screenshot (gitignored); YIIBU_CTA_IMAGE overrides. The CTA
# overlay only fires when the closing CTA phrase is detected, and skips cleanly
# when the image is absent.
CTA_IMAGE_PATH = os.environ.get(
    "YIIBU_CTA_IMAGE", os.path.join(SKILL_DIR, "assets", "substack.png"))
CTA_IMAGE_WIDTH_RATIO = 0.80       # 80% of screen width
CTA_IMAGE_TOP_MARGIN = 160         # pixels from top edge
CTA_IMAGE_FADE_IN = 0.4            # seconds
CTA_IMAGE_FADE_OUT = 0.4           # seconds
CTA_PHRASE_START = "今天"           # trigger phrase start marker in transcript
CTA_PHRASE_END = "傳給"             # trigger phrase end marker

# --- SFX ---
SFX_LIBRARY_DIR = os.path.join(SKILL_DIR, "sfx-library")
SFX_TRANSITION_FILE = os.path.join(SFX_LIBRARY_DIR, "whoosh.mp3")
SFX_TRANSITION_VOLUME = 1.5            # linear gain for transition SFX
SFX_TRANSITION_MIN_GAP = 5.0           # seconds gap between topics to insert SFX
SFX_DUCK_GAIN = 0.15                   # duck main audio to this gain during SFX (0.15 = -16dB)
SFX_DUCK_WINDOW = 0.8                  # seconds to duck around each SFX point

# --- Silence cut ---
SILENCE_CUT_CROSSFADE_MS = 50           # micro-crossfade at cut points (ms)

# --- Output ---
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
OUTPUT_FPS = 30
