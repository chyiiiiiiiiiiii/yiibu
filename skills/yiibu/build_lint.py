#!/usr/bin/env python3
"""Lint a build script for the antipatterns that cost the 2026-08-17 build
~50 minutes. Run BEFORE executing any hand-written build script:

    python3 build_lint.py WORK_DIR/my_build.py     # exit 1 on any hit

Every rule here burned real wall-clock time while being ALREADY DOCUMENTED —
prose does not stop an agent writing the same graph again, a linter does.
gates.py catches broken output; this catches slow/hanging CONSTRUCTION, which
gates never see because the file that eventually appears is fine.
"""
import re
import sys

RULES = [
    (r"libx264",
     "libx264 on 1080x1920 runs 20+ min where h264_videotoolbox takes seconds "
     "(running-vlog-template §9). Use buildkit.VENC."),
    # `-loop 1` is fine when the SAME command bounds it (-frames:v, -t) and bakes
    # to an intermediate (qtrle) — that IS the documented fix. The trap is a
    # bare loop feeding a composite graph directly.
    # `-t` counts as a bound too: it caps the OUTPUT duration, so ffmpeg exits on
    # its own no matter how long the looped input would run. Leaving it out of
    # this list flagged both a real build and this repo's own reference example
    # (references/examples/event-vlog/render.py), whose comment explains exactly
    # why the loop there is safe. A linter that cries wolf on the shipped
    # examples is a linter people learn to ignore.
    (r"-loop[\"',\s]*1(?![^\n]*(?:-frames:v|frames.v|qtrle|[\"']-t[\"']))[^\n]*\n(?![^\n]*(?:-frames:v|qtrle|[\"']-t[\"']))",
     "a `-loop 1` image feeding a filter graph never EOFs — ffmpeg writes the "
     "full output and then hangs forever (delivery-traps #6). Bake the image "
     "to a finite qtrle clip first, or use buildkit.overlay_pills."),
    (r"crop=w='[^']*t[^']*'",
     "crop's w/h are evaluated ONCE at filter-config time — animating them "
     "fails outright. zoompan is the filter that animates scale; use "
     "buildkit.punch_in."),
    (r"sidechaincompress",
     "sidechaincompress+amix silently dropped the music bed before the end of "
     "the video (delivery-traps #4b). Use bgm.duck_gain / buildkit.duck_mix."),
    (r"afade=t=out[^,\"']*\[?mus",
     "afade=t=out on a trimmed+retimed bed hard-cuts to digital zero instead "
     "of ramping. Let the bed play to the end (delivery-traps #4b)."),
    (r"loudnorm(?!.*print_format)",
     "loudnorm as an inline filter eats ~3s off the tail and NaNs on silence "
     "(delivery-traps #4). Measure with print_format=json, apply constant "
     "volume — buildkit.measure_gain_db."),
    (r"overlay[^\n]*\[v\d+\];.*overlay[^\n]*\[v\d+\];.*overlay",
     "3+ chained overlays of delayed-PTS streams in ONE graph: framesync "
     "composited only the first (2026-08-17). One sequential pass per "
     "overlay — buildkit.overlay_pills."),
]


TRIPLE_DQ = '"' * 3
TRIPLE_SQ = "'" * 3


def _strip_comments(src):
    """Drop # comments and triple-quoted strings, so documentation ABOUT an
    antipattern does not read as USE of it (buildkit's own docstrings name
    every trap they encode)."""
    src = re.sub("(?s)" + TRIPLE_DQ + ".*?" + TRIPLE_DQ, "", src)
    src = re.sub("(?s)" + TRIPLE_SQ + ".*?" + TRIPLE_SQ, "", src)
    return re.sub(r"(?m)#.*$", "", src)


def lint(path):
    src = _strip_comments(open(path, encoding="utf-8").read())
    hits = []
    for pat, msg in RULES:
        for m in re.finditer(pat, src, re.DOTALL):
            line = src[: m.start()].count("\n") + 1
            hits.append((line, pat, msg))
            break                       # one report per rule is enough
    return hits


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 2)
    hits = lint(sys.argv[1])
    if not hits:
        print(f"✅ {sys.argv[1]}: no known slow/hang antipatterns")
        sys.exit(0)
    print(f"❌ {sys.argv[1]}: {len(hits)} antipattern(s) that have each burned "
          f"real time before:\n")
    for line, pat, msg in hits:
        print(f"  line {line}  [{pat}]\n    {msg}\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
