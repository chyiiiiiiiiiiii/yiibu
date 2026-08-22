# EXAMPLE — the accepted I/O Connect 2026 Day-1 build (2:02, 39 segments,
# eleven versions to converge). Paths refer to the original machine; read this
# for the SHAPE (two caption layers, authored-vs-verbatim split, width check
# inside generation), not to run as-is.
#!/usr/bin/env python3
"""Author the ASS caption track for the I/O Connect 花絮 (v2).

House style, matched to 雅香石頭火鍋-花絮-v10:
  * rounded dark pill, centred at 18% of frame height (same as modules/title.py);
  * captions centred on the 70% baseline — never pinned to the bottom edge,
    where the Reels/Shorts UI eats them.

Caption content is split in two:
  * the pill names the thing (booth / session / section);
  * the 70% line explains it, authored from what the booth boards and slides
    actually say — except for the keynote clips, where it is verbatim speech
    (the only ASR that scored 0.84-1.00; booth audio ran 0.2-0.7).
"""
import json
import os
import re
from PIL import ImageFont

W = os.path.dirname(os.path.abspath(__file__))
FONT = "演示斜黑体"
FONT_FILE = "~/Library/Fonts/演示斜黑体.otf"

FRAME_W, FRAME_H = 1080, 1920
PILL_Y = int(0.23 * FRAME_H)      # 442 — house position for the top pill
BASE_Y = int(0.70 * FRAME_H)      # 1344 — the caption baseline
PILL_SIZE = 56
SPLIT_LABEL_Y = 48                # inside the dark band above the official panel
SPLIT_CREDIT_Y = 668              # just inside the bottom of the official panel

tl = json.load(open(f"{W}/timeline.json"))
T = {s["id"]: (s["start"], s["dur"]) for s in tl["segments"]}
TOTAL = tl["total"]


def t(sid, off=0.0):
    return T[sid][0] + off


def end(sid, off=0.0):
    return T[sid][0] + T[sid][1] + off


def ts(sec):
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}"


GOLD = "{\\1c&H0000D7FF&}"
WHITE = "{\\1c&H00FFFFFF&}"

KEYWORDS = sorted([
    "Google Gemma 4", "Android XR", "XREAL Aura", "HTML-in-canvas", "WebGPU",
    "LiteRT-LM.js", "LiteRT", "MCP", "Antigravity", "Gemini", "Gemma",
    "Agent", "DOM", "Canvas",
], key=len, reverse=True)   # longest first: "LiteRT" must not match inside "LiteRT-LM.js"


_KEYWORD_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS))


def gold(text):
    """Gold-highlight tech terms in ONE pass. A per-keyword replace loop re-matches
    inside text it just tagged ("LiteRT" inside "LiteRT-LM.js") and nests the tags."""
    return _KEYWORD_RE.sub(lambda m: GOLD + m.group(0) + WHITE, text)


EVENTS = []


def ev(layer, a, b, style, text):
    EVENTS.append((layer, a, b, style, text))


PILLS = []


def pill(sid, text, a=0.25, b=-0.15):
    """House rounded pill. Rendered by the skill's own modules/title.py (PIL, properly
    antialiased, width hugs the text) — not drawn in ASS, which came out coarse."""
    PILLS.append({"text": text, "start": round(t(sid, a), 3), "end": round(end(sid, b), 3)})


AT_BASE = f"{{\\an5\\pos({FRAME_W//2},{BASE_Y})}}"


def note(sid, text, a=0.25, b=-0.15):
    """Explanatory caption, centred on the 70% baseline."""
    ev(4, t(sid, a), end(sid, b), "Note", AT_BASE + gold(text))


def speech(sid, lines):
    for a, b, tx in lines:
        ev(4, t(sid, a), t(sid, b), "Speech", AT_BASE + gold(tx))


def split_labels(sid, note_text):
    """Label band + source credit for a split-layout XR segment."""
    a, b = t(sid, 0.15), end(sid, -0.1)
    ev(3, a, b, "SplitLabel",
       f"{{\\an5\\pos({FRAME_W//2},{SPLIT_LABEL_Y})}}眼鏡裡看到的畫面")
    ev(3, a, b, "Credit",
       f"{{\\an5\\pos({FRAME_W//2},{SPLIT_CREDIT_Y})}}畫面來源：Google 官方 Android XR 影片")
    ev(4, a, b, "Note", AT_BASE + gold(note_text))


# ---------------------------------------------------------------- HOOK
ev(5, t("s01", 0.15), end("s01", -0.05), "Hook",
   f"{{\\an5\\pos({FRAME_W//2},{BASE_Y})}}在空氣裡捏一下\\N就翻到下一頁")
ev(5, t("s02", 0.1), end("s03", -0.1), "Hook2",
   f"{{\\an5\\pos({FRAME_W//2},{BASE_Y})}}2026 Google I/O Connect\\N{{\\fs64}}上海 · Day 1")

# ---------------------------------------------------------------- 入場
pill("s04", "朋友", b=-0.1)
note("s04", "早上先跟戰友會合")
pill("s06", "一天，三種現場")
note("s06", "Session · Workshop\\N攤位展覽同時開跑")
note("s07", "先去逛展區")

# ---------------------------------------------------------------- 展區
pill("s08", "Gemini 奇趣影棚")
note("s08", "站上去拍一張\\NGemini 把你放進新場景")
pill("s11", "Antigravity 街機遊戲實驗室")
note("s11", "敲一段提示詞\\NAI 做出一台復古街機")
note("s12", "當場就能開玩")
pill("s13", "HTML-in-canvas Web API")
note("s13", "把 DOM 融進 Canvas")
note("s14", "3D 場景裡的文字\\N可以框選、可以自動翻譯")
note("s15", "現場示範：一鍵翻成中文", a=0.4)
pill("s16", "Web AI × LiteRT-LM.js")
note("s16", "透過 WebGPU\\N在瀏覽器中執行端側 AI")
note("s17", "LiteRT-LM.js runtime\\N現場直接上手 Gemma 模型")
pill("s18", "AI 無障礙外掛")
note("s18", "螢幕閱讀器讀不出來的圖片\\N交給 AI 講給視障使用者聽")
note("s19", "議程後大排長龍的攤位")
note("s20", "工程師的哏牆，一定要拍")

# ---------------------------------------------------------------- XR
pill("s21", "Android XR × XREAL Aura")
note("s21", "無邊際的空間畫布\\N+ Gemini 多模態輔助")
note("s22", "先看實機")

pill("x1", "換我戴上去試試")
note("x1", "食指拇指輕輕一捏\\N就是點一下")
split_labels("x2", "主畫面直接浮在真實房間裡")
note("x3", "捏太久就變成長按\\N力道要拿捏")
split_labels("x4", "整片視野\\N換成另一個地方")
split_labels("x5", "三場球賽可以同時開著看")

# ---------------------------------------------------------------- Sessions
pill("s25", "議程：AI 無障礙外掛")
note("s25", "講者分享第一線的無障礙需求")

speech("s26", [
    (0.30, 2.60, "比如為螢幕閱讀器\\N的重度使用者"),
    (2.60, 5.30, "打造更完整的閱讀功能"),
])
speech("s27", [
    (0.20, 2.10, "但是一旦遇到數學內容"),
    (2.10, 4.05, "它就只能去讀圖片、圖形"),
])
speech("s28", [
    (0.25, 3.00, "借助多模態模型\\N的理解能力"),
    (3.00, 5.90, "我們能夠將\\N圖片裡的數學公式"),
    (5.90, 7.95, "轉譯為結構化的程式碼"),
])
speech("s28b", [
    (0.25, 3.60, "螢幕閱讀器使用者就可以\\N按照自己的閱讀習慣"),
    (3.60, 5.25, "讀到公式中的全部細節"),        # venue subtitle: 全部, not 任何
])
speech("s28c", [
    (0.30, 2.55, "曾經閱讀一本書\\N費時又費力"),
    (2.55, 5.25, "現在有了 AI 外掛\\N可以一鍵識別"),
    (5.25, 7.45, "節省了很多的時間\\N提高效率"),   # venue subtitle: 節省, not 減少
])
pill("s29", "LiteRT · 端側語音辨識")
note("s29", "Parakeet · Whisper\\NQwen ASR · Moonshine\\N最小 <100MB 就能跑")
pill("s31", "Project Montage", a=0.2, b=-0.1)
note("s31", "用 MCP 串起多個 Agent\\N分鏡 → 生圖 → 生影片\\N→ 字幕 → 旁白 → 配樂", a=0.2, b=-0.1)
note("s32", "這支飯店宣傳片\\N整條產線都是 Agent 做的", a=0.3)

# ---------------------------------------------------------------- 結尾
ev(5, t("s33", 0.35), t("s33", 2.30), "Emph",
   f"{{\\an5\\pos({FRAME_W//2},{BASE_Y})}}不僅是追趕")
ev(5, t("s33", 2.30), t("s33", 5.20), "Emph",
   f"{{\\an5\\pos({FRAME_W//2},{BASE_Y})}}更是並肩同行")

# closing block — over the landmark shot, no black card
ev(5, t("s36", 0.2), end("s36"), "CardBig", AT_BASE + "DAY1，明天繼續")
ev(5, t("s36", 0.2), end("s36"), "CardList",
   f"{{\\an5\\pos({FRAME_W//2},{BASE_Y + 210})}}"
   + gold("Android XR · XREAL Aura · Gemini\\N"
          "Antigravity · HTML-in-canvas · WebGPU\\N"
          "LiteRT · MCP · Gemma"))

# ---------------------------------------------------------------- write ASS
HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {FRAME_W}
PlayResY: {FRAME_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Speech,{FONT},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1
Style: Note,{FONT},76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,0,5,5,60,60,0,1
Style: SplitLabel,{FONT},50,&H0000D7FF,&H0000D7FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1
Style: Credit,{FONT},40,&H00E6E6E6,&H00E6E6E6,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,4,5,40,40,0,1
Style: Hook,{FONT},104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,7,5,60,60,0,1
Style: Hook2,{FONT},74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,7,5,60,60,0,1
Style: Emph,{FONT},124,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,7,5,60,60,0,1
Style: CardBig,{FONT},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,7,5,60,60,0,1
Style: CardList,{FONT},44,&H00E6E6E6,&H00E6E6E6,&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,0,5,5,50,50,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

FADE = {
    "Note": "{\\fad(140,120)}", "Speech": "",
    "SplitLabel": "{\\fad(180,150)}", "Credit": "{\\fad(180,150)}",
    "Hook": "{\\fad(120,150)}", "Hook2": "{\\fad(150,180)}",
    "Emph": "{\\fad(160,200)}",
    "CardBig": "{\\fad(250,0)}", "CardList": "{\\fad(250,0)}",
}

lines = []
for layer, a, b, style, text in sorted(EVENTS, key=lambda e: (e[1], e[0])):
    lines.append(
        f"Dialogue: {layer},{ts(a)},{ts(b)},{style},,0,0,0,,{FADE.get(style,'')}{text}")

open(f"{W}/captions.ass", "w").write(HEADER + "\n".join(lines) + "\n")

# EDGE: caption text -> width/layout check. Running this as a separate step means
# remembering it after every wording change; forgetting once shipped a line 216px
# past the safe area. Generating and validating are now the same act, so an
# overflowing .ass cannot exist on disk without the build failing.
import sys as _sys
_SKILL = os.environ.get("YIIBU_SKILL_DIR") or next(
    (d for d in (os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * n))
                 for n in range(4))
     if os.path.exists(os.path.join(d, "house_style.json"))),
    os.path.expanduser("~/.claude/skills/yiibu"))
_sys.path[:0] = [_SKILL, os.path.join(_SKILL, "modules")]
import gates as _gates                                          # noqa: E402
_fails, _det = _gates.gate_captions(W)
if _fails:
    raise SystemExit("caption layout rejected:\n  - " + "\n  - ".join(_fails))
print(f"  layout ok: {_det['overflow']} overflow, "
      f"{len(_det['undeclared_styles'])} undeclared")
json.dump(PILLS, open(f"{W}/pills.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(lines)} caption events, {len(PILLS)} pills, video total {TOTAL:.2f}s")
