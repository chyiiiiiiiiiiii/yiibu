# EXAMPLE — the locked running-vlog build (上海晨跑5K). Paths refer to the
# original machine; read alongside references/running-vlog-template.md.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vp_build.py — 上海晨跑 5K, video-postprod running-vlog-template 版
參考 ~/Desktop/running-2026-08-09/夜跑5K-v6.mp4 的鎖定樣式:
result-first hook、演示斜黑体字幕+金色關鍵字、B-roll 乾淨、hero 收尾。
"""
import os, subprocess, json, sys

# The audio chain below composes buildkit primitives rather than hand-writing the
# graph. Importing it also self-lints THIS file, so a known slow/hang antipattern
# refuses to start instead of stalling twenty minutes in.
SKILL = os.environ.get("YIIBU_SKILL_DIR",
                       os.path.expanduser("~/.claude/skills/video-postprod"))
sys.path[:0] = [SKILL, os.path.join(SKILL, "modules")]
from modules import buildkit as bk    # noqa: E402

P = "~/Downloads/0813_running_shanghai"
W = os.path.join(P, "vp_work"); os.makedirs(W, exist_ok=True)
VF = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,format=yuv420p"

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr[-1500:])

# ── PLAN: (file, in, out, audio_gain, label) ──
SPEECH_GAIN = 1.9   # speech band 量測 -23.4 dB → 目標 ~-18
AMB_GAIN = 1.2
PLAN = [
    ("IMG_3089_end.MOV",      0.00, 1.55, SPEECH_GAIN, "hook 5K均速531"),
    ("IMG_3044_start_2.MOV",  0.00, 1.74, SPEECH_GAIN, "現在早上7點"),
    ("IMG_3077_zoomhook.MOV", 0.50, 3.20, 1.3,         "阿公阿嬤揮刀"),
    ("IMG_3051_warmup.mov",   2.00, 4.00, AMB_GAIN,    "熱身"),
    ("IMG_3052_yii.MOV",      0.70, 2.45, SPEECH_GAIN, "開跑開跑"),
    ("IMG_3053.MOV",          1.00, 3.20, AMB_GAIN,    "小區跑步道"),
    ("IMG_3055.MOV",          2.00, 4.00, AMB_GAIN,    "橋"),
    ("IMG_3056.mov",          0.40, 1.90, AMB_GAIN,    "健走團"),
    ("IMG_3057.MOV",          0.30, 1.80, AMB_GAIN,    "阿伯跑者"),
    ("IMG_3063.mov",          0.00, 1.50, AMB_GAIN,    "狗狗"),
    ("IMG_3061.mov",          0.20, 2.95, SPEECH_GAIN, "5分44秒"),
    ("IMG_3089_end.MOV",      1.70, 63.595, SPEECH_GAIN, "心得 monologue"),
]

segs = []
for i, (f, ss, to, gain, label) in enumerate(PLAN):
    out = os.path.join(W, f"seg{i:02d}.mp4")
    segs.append(out)
    if not os.path.exists(out):
        run(["ffmpeg","-v","error","-ss",str(ss),"-to",str(to),"-i",os.path.join(P,f),
             "-vf",VF,"-af",f"volume={gain},aresample=48000",
             "-c:v","h264_videotoolbox","-b:v","20M","-c:a","aac","-b:a","192k","-ac","2","-y",out])
    print("seg",i,label)

# measured cumulative starts
durs=[]
for s in segs:
    d=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",s],
                            capture_output=True,text=True).stdout.strip())
    durs.append(d)
starts=[]; t=0.0
for d in durs: starts.append(t); t+=d
TOTAL=t
S11=starts[11]                      # monologue timeline start
MONO_OFF=S11-1.70                   # source time -> video time
print("starts:",[round(x,2) for x in starts],"total",round(TOTAL,2))

with open(os.path.join(W,"concat.txt"),"w") as fp:
    for s in segs: fp.write(f"file '{s}'\n")
run(["ffmpeg","-v","error","-f","concat","-safe","0","-i",os.path.join(W,"concat.txt"),
     "-c","copy","-y",os.path.join(W,"base_cat.mp4")])
print("concat ok")

# ── cutaways (video-only) over monologue ──
CUTS = [  # (file, ss, dur, src_time 對應句)
    ("IMG_3073.mov", 1.0, 3.5, 10.1),   # 每棟建築都長一樣
    ("IMG_3070.mov", 0.5, 3.1, 18.3),   # 這邊都電動車
    ("IMG_3059.MOV", 0.5, 3.1, 32.9),   # 外送小哥
    ("IMG_3058.mov", 0.4, 3.0, 41.8),   # 抓準時機過馬路
]
cutfiles=[]
for i,(f,ss,dur,src) in enumerate(CUTS):
    out=os.path.join(W,f"cut{i}.mp4"); cutfiles.append(out)
    if not os.path.exists(out):
        run(["ffmpeg","-v","error","-ss",str(ss),"-t",str(dur),"-i",os.path.join(P,f),
             "-vf",VF,"-an","-c:v","h264_videotoolbox","-b:v","20M","-y",out])
print("cutaways ok")

# ── subtitles (vp house style) ──
GOLD_ASS="&H5AD6F5&"; WHITE="&HFFFFFF&"
def g(txt):  # **word** -> gold span (vp: keyword 90px vs body 82px)
    return txt.replace("**","\x00").replace("\x00","{\\fs90\\1c"+GOLD_ASS+"}",1).replace("\x00","{\\fs82\\1c"+WHITE+"}",1) if "**" in txt else txt
def fmt(t):
    h=int(t//3600); m=int(t%3600//60); s=t%60
    return f"{h}:{m:02d}:{s:05.2f}"

MONO=[  # (src_start, src_end, text) — 已按 960px 行寬在語意斷點切行
 (2.00,3.10,"今天在這邊是"),
 (3.10,4.20,"**河濱體育公園**"),
 (4.90,6.90,"這一區就是叫**河岸新村**"),
 (7.00,8.60,"這一區 所以他們有"),
 (8.60,9.90,"從一數到十幾"),
 (10.10,11.20,"每棟建築都長一樣"),
 (11.30,13.10,"大概就是大地色"),
 (13.10,14.90,"棕色 橘色 米色"),
 (15.20,16.60,"所以看起來就很習慣"),
 (16.60,17.40,"很一致"),
 (18.00,18.90,"它優點就是"),
 (18.90,20.20,"因為這邊都**電動車**"),
 (20.30,22.30,"所以機車 汽車"),
 (22.60,23.60,"都沒有聲音"),
 (24.00,24.80,"也沒有什麼污染"),
 (24.80,26.50,"所以你感覺空氣品質"),
 (26.50,28.00,"**AQI 就是十幾二十**"),
 (28.30,29.50,"所以就是非常的好"),
 (29.50,31.70,"缺點呢 也是因為電動車"),
 (31.70,32.70,"所以非常的安靜"),
 (32.70,35.20,"再加上他們很多**外送小哥**"),
 (35.20,36.20,"就會鑽小路"),
 (36.20,37.50,"他們可能會超車"),
 (37.50,38.60,"所以你就會"),
 (38.60,39.50,"一直聽到**叭叭聲**"),
 (39.80,41.40,"然後這邊就是平等的"),
 (41.60,42.60,"大家都需要"),
 (42.60,44.20,"抓準時機的去超車"),
 (44.20,45.50,"或者是你過馬路"),
 (45.70,46.60,"這一點就是"),
 (46.60,47.90,"要特別注意的部分"),
 (48.50,49.70,"然後他們每一區"),
 (49.80,50.90,"幾乎都有人行道"),
 (50.90,52.40,"所以也算是**跑者友善**"),
 (52.90,55.30,"總而言之 整體來說"),
 (55.30,56.20,"**7 分**"),
 (56.20,58.50,"下次我想到**外灘沿岸**"),
 (58.70,59.50,"跑一趟"),
 (59.70,61.50,"看看那邊 效果如何"),
]
HERO_SRC=(62.30, 63.595, "Let's go!")

# ── width gate: 行寬超過 960px 視為 FAIL ──
from PIL import ImageFont
_f82 = ImageFont.truetype(os.path.expanduser("~/Library/Fonts/演示斜黑体.otf"), 82)
_f90 = ImageFont.truetype("~/Library/Fonts/演示斜黑体.otf", 90)
def _linewidth(txt):
    w, gold, i = 0.0, False, 0
    parts = txt.split("**")
    for pi, part in enumerate(parts):
        f = _f90 if pi % 2 == 1 else _f82
        w += f.getlength(part)
    return w
_ALL = [t for _,_,t in MONO] + ["5K 均速 **5:31**","現在早上時間 **7 點**","阿公阿嬤的晨練 是**揮刀**","開跑 開跑","第 1K **5 分 44 秒**"]
_bad = [(t, round(_linewidth(t))) for t in _ALL if _linewidth(t) > 960]
if _bad:
    raise SystemExit(f"WIDTH GATE FAIL: {_bad}")
print("width gate ok, max =", max(round(_linewidth(t)) for t in _ALL))


lines=[]
def add(t0,t1,text,style="Speech",pos="{\\an2\\pos(540,1500)}"):
    lines.append(f"Dialogue: 0,{fmt(t0)},{fmt(t1)},{style},,0,0,0,,{pos}{g(text)}")

add(0.05, starts[1]-0.05, "5K 均速 **5:31**")
add(starts[1]+0.05, starts[2]-0.05, "現在早上時間 **7 點**")
add(starts[2]+0.10, starts[3]-0.05, "阿公阿嬤的晨練 是**揮刀**")
add(starts[4]+0.15, starts[5]-0.05, "開跑 開跑")
add(starts[10]+0.05, starts[11]-0.05, "第 1K **5 分 44 秒**")
for s0,s1,txt in MONO:
    add(s0+MONO_OFF, s1+MONO_OFF, txt)
add(HERO_SRC[0]+MONO_OFF, TOTAL-0.05, HERO_SRC[2], style="Hero", pos="{\\an2\\pos(540,1330)}")

ass = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Speech,演示斜黑体,82,&H00FFFFFF,&H00000000,&H60000000,-1,1,0,5,2,60,60,340,1
Style: Hero,演示斜黑体,132,&H00FFFFFF,&H00000000,&H60000000,-1,1,0,6,2,60,60,340,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lines) + "\n"
open(os.path.join(W,"subs.ass"),"w").write(ass)
print(len(lines),"subtitle lines")

# ── final compose: cutaway overlays + subtitles ──
fc=[]
prev="0:v"
for i,(f,ss,dur,src) in enumerate(CUTS):
    t0=src+MONO_OFF
    fc.append(f"[{i+1}:v]setpts=PTS+{t0:.3f}/TB[c{i}]")
    fc.append(f"[{prev}][c{i}]overlay=0:0:eof_action=pass:enable='between(t,{t0:.3f},{t0+dur:.3f})'[v{i}]")
    prev=f"v{i}"
fc.append(f"[{prev}]subtitles=subs.ass[vout]")

MUSIC_START=33.1-starts[2]   # drop 砸在揮刀 B-roll 開場
fade=TOTAL-0.5
common_v=["-map","[vout]","-c:v","h264_videotoolbox","-b:v","14M","-r","30","-pix_fmt","yuv420p"]
common_a=["-c:a","aac","-b:a","192k","-ar","48000","-ac","2"]

# music version
#
# NOT sidechaincompress, and NOT inline loudnorm. This script shipped both and
# both are documented defects (delivery-traps #4 and #4b):
#
#   * sidechaincompress + amix silently stopped passing the bed about 1.6s
#     before the end, while the bed file itself measured a healthy -23.6 dBFS.
#     The music simply vanished under the last shot and no gate noticed.
#   * loudnorm as an inline FILTER eats ~3s off the tail and returns NaN on
#     silence. It is a measurement tool: run it with print_format=json, then
#     apply the result as a constant volume.
#
# The replacement is a precomputed numpy envelope multiplied into the bed —
# buildkit.duck_mix — plus a measured constant gain through afx_chain, whose
# limiter ceiling is what actually prevents clipping.
gain_db, _meas = bk.measure_gain_db(os.path.join(W, "base_cat.mp4"))
bed_f32, _n = bk.duck_mix(os.path.join(W, "base_cat.mp4"),
                          os.path.join(P, "music_src.mp3"),
                          W, depth_db=11.0)
af_m = (f"[0:a]aresample=48000,{bk.afx_chain(gain_db)},"
        f"afade=t=out:st={fade:.2f}:d=0.5[aout]")
run(["ffmpeg","-v","error","-i",os.path.join(W,"base_cat.mp4"),
     *sum([["-i",c] for c in cutfiles],[]),
     "-ss",str(MUSIC_START),"-i",os.path.join(P,"music_src.mp3"),
     "-filter_complex",";".join(fc)+";"+af_m,
     *common_v,"-map","[aout]",*common_a,"-y",os.path.join(W,"vp_music.mp4")])
print("music version rendered")

# no-music version — same measured gain, no bed. Gate BOTH: a silent ending and
# a dead music bed fail in only one of the two versions.
af_n = (f"[0:a]aresample=48000,{bk.afx_chain(gain_db)},"
        f"afade=t=out:st={fade:.2f}:d=0.5[aout]")
run(["ffmpeg","-v","error","-i",os.path.join(W,"base_cat.mp4"),
     *sum([["-i",c] for c in cutfiles],[]),
     "-filter_complex",";".join(fc)+";"+af_n,
     *common_v,"-map","[aout]",*common_a,"-y",os.path.join(W,"vp_nomusic.mp4")])
print("nomusic version rendered")
json.dump({"starts":starts,"total":TOTAL,"mono_off":MONO_OFF,"music_start":MUSIC_START},
          open(os.path.join(W,"layout.json"),"w"))
print("DONE", round(TOTAL,2))
