#!/usr/bin/env python3
"""Video post-production pipeline for tech digest shorts.

Usage:
    python3 postprod.py INPUT_VIDEO [options]

Options:
    --script PATH     Tech-digest script JSON (for B-roll + keywords)
    --output PATH     Output video path (default: input_final.mp4)
    --step STEP       Run only one step: silence|transcribe|subtitle|broll|bgm|compose
    --cuts START-END  Manual cut ranges (repeatable), e.g. --cuts 12.5-15.3
    --bgm PATH        Manual BGM audio file (skips mood analysis)
    --no-bgm          Skip BGM step entirely
    --work-dir PATH   Working directory (default: /tmp/yiibu/<timestamp>)
"""
import argparse
import json
import os
import subprocess
import sys
import time

# Add skill directory to path
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)

from modules.silence_cut import run_silence_cut
from modules.transcribe import run_transcribe
from modules.types import load_words
from modules.positioning import analyze_video_for_positioning
from modules.subtitles import generate_ass_file
from modules.broll import (
    plan_broll_segments, collect_broll, auto_generate_broll_items,
    align_broll_to_transcript, sequence_overlapping_segments,
    clamp_broll_to_topic_boundaries,
    parse_digest_broll_urls,
)
from modules.transcript_analyzer import (
    analyze_transcript_for_visuals,
    merge_with_script_items,
    apply_coverage_targets,
)
from modules.bgm import run_bgm
from modules.compose import compose_video, get_video_duration
from modules.pipeline_state import (
    file_sha256,
    load_json_cache,
    rebind_transcription_words,
    record_transcription_domain,
    write_json_cache,
)
from config import WORK_DIR_PREFIX, SFX_TRANSITION_FILE


def parse_args():
    parser = argparse.ArgumentParser(description="Video post-production pipeline")
    parser.add_argument("input", help="Input video file path")
    parser.add_argument("--script", help="Tech-digest script JSON path")
    parser.add_argument("--output", help="Output video path")
    parser.add_argument(
        "--step",
        choices=["silence", "transcribe", "subtitle", "broll", "bgm", "compose", "verify"],
        help="Run only a specific step",
    )
    parser.add_argument(
        "--cuts", action="append",
        help="Manual cut range: START-END (seconds), repeatable",
    )
    parser.add_argument("--bgm", help="Manual BGM audio file (skips mood analysis)")
    parser.add_argument("--music", help=(
        "What the user said about music — a track name, an artist and title, a "
        "vibe word. Resolved through resolve_music.py's ladder, which always "
        "terminates: explicit path, PROJECT_DIR/music/, a library filename "
        "match, then a clearly-labelled stand-in. Never stalls the build."))
    parser.add_argument("--sfx", help="Transition SFX file (played at topic switches)")
    parser.add_argument("--no-bgm", action="store_true", help="Skip BGM step entirely")
    parser.add_argument("--no-broll", action="store_true", help="Skip B-roll step entirely")
    parser.add_argument("--no-sfx", action="store_true", help="Disable whoosh transition SFX")
    parser.add_argument("--top-title", help="Rounded top-title banner text (e.g. hook question)")
    parser.add_argument("--top-title-pct", type=float, default=0.23,
                        help="Top-title vertical position as fraction of height (default 0.23)")
    parser.add_argument("--top-title-mode", choices=["persistent", "start"], default="persistent",
                        help="Show title whole video (persistent) or only the opening (start)")
    parser.add_argument("--top-title-start-dur", type=float, default=7.5,
                        help="Seconds the title shows in 'start' mode (default 7.5)")
    parser.add_argument("--digest", help="Tech digest markdown path (for B-roll URLs)")
    parser.add_argument("--title", help="Title card text (overlaid in first 2.5s)")
    parser.add_argument("--card-subtitle", help="Title card subtitle text")
    parser.add_argument("--cta-image", help="CTA overlay image (e.g. Substack screenshot)")
    parser.add_argument("--no-english", dest="english", action="store_false",
                        help="Disable the English line under each caption (default: bilingual on)")
    parser.set_defaults(english=None)   # None → use config.SUBTITLE_BILINGUAL default
    parser.add_argument("--work-dir", help="Working directory")
    return parser.parse_args()


def load_script(script_path):
    """Load tech-digest script JSON."""
    if not script_path or not os.path.exists(script_path):
        return {"items": [], "tech_keywords": []}
    with open(script_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ask(prompt, default):
    """input() that survives non-interactive runs (agents, CI, launchd).

    A pipeline that crashes on EOFError twenty minutes in is worse than one
    that states its assumption and keeps going.
    """
    try:
        if not sys.stdin.isatty():
            raise EOFError
        return input(prompt).strip().lower() or default
    except EOFError:
        print(f"{prompt}{default}   (non-interactive: assuming '{default}')")
        return default


def parse_manual_cuts(cuts_args):
    """Parse --cuts arguments into list of (start, end) tuples."""
    if not cuts_args:
        return None
    result = []
    for c in cuts_args:
        parts = c.split("-", 1)
        result.append((float(parts[0]), float(parts[1])))
    return result


def analysis_cache_inputs(
    input_video,
    words_path,
    script_path=None,
    digest_path=None,
    timeline_path=None,
):
    config_paths = [
        os.path.join(SKILL_DIR, "config.py"),
        os.path.join(SKILL_DIR, "modules", "broll.py"),
        os.path.join(SKILL_DIR, "modules", "transcript_analyzer.py"),
        os.path.join(SKILL_DIR, "keyword_bank.json"),
        os.path.join(SKILL_DIR, "keyword_bank.local.json"),
    ]
    return {
        "source": {"identifier": f"file:{os.path.abspath(input_video)}",
                   "sha256": file_sha256(input_video)},
        "words": words_path if os.path.exists(words_path) else None,
        "script": os.path.abspath(script_path) if script_path else None,
        "digest": os.path.abspath(digest_path) if digest_path else None,
        "timeline": timeline_path if timeline_path and os.path.exists(timeline_path) else None,
        "config": [path for path in config_paths if os.path.exists(path)],
    }


def main():
    args = parse_args()

    # Use one resolved Gemini key for all SDK steps (Veo, image, LLM) — see
    # modules/llm.resolve_gemini_key for the shell-rc-first order and YIIBU_GEMINI_KEY.
    # Set ONLY GEMINI_API_KEY (setting GOOGLE_API_KEY too makes google-genai warn
    # and can abort Veo generation).
    from modules.llm import resolve_gemini_key
    _gkey = resolve_gemini_key()
    if _gkey:
        os.environ["GEMINI_API_KEY"] = _gkey
        os.environ.pop("GOOGLE_API_KEY", None)

    # Install skill-bundled fonts (so subtitles/title render even without an external copy)
    from modules.title import ensure_fonts
    ensure_fonts()

    input_video = os.path.abspath(args.input)

    if not os.path.exists(input_video):
        print(f"Error: Input file not found: {input_video}")
        sys.exit(1)

    work_dir = args.work_dir or os.path.join(
        WORK_DIR_PREFIX, str(int(time.time()))
    )
    os.makedirs(work_dir, exist_ok=True)

    base, ext = os.path.splitext(input_video)
    output_path = args.output or f"{base}_final.mp4"
    script = load_script(args.script)
    manual_cuts = parse_manual_cuts(args.cuts)
    manual_bgm = os.path.abspath(args.bgm) if args.bgm else None
    sfx_path = None if args.no_sfx else (
        os.path.abspath(args.sfx) if args.sfx else (
            SFX_TRANSITION_FILE if SFX_TRANSITION_FILE and os.path.exists(SFX_TRANSITION_FILE) else None
        )
    )
    no_bgm = args.no_bgm
    no_broll = args.no_broll
    step = args.step
    cta_image = os.path.abspath(args.cta_image) if args.cta_image else None

    digest_path = os.path.abspath(args.digest) if args.digest else None

    print(f"Input:    {input_video}")
    print(f"Work dir: {work_dir}")
    print(f"Output:   {output_path}")
    if args.script:
        print(f"Script:   {args.script} ({len(script.get('items', []))} items)")
    if digest_path:
        print(f"Digest:   {digest_path}")
    print()

    # Paths for intermediate files
    trimmed_path = os.path.join(work_dir, "trimmed.mp4")
    words_path = os.path.join(work_dir, "words.json")
    subtitle_path = os.path.join(work_dir, "subtitles.ass")
    broll_plan_path = os.path.join(work_dir, "broll_plan.json")
    bgm_mixed_path = os.path.join(work_dir, "bgm_mixed.wav")
    timeline_path = os.path.join(work_dir, "timeline.json")

    # ── Step 1: Silence removal ──────────────────────────────
    if step is None or step == "silence":
        print("[Step 1/7] Removing silence and mistakes...")
        trimmed_path = run_silence_cut(input_video, work_dir, manual_cuts)
        print(f"  Done: {trimmed_path}\n")
        if step == "silence":
            return

    # ── Step 2: Transcription ────────────────────────────────
    if step is None or step == "transcribe":
        print("[Step 2/7] Transcribing audio...")
        try:
            words_path = run_transcribe(trimmed_path, work_dir)
        except ImportError:
            # The promise is "each missing dependency skips its feature".
            print("  faster-whisper not installed — skipping transcription and "
                  "speech captions.\n"
                  "  To enable: create the ASR venv (SETUP.md Tier 1).")
            words_path = os.path.join(work_dir, "words.json")  # stays absent
            if step == "transcribe":
                return
        else:
            record_transcription_domain(work_dir, trimmed_path, words_path)
            print(f"\n  IMPORTANT: Review the transcript above.")
            print(f"  Edit {words_path} if corrections needed, and declare each one")
            print("  in corrections.json with its evidence — an undeclared edit is refused.")
            if step is None:
                resp = ask("  Continue? (y/n): ", "y")
                if resp != "y":
                    print("  Pipeline paused. Re-run with --step subtitle after editing.")
                    return
            if step == "transcribe":
                return

    if os.path.exists(words_path) and step in (None, "subtitle", "broll"):
        try:
            rebind_transcription_words(work_dir, words_path)
        except ValueError as e:
            print(f"  Error: cannot bind transcript to current media: {e}")
            sys.exit(1)

    # ── Load persistent keyword bank ──────────────────────────
    # keyword_bank.json ships with the repo (generic tech terms);
    # keyword_bank.local.json is gitignored — personal brand/channel names
    # live there so they highlight for you without shipping to strangers.
    bank_keywords = []
    for bank_file in ("keyword_bank.json", "keyword_bank.local.json"):
        p = os.path.join(SKILL_DIR, bank_file)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                bank = json.load(f)
            for cat in ("brand", "tech", "concept"):
                bank_keywords.extend(bank.get(cat, []))

    # ── Auto-generate B-roll items from transcript if no script items ──
    # Only needed for subtitle + broll steps; compose/bgm read from saved files
    items = script.get("items", [])
    keywords = script.get("tech_keywords", [])
    auto_script_path = os.path.join(work_dir, "auto_script.json")
    visual_moments_path = os.path.join(work_dir, "visual_moments.json")
    cache_inputs = None

    def _cache_inputs():
        nonlocal cache_inputs
        if cache_inputs is None:
            cache_inputs = analysis_cache_inputs(
                input_video, words_path, args.script, digest_path, timeline_path,
            )
        return cache_inputs

    if not items and os.path.exists(words_path) and step in (None, "subtitle", "broll"):
        auto_inputs = {**_cache_inputs(), "stage": "auto_script-v1"}
        auto_result = load_json_cache(auto_script_path, auto_inputs)
        if auto_result is not None:
            print("  Loading cached auto-generated B-roll items...")
            items = auto_result.get("items", [])
            keywords = keywords or auto_result.get("tech_keywords", [])
            print(f"  Loaded {len(items)} items from {auto_script_path}")
        else:
            print("  No script items — auto-generating B-roll from transcript...")
            auto_result = auto_generate_broll_items(words_path)
            items = auto_result.get("items", [])
            keywords = keywords or auto_result.get("tech_keywords", [])
            write_json_cache(auto_script_path, auto_result, auto_inputs)
            print(f"  Auto-generated {len(items)} items → {auto_script_path}")

    # ── Parse digest B-roll URLs if provided ────────────────────
    digest_broll_items = []
    digest_mustread_urls = {}
    if digest_path:
        digest_broll_items, digest_mustread_urls = parse_digest_broll_urls(digest_path)

    # ── Step 2.5: Transcript visual analysis ──────────────────
    # LLM-driven extraction of visual moments to boost B-roll coverage
    if os.path.exists(words_path) and step in (None, "broll"):
        visual_inputs = {
            **_cache_inputs(),
            "stage": "visual_moments-v1",
            "items": items,
        }
        visual_segments = load_json_cache(visual_moments_path, visual_inputs)
        if visual_segments is not None:
            print("  Loading cached visual moments...")
            print(f"  Loaded {len(visual_segments)} visual segments from cache")
        else:
            print("[Step 2.5/6] Analyzing transcript for visual moments...")
            video_for_duration = trimmed_path if os.path.exists(trimmed_path) else input_video
            total_dur = get_video_duration(video_for_duration)

            visual_moments = analyze_transcript_for_visuals(
                words_path, total_dur,
                digest_broll_items=digest_broll_items or None,
                digest_mustread_urls=digest_mustread_urls or None,
            )
            if visual_moments:
                visual_segments = merge_with_script_items(visual_moments, items)
                visual_segments = apply_coverage_targets(visual_segments, total_dur)
                print(f"  {len(visual_segments)} segments after merge + coverage targeting")
            else:
                visual_segments = []

            write_json_cache(visual_moments_path, visual_segments, visual_inputs)
            print(f"  Cached → {visual_moments_path}\n")

    # ── Merge keyword bank into keywords ──────────────────────
    if bank_keywords:
        existing = {kw.lower() for kw in keywords}
        added = [kw for kw in bank_keywords if kw.lower() not in existing]
        if added:
            keywords.extend(added)
            print(f"  Keyword bank: +{len(added)} terms → {len(keywords)} total keywords")

    # ── Step 3: Subtitle generation ──────────────────────────
    if (step is None and not os.path.exists(words_path)):
        print("[Step 3/7] No words.json (transcription was skipped) — "
              "skipping subtitles.")
    elif step is None or step == "subtitle":
        print("[Step 3/7] Generating subtitles...")
        if not os.path.exists(words_path):
            print(f"  Error: no words.json in {work_dir} — run the transcribe "
                  f"step first (needs the faster-whisper venv, SETUP.md Tier 1).")
            sys.exit(1)
        words = load_words(words_path)

        print("  Analyzing video for face position...")
        sub_pos = analyze_video_for_positioning(trimmed_path)
        align_label = "bottom" if sub_pos['alignment'] == 2 else "top"
        print(f"  Subtitle position: y_ratio={sub_pos['y_ratio']:.2f}, "
              f"alignment={sub_pos['alignment']} ({align_label})")
        resp = ask(f"  Place subtitles at {align_label}? (y/n/t=top/b=bottom): ", "y")
        if resp == "n" or resp == "t":
            sub_pos = {"y_ratio": 0.10, "alignment": 8}
            print("  → Overridden to top")
        elif resp == "b":
            sub_pos = {"y_ratio": 0.88, "alignment": 2}
            print("  → Overridden to bottom")

        # Title card: CLI args take priority, then script JSON fields
        title_text = args.title or script.get("title")
        card_sub = getattr(args, "card_subtitle", None) or script.get("subtitle")

        generate_ass_file(
            words=words,
            keywords=keywords,
            subtitle_pos=sub_pos,
            output_path=subtitle_path,
            title=title_text,
            card_subtitle=card_sub,
            bilingual=args.english,   # None → config.SUBTITLE_BILINGUAL (default on)
        )
        print(f"  Done: {subtitle_path}\n")
        if step == "subtitle":
            return

    # ── Step 4: B-roll collection ────────────────────────────
    if step is None or step == "broll":
        if no_broll and step != "broll":
            print("[Step 4/7] B-roll skipped (--no-broll)\n")
        else:
            print("[Step 4/7] Collecting B-roll assets...")

            # Use visual_segments from Step 2.5 if available (already merged + coverage-targeted)
            if os.path.exists(visual_moments_path):
                with open(visual_moments_path, "r", encoding="utf-8") as f:
                    broll_segments = json.load(f)
                print(f"  Using {len(broll_segments)} segments from visual analysis")
            else:
                broll_segments = plan_broll_segments(items)

            # Align B-roll to actual keyword timestamps from transcript
            if os.path.exists(words_path):
                words_for_align = load_words(words_path)
                broll_segments = align_broll_to_transcript(broll_segments, words_for_align)
                broll_segments = sequence_overlapping_segments(broll_segments)
                broll_segments = clamp_broll_to_topic_boundaries(broll_segments, words_for_align)
                print(f"  Aligned {len(broll_segments)} segments to transcript keywords")

            broll_segments = collect_broll(broll_segments, work_dir)

            with open(broll_plan_path, "w", encoding="utf-8") as f:
                json.dump(broll_segments, f, ensure_ascii=False, indent=2)

            acquired = sum(1 for s in broll_segments if s.get("asset_path"))
            print(f"  Collected {acquired}/{len(broll_segments)} B-roll assets\n")
        if step == "broll":
            return

    # ── Step 5: BGM ──────────────────────────────────────────
    if step is None or step == "bgm":
        if no_bgm and step != "bgm":
            print("[Step 5/7] BGM skipped (--no-bgm)\n")
        else:
            print("[Step 5/7] Adding background music...")
            video_for_bgm = trimmed_path if os.path.exists(trimmed_path) else input_video
            # Resolve script path for SFX transition detection
            script_json_path = (
                os.path.abspath(args.script) if args.script
                else auto_script_path if os.path.exists(auto_script_path)
                else None
            )
            bgm_mixed_path = run_bgm(
                trimmed_video=video_for_bgm,
                work_dir=work_dir,
                words_path=words_path if os.path.exists(words_path) else None,
                manual_bgm=manual_bgm,
                sfx_path=sfx_path,
                broll_plan_path=broll_plan_path,
                script_path=script_json_path,
                music_request=args.music,
                project_dir=os.path.dirname(os.path.abspath(output_path)),
            )
            print()
        if step == "bgm":
            return

    # ── Step 6: Composition ──────────────────────────────────
    if step is None or step == "compose":
        print("[Step 6/7] Composing final video...")

        if os.path.exists(broll_plan_path):
            with open(broll_plan_path, "r", encoding="utf-8") as f:
                broll_segments = json.load(f)
        else:
            broll_segments = []

        # Use BGM audio if available
        # Prefer SFX-mixed audio if available, fall back to plain BGM
        bgm_sfx_path = os.path.join(work_dir, "bgm_mixed_sfx.wav")
        if os.path.exists(bgm_sfx_path):
            bgm_audio = bgm_sfx_path
        elif os.path.exists(bgm_mixed_path):
            bgm_audio = bgm_mixed_path
        else:
            bgm_audio = None

        # Resolve CTA image: CLI arg > config default
        from config import CTA_IMAGE_PATH
        effective_cta = cta_image or CTA_IMAGE_PATH
        if effective_cta and not os.path.exists(effective_cta):
            print(f"  CTA image not found: {effective_cta}, skipping")
            effective_cta = None

        compose_video(
            trimmed_video=trimmed_path,
            subtitle_path=subtitle_path,
            broll_segments=broll_segments,
            output_path=output_path,
            bgm_audio=bgm_audio,
            cta_image=effective_cta,
            words_path=words_path if os.path.exists(words_path) else None,
        )

        # Rounded top-title banner (persistent or opening-only)
        if args.top_title:
            from modules.title import overlay_title
            titled = os.path.join(work_dir, "titled_output.mp4")
            overlay_title(
                output_path, titled, args.top_title, work_dir,
                pct=args.top_title_pct, mode=args.top_title_mode,
                start_dur=args.top_title_start_dur,
            )
            os.replace(titled, output_path)
            print(f"  Top title added ({args.top_title_mode}, {int(args.top_title_pct * 100)}%)")

        duration = get_video_duration(output_path)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)

        print(f"\n{'=' * 50}")
        print(f"COMPLETE")
        print(f"{'=' * 50}")
        print(f"Output:   {output_path}")
        print(f"Duration: {duration:.1f}s")
        print(f"Size:     {size_mb:.1f} MB")
        print(f"Format:   1080x1920 H.264 (9:16)")
        print(f"{'=' * 50}")

    # ── Step 7: Verification ──────────────────────────────────
    #
    # Two checkers, and only the second one can stop a hand-over.
    #
    # For a long time this step ran verify.py ALONE — advisory, eight checks,
    # signing off with "PUBLISH READY" — and the nineteen blocking gates were
    # reached only if the agent remembered to type the command from AGENTS.md
    # §6. The automatic step was the one that could not refuse, and the one
    # that could refuse was optional. That is backwards, and no amount of
    # prose fixes it: an agent that reads a green advisory report and hands
    # the file over has not disobeyed anything.
    #
    # gates.py runs as a subprocess on purpose: it owns its exit codes (0
    # shippable / 1 blocked / 2 deferred), its output, and the build_log.jsonl
    # append that makes "the gates never ran" visible afterwards. postprod.py
    # exits with the SAME code, so a caller — a shell script, CI, a hook — sees
    # the gate verdict without knowing gates.py exists.
    if step is None or step == "verify":
        print("\n[Step 7/7] Verification — advisory first, then the gates.")
        from verify import run_all_checks, print_report
        results = run_all_checks(work_dir, output_path, do_fix=True)
        print_report(results)

        if not (output_path and os.path.exists(output_path)):
            print("  No final render to gate yet.")
            return
        rc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "gates.py"),
             output_path, "--work-dir", work_dir]).returncode
        if rc:
            sys.exit(rc)
        if step == "verify":
            return


if __name__ == "__main__":
    main()
