#!/usr/bin/env python3
"""Stage a fair multi-driver benchmark, and collect what it actually cost.

This exists because of what went wrong on 2026-08-22, when three agents were
given one folder and the result could not be quoted:

  * **The folder was not clean.** A previous edit of the same footage had been
    copied in beside the raw clips — four finished videos, its cover art, its
    music, and `project_config.py`, that edit's whole configuration. One agent
    read it and reused the hook concept, the closing caption verbatim and the
    music track. Its output was then ranked second and nearly quoted as
    evidence that a cheaper model gets you there too.
  * **Nothing recorded cost.** `notes.json` already existed and `gates.py`
    already copied it into the build log, but SKILL.md said to write it "if you
    want them kept" — so nobody did, three times, and the one question the
    benchmark was run to answer had no data at all.
  * **The agents shared one input directory** and wrote into it concurrently.

None of that is a model's fault. An agent handed a folder is supposed to read
the folder; the harness is what has to make sure the folder contains only the
question. So:

  stage    copies ONLY footage, per agent, into its own directory, and REFUSES
           anything that looks like a previous build — printing what it refused,
           because a silent skip is how the first leak survived
  finish   stamps wall-clock (measured here) alongside the token counts (only
           the driver knows those — self-reported, and labelled as such)
  report   reads every agent's build_log.jsonl and notes.json into one table

    python3 bench.py stage ~/Desktop/bench-2 --source ~/Desktop/footage \\
                     --agents claude-opus,gemini-flash,terra --music track.mp3
    python3 bench.py finish ~/Desktop/bench-2 --agent terra --model TeraGPT \\
                     --tokens-in 184000 --tokens-out 39000
    python3 bench.py remusic ~/Desktop/bench-2 --music "dina-ayada-problems.mp3"
    python3 bench.py report ~/Desktop/bench-2
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys

FOOTAGE_EXT = {".mov", ".mp4", ".m4v", ".avi", ".heic", ".heif",
               ".jpg", ".jpeg", ".png", ".dng"}

# Names that mean "this is somebody's finished edit", not footage. Matched
# before extension, because every one of these IS a media file — which is
# exactly why an extension allowlist alone let the first leak through.
BUILD_OUTPUT = re.compile(
    r"(^final|^cover|^preview|^endcard|^spine|^rough|-nomusic|_無音樂|"
    r"^visoge-|standin|_sips|^_)", re.I)
# This list is a HEURISTIC and will not be complete — `end_sips.jpg`, a macOS
# `sips` conversion of a photo that was already in the folder, got through the
# first version of it. That is survivable and the reason is the design: the
# refusals are PRINTED, so a leak the pattern misses is still something a person
# sees before the run rather than something a benchmark discovers afterwards.
# Widen it when a new shape shows up; do not rely on it alone.

PROMPT = """\
用 yiibu 把這批素材剪成一支適合 Reels 的直式短片。

素材在：{source}
只使用這個資料夾裡的影片與照片。不要讀取、參考或重用任何其他位置的檔案。

我想要一支大約 45–60 秒、第一次看到的人也願意看完的活動 recap。
請你自行理解素材、挑選鏡頭、安排節奏與敘事；不要編造任何畫面或音訊無法支持的事實。

配樂：{music}

請輸出有音樂版、無音樂版和 cover.jpg，結果放到：
{project}

完成前請依 yiibu 的標準做必要檢查。

最後一步（必做）：回報這次跑掉多少成本。build script 觀測不到 token，只有你知道，
所以請執行：

    python3 {skill}/bench.py finish {dest} --agent {agent} --model "<你實際使用的模型名稱>" --tokens-in <數字> --tokens-out <數字>

查不到 token 數就省略 --tokens-in / --tokens-out，其餘照跑。
--agent 就是上面那個資料夾名稱（它只是槽位），--model 才是實際跑的模型。

然後告訴我：
1. 成片路徑
2. gate 結果
3. 你無法確認、因此沒有寫進影片的內容
"""


def _stamp_path(agent_dir):
    return os.path.join(agent_dir, ".bench_start")


def stage(args):
    dest = os.path.abspath(os.path.expanduser(args.dest))
    src = os.path.abspath(os.path.expanduser(args.source))
    if os.path.isdir(dest) and os.listdir(dest):
        sys.exit(f"{dest} already exists and is not empty — benchmark runs are "
                 f"not re-enterable; pick a fresh directory so the second run "
                 f"cannot inherit the first one's artifacts")
    if not os.path.isdir(src):
        sys.exit(f"no such source directory: {src}")

    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    if not agents:
        sys.exit("--agents is empty")

    keep, refused = [], []
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if name.startswith(".") or os.path.isdir(p):
            refused.append((name, "directory" if os.path.isdir(p) else "dotfile"))
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in FOOTAGE_EXT:
            refused.append((name, f"not footage ({ext or 'no extension'})"))
        elif BUILD_OUTPUT.search(name):
            refused.append((name, "looks like a previous build's output"))
        else:
            keep.append(name)

    # FAIL CLOSED once a previous build is in evidence.
    #
    # The deny-list above is a heuristic and it leaked twice, each time on a
    # folder that plainly contained a finished edit. `封面.jpg` is a cover and
    # `^cover` does not match Chinese; `上海晨跑5K-hardliquor.mp4` is the music
    # half of a pair whose -nomusic half WAS caught. Widening the pattern one
    # word at a time loses to the next folder in the next language.
    #
    # So when the folder shows any sign of a previous project — a build script,
    # a config, a deliverable — the rule flips from "refuse what looks bad" to
    # "keep only what looks like a camera original", and everything dropped is
    # printed. A benchmark that quietly loses one screenshot is recoverable in
    # one command; a benchmark that quietly inherits the answer is not, and that
    # is what happened on 2026-08-22.
    CAMERA = re.compile(r"^(IMG|VID|DSC|MVI|PXL|GH0|GX0|DJI|MAH|MOV|P10|SAM)[_0-9]",
                        re.I)
    build_seen = [n for n, why in refused
                  if "previous build" in why or n.lower().endswith((".py", ".json"))]
    tightened = []
    if build_seen and keep:
        loose = [n for n in keep if not CAMERA.match(n)]
        if loose:
            keep = [n for n in keep if CAMERA.match(n)]
            tightened = loose
            for n in loose:
                refused.append((n, "not a camera original, and this folder "
                                   "contains a previous build"))

    if not keep:
        sys.exit(f"nothing in {src} looks like footage")

    music = os.path.abspath(os.path.expanduser(args.music)) if args.music else None
    if music and not os.path.isfile(music):
        sys.exit(f"no such music file: {music}")

    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    os.makedirs(dest, exist_ok=True)
    for agent in agents:
        adir = os.path.join(dest, agent)
        asrc = os.path.join(adir, "source")
        os.makedirs(asrc, exist_ok=True)
        for name in keep:
            shutil.copy2(os.path.join(src, name), os.path.join(asrc, name))
        if music:
            # PROJECT_DIR/music/ is rung 2 of the resolve_music ladder. The
            # track goes HERE and never into source/: the ladder is meant to
            # find it, and footage folders are meant to hold footage.
            os.makedirs(os.path.join(adir, "music"), exist_ok=True)
            shutil.copy2(music, os.path.join(adir, "music", os.path.basename(music)))
        open(_stamp_path(adir), "w").write(now)
        open(os.path.join(adir, "PROMPT.md"), "w", encoding="utf-8").write(
            PROMPT.format(source=asrc, project=adir, agent=agent, dest=dest,
                          skill=os.path.dirname(os.path.abspath(__file__)),
                          music=(f"用 {os.path.basename(music)}（已放在 "
                                 f"{adir}/music/）" if music
                                 else "沒有指定，請自行決定")))

    json.dump({"staged_at": now, "source": src, "agents": agents,
               "footage_files": len(keep), "music": music,
               "refused": [{"name": n, "why": w} for n, w in refused]},
              open(os.path.join(dest, "bench.json"), "w"),
              ensure_ascii=False, indent=1)

    print(f"staged {len(agents)} agent(s) into {dest}")
    print(f"  {len(keep)} footage file(s) copied to each")
    if music:
        print(f"  music: {os.path.basename(music)} -> <agent>/music/ (ladder rung 2)")
    if tightened:
        print(f"  a previous build is present in {os.path.basename(src)}: "
              f"{', '.join(build_seen[:3])}{'…' if len(build_seen) > 3 else ''}")
        print(f"  -> tightened to camera originals only; {len(tightened)} other "
              f"file(s) dropped. Copy any you actually want back by hand.")
    if refused:
        # Printed, never silent. The 2026-08-22 leak survived because the copy
        # step said nothing about what it had brought along.
        print(f"  NOT copied ({len(refused)}) — these would have been the answer key:")
        for n, w in sorted(refused)[:14]:
            print(f"    · {n}  ({w})")
        if len(refused) > 14:
            print(f"    · … and {len(refused) - 14} more")
    print(f"\n  each agent gets {dest}/<agent>/PROMPT.md — one prompt, paths filled in")


def _work_dir(agent_dir):
    """Where the agent put build_log.jsonl; notes.json has to land beside it."""
    for root, dirs, files in os.walk(agent_dir):
        dirs[:] = [d for d in dirs if d not in ("source", "music", "segments")]
        if "build_log.jsonl" in files:
            return root
    return agent_dir


def _claude_sessions():
    import glob
    return glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))


def _codex_sessions():
    import glob
    return glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/rollout-*.jsonl"))


def _first_user_text(path, limit=40):
    """The opening user turn. That is the PROMPT.md this harness wrote, and it
    is what tells one session apart from another working in the same repo."""
    out = []
    for i, line in enumerate(open(path, encoding="utf-8", errors="ignore")):
        if i > limit:
            break
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or d.get("payload") or {}
        if msg.get("role") == "user" or msg.get("type") == "user_message":
            out.append(json.dumps(msg, ensure_ascii=False))
            if len(out) >= 3:
                break
    return "\n".join(out)


def _read_claude(path):
    tot = {"input_tokens": 0, "output_tokens": 0,
           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    models, turns, ts = set(), 0, []
    for line in open(path, encoding="utf-8", errors="ignore"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("timestamp"):
            ts.append(d["timestamp"])
        msg = d.get("message") or {}
        u = msg.get("usage")
        if not u:
            continue
        turns += 1
        if msg.get("model"):
            models.add(msg["model"])
        for k in tot:
            tot[k] += u.get(k, 0) or 0
    if not turns:
        return None
    return {"driver": "claude-code", "turns": turns,
            "model": sorted(models)[0] if len(models) == 1 else sorted(models),
            "first_ts": min(ts) if ts else None, "last_ts": max(ts) if ts else None,
            **tot}


def _read_codex(path):
    """Codex writes a running total; the LAST one is the session total."""
    last, model, ts = None, None, []
    for line in open(path, encoding="utf-8", errors="ignore"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("timestamp"):
            ts.append(d["timestamp"])
        pay = d.get("payload") or {}
        if d.get("type") == "session_meta":
            model = (pay.get("model") or pay.get("model_provider") or model)
        if pay.get("type") == "token_count":
            t = (pay.get("info") or {}).get("total_token_usage")
            if t:
                last = t
        if pay.get("model"):
            model = pay["model"]
    if not last:
        return None
    return {"driver": "codex", "turns": None, "model": model,
            "input_tokens": last.get("input_tokens", 0),
            "output_tokens": last.get("output_tokens", 0),
            "cache_read_input_tokens": last.get("cached_input_tokens", 0),
            "cache_creation_input_tokens": last.get("cache_write_input_tokens", 0),
            "reasoning_output_tokens": last.get("reasoning_output_tokens", 0),
            "first_ts": min(ts) if ts else None, "last_ts": max(ts) if ts else None}


def _driver_usage(agent_dir, want_session=None):
    """Read what the driver already wrote down, instead of asking anyone to type it.

    The first version of `finish` took --tokens-in/--tokens-out and told the
    agent to look them up. Two things were wrong with that, and both showed up
    within a day. The person running the benchmark does not know the numbers —
    that was the objection that prompted this — and the agent's own guess is not
    much better: one reported "58,000 input / 12,000 output" for a session its
    driver had logged as 7,347,317 input and 29,222 output. Two orders of
    magnitude, offered in good faith, and unfalsifiable once written down.
    Another read its CONTEXT WINDOW (100.3k currently loaded) and reported that
    as consumption, which is a different quantity entirely.

    So nobody types it. Claude Code and Codex both keep a per-session log with
    running token totals; this finds the one whose OPENING USER TURN is the
    PROMPT.md we staged for this agent — the repo is full of sessions working in
    the same directory, and the prompt is what distinguishes them — and reads
    the totals and the real working time out of it.

    A driver with no readable log returns None, and the gap shows up as a gap.
    """
    marker = os.path.join(agent_dir, "source")
    hits = []
    for paths, reader in ((_claude_sessions(), _read_claude),
                          (_codex_sessions(), _read_codex)):
        for p in paths:
            try:
                if marker not in _first_user_text(p):
                    continue
                got = reader(p)
            except (OSError, ValueError):
                continue
            if got:
                got["source"] = f"{got['driver']} session {os.path.basename(p)[:28]}"
                got["path"] = p
                hits.append(got)
    if want_session:
        hits = [h for h in hits if want_session in h["path"]]
    # Did this session actually PRODUCE what is in the folder? A session that
    # ran the slot and was later overwritten by a second driver matches every
    # text test just as well as the one whose work survived — that happened on
    # the first real run, where one slot was driven twice and the readable log
    # belonged to the loser. The deliverables' mtime settles it: work that
    # finished outside a session's own window was not that session's work.
    made = [os.path.getmtime(os.path.join(agent_dir, f))
            for f in os.listdir(agent_dir) if f.endswith((".mp4", ".mov"))]
    if made:
        newest = dt.datetime.fromtimestamp(max(made)).astimezone()
        kept = []
        for h in hits:
            try:
                a = dt.datetime.fromisoformat(h["first_ts"].replace("Z", "+00:00"))
                b = dt.datetime.fromisoformat(h["last_ts"].replace("Z", "+00:00"))
            except (ValueError, AttributeError, KeyError):
                kept.append(h)
                continue
            if a - dt.timedelta(minutes=5) <= newest <= b + dt.timedelta(minutes=5):
                kept.append(h)
            else:
                h["rejected"] = (f"deliverables written {newest:%H:%M}, outside "
                                 f"{a.astimezone():%H:%M}-{b.astimezone():%H:%M}")
        if kept:
            hits = kept
        elif hits:
            return {"none_produced": [f"{h['source']} — {h.get('rejected','')}"
                                      for h in hits]}
    if len(hits) > 1:
        # REFUSE TO GUESS. The first version took the most recent match and wrote
        # it down, and on the very first real use that put one driver's 7.3M
        # tokens into another driver's slot — because a session that merely READ
        # the other slot's directory matched just as well as the one that built
        # the video. Picking the newest is not a tiebreak, it is a coin toss with
        # a number attached, and a wrong number that looks measured is worse than
        # no number at all. That is this whole file's thesis.
        return {"ambiguous": [h["source"] for h in hits]}
    return hits[0] if hits else None


def finish(args):
    dest = os.path.abspath(os.path.expanduser(args.dest))
    adir = os.path.join(dest, args.agent)
    if not os.path.isdir(adir):
        sys.exit(f"no staged directory for agent {args.agent!r} in {dest}")

    started = None
    if os.path.exists(_stamp_path(adir)):
        started = open(_stamp_path(adir)).read().strip()
    ended = dt.datetime.now().astimezone()
    since_staging = None
    if started:
        since_staging = round((ended - dt.datetime.fromisoformat(started)).total_seconds(), 1)

    wd = _work_dir(adir)
    usage = _driver_usage(adir, args.session)

    # `since_staging` is NOT how long the agent worked. The stamp is written when
    # the directories are prepared, and the first round was started nine hours
    # later — which recorded 36528s, a real number measuring nothing anyone
    # asked about. The driver's own log knows when it actually started and
    # stopped, so that is what `worked_s` is, and the staging span keeps its own
    # name instead of impersonating it.
    measured = {"staged_at": started,
                "finished_at": ended.isoformat(timespec="seconds"),
                "since_staging_s": since_staging}
    elapsed = None
    if usage and not usage.get("ambiguous") and usage.get("first_ts") and usage.get("last_ts"):
        try:
            a = dt.datetime.fromisoformat(usage["first_ts"].replace("Z", "+00:00"))
            b = dt.datetime.fromisoformat(usage["last_ts"].replace("Z", "+00:00"))
            elapsed = round((b - a).total_seconds(), 1)
            measured["worked_s"] = elapsed
        except ValueError:
            pass
    if usage and usage.get("none_produced"):
        print(f"  a session ran {args.agent}, but its work is not what is in the "
              f"folder — something else finished later and overwrote it:")
        for c in usage["none_produced"]:
            print(f"    · {c}")
        print(f"  no cost recorded: the driver that produced these files left no "
              f"log this script can read.")
        usage = None
    if usage and usage.get("ambiguous"):
        print(f"  {len(usage['ambiguous'])} sessions match {args.agent}: nothing written "
              f"for cost, because guessing which one is worse than an empty column.")
        for c in usage["ambiguous"]:
            print(f"    · {c}")
        print(f"  re-run with --session <part of the filename> to pick one.")
        usage = None
    if usage:
        usage.pop("path", None)
        measured["usage"] = usage

    # Anything typed on the command line stays a claim, in its own half, however
    # true it is. The distinction is the point: `measured` is what the machine
    # read, `self_reported` is what somebody said.
    claimed = {k: v for k, v in (("model", args.model),
                                 ("tokens_in", args.tokens_in),
                                 ("tokens_out", args.tokens_out)) if v is not None}
    notes = {"agent": args.agent, "measured": measured}
    if claimed:
        notes["self_reported"] = claimed
    json.dump(notes, open(os.path.join(wd, "notes.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"wrote {os.path.join(wd, 'notes.json')}")
    if elapsed is not None:
        print(f"  worked: {elapsed / 60:.1f} min (from the driver's own log)")
    elif since_staging:
        print(f"  no driver log found; {since_staging / 60:.1f} min since staging "
              f"— that is not how long the agent worked")
    if usage:
        print(f"  measured usage from {usage['source']}: "
              f"in {usage['input_tokens']:,} · out {usage['output_tokens']:,} · "
              f"cache-read {usage['cache_read_input_tokens']:,}")
        print(f"  model (read, not typed): {usage['model']}")
        if claimed.get("tokens_in") and abs(claimed["tokens_in"] - usage["input_tokens"]) > \
                0.25 * max(usage["input_tokens"], 1):
            print(f"  NOTE: the typed --tokens-in ({claimed['tokens_in']:,}) is nowhere near "
                  f"the logged {usage['input_tokens']:,}. Keeping both; the read one wins in "
                  f"the report.")
    elif args.tokens_in is None and args.tokens_out is None:
        print("  no token usage available: this driver exposes no session id, "
              "and none was passed on the command line. The build log will show "
              "the gap rather than pretend there is nothing to report.")


def report(args):
    dest = os.path.abspath(os.path.expanduser(args.dest))
    meta_p = os.path.join(dest, "bench.json")
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    # Manifest agents FIRST, then any directory that appeared afterwards. A
    # fourth driver was added to a staged run by copying a folder in, and the
    # report — keyed only on the manifest — left it out without a word. Silent
    # omission is the failure this whole file exists to stop.
    on_disk = sorted(d for d in os.listdir(dest)
                     if os.path.isdir(os.path.join(dest, d)))
    listed = list(meta.get("agents") or [])
    extra = [d for d in on_disk if d not in listed]
    rows = []
    for agent in (listed + extra) or on_disk:
        adir = os.path.join(dest, agent)
        wd = _work_dir(adir)
        row = {"agent": agent}
        logp = os.path.join(wd, "build_log.jsonl")
        if os.path.exists(logp):
            log = [json.loads(l) for l in open(logp) if l.strip()]
            last = log[-1]
            row.update(verdict=last["verdict"], runs=len(log),
                       rejected=sum(1 for r in log if r["verdict"] == "blocked"),
                       duration_s=last.get("video", {}).get("duration_s"),
                       segments=last.get("segments"),
                       sources=last.get("sources_used"),
                       failed=sorted({g for r in log for g in r["gates_failed"]}))
        np = os.path.join(wd, "notes.json")
        if os.path.exists(np):
            n = json.load(open(np))
            m = n.get("measured") or {}
            sr = n.get("self_reported") or {}
            row["elapsed_s"] = m.get("worked_s") or m.get("since_staging_s")
            row["elapsed_measured"] = "worked_s" in m
            u = m.get("usage")
            if u:
                row.update(model=u["model"], tokens_in=u["input_tokens"],
                           tokens_out=u["output_tokens"],
                           cache_read=u["cache_read_input_tokens"], token_src="read")
            else:
                row.update(model=sr.get("model"), tokens_in=sr.get("tokens_in"),
                           tokens_out=sr.get("tokens_out"),
                           token_src="said" if sr.get("tokens_in") else "—")
        rows.append(row)

    if args.json:
        print(json.dumps({"dest": dest, "meta": meta, "rows": rows},
                         ensure_ascii=False, indent=1))
        return

    def cell(v):
        return "—" if v in (None, "") else str(v)

    print(f"\n  benchmark: {dest}")
    if extra:
        print(f"  note: {', '.join(extra)} was not in this run's manifest — added "
              f"after staging, and included here rather than dropped")
    if meta.get("refused"):
        print(f"  staged from {meta.get('source')} · "
              f"{meta.get('footage_files')} footage files · "
              f"{len(meta['refused'])} non-footage item(s) refused")
    hdr = ("agent", "verdict", "runs", "rej", "dur", "segs", "wall",
           "tok in", "tok out", "cache rd", "src")
    w = [17, 10, 5, 4, 7, 5, 8, 11, 10, 15, 5]
    print("  " + "".join(h.ljust(x) for h, x in zip(hdr, w)))
    print("  " + "-" * sum(w))
    for r in rows:
        el = r.get("elapsed_s")
        def num(v):
            return f"{v:,}" if isinstance(v, int) else "—"
        cells = (r["agent"], cell(r.get("verdict")), cell(r.get("runs")),
                 cell(r.get("rejected")), cell(r.get("duration_s")),
                 cell(r.get("segments")),
                 f"{el/60:.1f}m" if (el and r.get("elapsed_measured")) else "—",
                 num(r.get("tokens_in")), num(r.get("tokens_out")),
                 num(r.get("cache_read")), cell(r.get("token_src")))
        print("  " + "".join(c.ljust(x) for c, x in zip(cells, w)))
    print()
    print("  wall = time the driver's own log says it worked; blank when that log "
          "cannot be read\n  (time since staging is recorded in notes.json but is "
          "not the same thing).")
    print("  src=read: token counts read from the driver's own session transcript.  "
          "src=said:\n  typed on the command line, i.e. a claim.")
    for r in rows:
        if r.get("model"):
            print(f"  {r['agent']}: {r['model']}")
    for r in rows:
        if r.get("failed"):
            print(f"  {r['agent']}: rejected at some point by "
                  f"{', '.join(r['failed'])}")


def remusic(args):
    """Swap the track after staging, and keep everything that names it in step.

    Doing this by hand is three edits — the file in each <agent>/music/, the
    line in each PROMPT.md, and the path in bench.json — and the second and
    third get forgotten. That is the shape of the worst bug in this repo's
    history: two nodes changed, no edge connecting them. So it is one command.
    """
    dest = os.path.abspath(os.path.expanduser(args.dest))
    meta_p = os.path.join(dest, "bench.json")
    if not os.path.exists(meta_p):
        sys.exit(f"{dest} was not staged by this script (no bench.json)")
    music = os.path.abspath(os.path.expanduser(args.music))
    if not os.path.isfile(music):
        sys.exit(f"no such music file: {music}")
    meta = json.load(open(meta_p))

    for agent in meta["agents"]:
        adir = os.path.join(dest, agent)
        mdir = os.path.join(adir, "music")
        os.makedirs(mdir, exist_ok=True)
        for old in os.listdir(mdir):
            os.remove(os.path.join(mdir, old))
        shutil.copy2(music, os.path.join(mdir, os.path.basename(music)))
        open(os.path.join(adir, "PROMPT.md"), "w", encoding="utf-8").write(
            PROMPT.format(source=os.path.join(adir, "source"), project=adir,
                          agent=agent, dest=dest,
                          skill=os.path.dirname(os.path.abspath(__file__)),
                          music=(f"用 {os.path.basename(music)}（已放在 "
                                 f"{mdir}/）")))
    meta["music"] = music
    json.dump(meta, open(meta_p, "w"), ensure_ascii=False, indent=1)
    print(f"music -> {os.path.basename(music)} for {len(meta['agents'])} agent(s)")
    print(f"  each <agent>/music/ replaced, each PROMPT.md rewritten, "
          f"bench.json updated")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stage", help="one clean input directory per agent")
    s.add_argument("dest")
    s.add_argument("--source", required=True, help="the footage folder")
    s.add_argument("--agents", required=True, help="comma-separated agent ids")
    s.add_argument("--music", help="one track, copied to each <agent>/music/")
    s.set_defaults(fn=stage)

    f = sub.add_parser("finish", help="stamp wall clock + self-reported cost")
    f.add_argument("dest")
    f.add_argument("--agent", required=True)
    f.add_argument("--model", help="only if the driver cannot be read automatically")
    f.add_argument("--tokens-in", type=int)
    f.add_argument("--tokens-out", type=int)
    f.add_argument("--session", help="part of a session filename, when more than "
                                     "one matches this agent")
    f.set_defaults(fn=finish)

    m = sub.add_parser("remusic", help="swap the track, rewrite every prompt")
    m.add_argument("dest")
    m.add_argument("--music", required=True)
    m.set_defaults(fn=remusic)

    r = sub.add_parser("report", help="one table across every agent")
    r.add_argument("dest")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=report)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
