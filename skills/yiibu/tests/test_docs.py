"""The docs are part of the product, so they get tests too.

Everything here was a real drift found by hand on 2026-08-21, and hand-auditing
3,400 lines of markdown is not a thing anyone will do twice:

  * SKILL.md taught `--no-music`. The flag is `--no-bgm`. Nothing had ever
    checked that a documented flag exists.
  * Ten places across five documents said the pill sits at 23% of frame height.
    `house_style.json` was raised to 18% on 2026-08-19 and the docs never moved,
    so the written spec and the enforced spec disagreed for two days — including
    the error message `gates.py` itself printed when it rejected a layout.
  * Eight flags existed with no mention in any document, which by this repo's own
    rule ("an undocumented capability does not exist") means they did not exist.

These are cheap, mechanical invariants. They cannot tell you whether a sentence
is *true*, only whether it still refers to something real — which is the class of
rot that actually happens.
"""
import ast
import importlib.util
import json
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The repo root sits two levels above the skill root once this ships as a
# plugin (repo/skills/yiibu/). The landing READMEs live up there and carry the
# gate table, so the doc guards have to see them — otherwise the two files a
# stranger reads first are the only two nothing checks.
REPO_ROOT = ROOT.parent.parent if (ROOT.parent.parent / ".claude-plugin").is_dir() else ROOT

DOCS = sorted(
    [p for p in ROOT.rglob("*.md")
     if ".git" not in p.parts and ".pytest_cache" not in p.parts
     and ".venv" not in p.parts]
    + ([p for p in REPO_ROOT.glob("*.md")] if REPO_ROOT != ROOT else [])
)
PYFILES = sorted(p for p in ROOT.rglob("*.py")
                 if ".git" not in p.parts and ".venv" not in p.parts
                 and "__pycache__" not in p.parts)

DOCTEXT = {p: p.read_text(encoding="utf-8", errors="ignore") for p in DOCS}
ALLDOCS = "\n".join(DOCTEXT.values())
ALLCODE = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in PYFILES)

CJK_NUM = {12: "十二", 13: "十三", 14: "十四", 15: "十五", 16: "十六",
           17: "十七", 18: "十八", 19: "十九", 20: "二十"}

HOUSE = json.loads((ROOT / "house_style.json").read_text())


def _rel(p):
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p.relative_to(REPO_ROOT))


# ── CLI flags, both directions ───────────────────────────────────────────

CODE_FLAGS = set(re.findall(r'add_argument\(\s*["\'](--[a-z0-9-]+)', ALLCODE))

# install.sh is ours too, and its flags are documented in the README. Reading
# only argparse meant a shell flag looked undocumented-but-documented — the
# guard rejected `--full` on the day it was written, which is the guard being
# short-sighted rather than the doc being wrong. Rename the flag and the READMEs
# now break here, which is the whole point.
for _sh in list(REPO_ROOT.glob("*.sh")) + list(ROOT.glob("*.sh")):
    # A letter must follow the dashes: install.sh draws separator rules out of
    # forty hyphens, and `--------` is not a flag.
    CODE_FLAGS |= set(re.findall(r'"(--[a-z][a-z0-9-]{1,20})"',
                                 _sh.read_text(encoding="utf-8")))

# Flags belonging to OTHER people's tools, which the docs name because a reader
# has to type them, and generic shell conventions. Anything else with a `--` in
# backticks is claimed as ours and has to exist.
FLAG_ALLOWLIST = {
    "--dry-run", "--check",
    "--file",          # gemini CLI, in SETUP.md's vision call sites
}


def test_every_documented_flag_exists():
    """A doc that teaches a flag the code does not accept is worse than silence.

    SKILL.md taught `--no-music` for months; the real flag is `--no-bgm`.
    """
    bad = {}
    for path, text in DOCTEXT.items():
        for flag in sorted(set(re.findall(r'`(--[a-z0-9-]{3,})`', text))):
            if flag in CODE_FLAGS or flag in FLAG_ALLOWLIST:
                continue
            bad.setdefault(_rel(path), []).append(flag)
    assert not bad, f"documented flags that no argparse defines: {bad}"


def test_every_flag_is_documented():
    """This repo's rule is that an undocumented capability does not exist."""
    missing = sorted(f for f in CODE_FLAGS if f not in ALLDOCS)
    assert not missing, (
        f"flags with no mention in any .md: {missing} — add them to "
        f"docs/CONFIGURATION.md §5 or to the SKILL.md option list"
    )


# ── numbers that exist in exactly one authoritative place ────────────────

def test_docs_quote_the_real_pill_position():
    """house_style.json is the spec; prose repeating a stale number is a lie.

    The pill moved 0.23 -> 0.18 and ten places kept saying 23%, including the
    rejection message gates.py printed. A reader building to the written spec
    would have been rejected by the gate enforcing the other one.
    """
    live = f"{HOUSE['pill']['centre_pct'] * 100:.0f}%"
    stale = [f"{p}%" for p in (23, 20, 25, 30) if f"{p}%" != live]
    offenders = {}
    for path, text in DOCTEXT.items():
        for line_no, line in enumerate(text.splitlines(), 1):
            if "pill" not in line.lower():
                continue
            for s in stale:
                if s in line:
                    offenders.setdefault(_rel(path), []).append(f"{line_no}: {s}")
    assert not offenders, (
        f"pill is at {live} in house_style.json but the docs say otherwise: "
        f"{offenders}"
    )


def test_docs_quote_the_real_caption_baseline():
    live = f"{HOUSE['captions']['baseline_pct'] * 100:.0f}%"
    offenders = {}
    for path, text in DOCTEXT.items():
        for line_no, line in enumerate(text.splitlines(), 1):
            if "baseline" not in line.lower():
                continue
            found = re.findall(r'\b(\d{2})%', line)
            for f in found:
                if f"{f}%" != live and int(f) > 40:
                    offenders.setdefault(_rel(path), []).append(f"{line_no}: {f}%")
    assert not offenders, (
        f"caption baseline is {live} in house_style.json: {offenders}")


def test_gate_count_in_docs_matches_gates_py():
    """SKILL.md said twelve for a while after Duck and Dwell shipped.

    CHANGELOG.md is exempt: its entries record what was true at each release,
    and editing them to match today would be falsifying the history they exist
    to preserve. A dated report (BENCHMARK-YYYY-MM-DD.md) is the same category —
    it says what the suite was on the day it was run, and a snapshot edited to
    match today is no longer evidence of anything.
    """
    n = len(re.findall(r'^def gate_(\w+)', (ROOT / "gates.py").read_text(), re.M))
    words = {12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
             16: "sixteen", 17: "seventeen", 18: "eighteen",
             19: "nineteen", 20: "twenty"}
    wrong = {}
    for path, text in DOCTEXT.items():
        if path.name == "CHANGELOG.md" or re.match(r"^[A-Z]+-\d{4}-\d{2}-\d{2}\.md$",
                                                   path.name):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if not re.search(r'gate', line, re.I):
                continue
            # Both spellings below shipped WRONG while this test was green:
            # "gates.py  blocking shipping gates (12)" puts the number after the
            # noun, and "14 blocking shipping gates" puts two words in between.
            # A guard with a hole is worse than no guard, because the hole is
            # invisible: everyone reads the passing test as coverage.
            for pat in (r'\b(\d{1,2})\s+(?:\w+\s+){0,2}gates?\b',
                        r'gates?\b[^.\n]{0,24}?\((\d{1,2})\)'):
                m = re.search(pat, line, re.I)
                if m and int(m.group(1)) != n:
                    wrong.setdefault(_rel(path), []).append(f"{line_no}: {m.group(0)}")
            for bad_n, word in words.items():
                if bad_n != n and re.search(rf'\b{word}\b\s+(?:blocking\s+)?gates?',
                                            line, re.I):
                    wrong.setdefault(_rel(path), []).append(f"{line_no}: {word}")
            # The Chinese README was checked by none of the patterns above —
            # they all end in the English word "gate" — so it said 十七道閘門
            # for two days after its English sibling had been corrected to
            # nineteen. A guard that covers one translation is a guard that
            # quietly makes the other one the wrong half of a bilingual repo.
            if "當時" in line or "at the time" in line:
                continue
            for bad_n, word in CJK_NUM.items():
                if bad_n != n and re.search(rf'{word}\s*[道項]\s*(?:阻斷式)?閘門', line):
                    wrong.setdefault(_rel(path), []).append(f"{line_no}: {word}道閘門")
    assert not wrong, f"gates.py defines {n} gates; docs disagree: {wrong}"


@pytest.mark.parametrize("recipe", sorted(
    _rel(p) for p in (ROOT / "references").glob("*-template.md")))
def test_every_recipe_names_the_blocking_gate(recipe):
    """A recipe is where someone actually builds from, and two of the three
    got the ship step wrong at the same time: the food recipe ran `verify.py`
    ALONE and called it the delivery gate, and the running recipe never
    mentioned `gates.py` at all — while also asking for one video where the
    Deliverables gate requires the pair. Both were found by hand on 2026-08-25,
    which is exactly the audit nobody does twice."""
    text = (ROOT / recipe).read_text(encoding="utf-8")
    assert "gates.py" in text, (
        f"{recipe} never names gates.py — a recipe that ends at verify.py "
        f"teaches the advisory report as the ship check")


def test_plugin_manifest_gate_count():
    """The marketplace blurb is a doc, and it was the one nothing checked.

    `test_gate_count_matches_code` globs `*.md`. `.claude-plugin/plugin.json`
    is JSON, so it sat outside every guard and drifted: it advertised
    "seventeen blocking gates" while gates.py defined nineteen. That string is
    the first sentence a stranger reads about this plugin — a wrong number
    there is worse than a wrong number in ARCHITECTURE.md, not better.
    """
    manifest = REPO_ROOT / ".claude-plugin" / "plugin.json"
    if not manifest.exists():
        pytest.skip("not laid out as a plugin")
    n = len(re.findall(r'^def gate_(\w+)', (ROOT / "gates.py").read_text(), re.M))
    words = {12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
             16: "sixteen", 17: "seventeen", 18: "eighteen",
             19: "nineteen", 20: "twenty"}
    text = manifest.read_text(encoding="utf-8")
    wrong = [w for k, w in words.items()
             if k != n and re.search(rf'\b{w}\b\s+(?:blocking\s+)?gates?', text, re.I)]
    wrong += [m for m in re.findall(r'\b(\d{1,2})\s+(?:\w+\s+){0,2}gates?\b', text, re.I)
              if int(m) != n]
    assert not wrong, f"gates.py defines {n} gates; plugin.json says {wrong}"


def test_stop_hook_is_registered_and_documented():
    """The hook is the only thing that makes running the gates non-optional, so
    two ways of losing it get a test: deleting the manifest, and shipping it
    with nobody told it exists. A hook nobody knows about cannot be trusted or
    debugged — when it fires, it just looks like Claude refusing to stop."""
    manifest = REPO_ROOT / "hooks" / "hooks.json"
    if REPO_ROOT == ROOT:
        pytest.skip("not laid out as a plugin")
    assert manifest.exists(), "the Stop hook manifest is gone"
    assert "Stop" in json.loads(manifest.read_text())["hooks"]
    named = [_rel(p) for p, t in DOCTEXT.items() if "gate_guard" in t]
    assert named, "hooks/gate_guard.py is not mentioned in any document"



@pytest.mark.parametrize("doc", ["README.md", "README.zh-TW.md", "ARCHITECTURE.md"])
def test_every_gate_is_named_in_the_gate_tables(doc):
    """The count guard cannot see a table that is short by three rows.

    Duck, Dwell and Clearance shipped and were named in no table, in either
    language, while `test_gate_count_in_docs_matches_gates_py` stayed green —
    because nothing in the docs stated a total the number could contradict.
    """
    names = re.findall(r'^\s*\("(\w+)",', (ROOT / "gates.py").read_text(), re.M)
    path = ROOT / doc if (ROOT / doc).exists() else REPO_ROOT / doc
    text = path.read_text(encoding="utf-8")
    missing = [g for g in names if not re.search(rf'^\| {g} \|', text, re.M)]
    assert not missing, (
        f"{doc} has no table row for: {missing} — a gate a reader cannot find "
        f"is one they will trip over instead of build to"
    )


def test_every_gate_row_carries_its_provenance():
    """A gate table with a why column has to actually fill it.

    Both READMEs carried a two-column header while six rows had already been
    written with a third — Duck, Dwell, Clearance, Timeline, Pacing, Monologue.
    Markdown drops the overflow silently, so the reason each of those gates
    exists was in the file, in git, and invisible to every reader of the
    rendered page. ARCHITECTURE.md had the full three columns the whole time,
    which is how the drift went unnoticed: the information existed, just not
    where anybody looked.

    Checked structurally rather than by counting columns in one file, because
    the defect was a header and a row disagreeing, not a row being wrong.
    """
    tables = {"README.md": r'^\|\s*gate\s*\|',
              "README.zh-TW.md": r'^\|\s*閘門\s*\|',
              "ARCHITECTURE.md": r'^\|\s*gate\s*\|'}
    for doc, hdr_re in tables.items():
        path = ROOT / doc if (ROOT / doc).exists() else REPO_ROOT / doc
        lines = path.read_text(encoding="utf-8").splitlines()
        start = next((i for i, l in enumerate(lines)
                      if re.match(hdr_re, l)), None)
        assert start is not None, f"{doc} has no gate table any more"
        width = lines[start].count("|") - 1
        assert width == 3, (
            f"{doc}'s gate table has {width} columns — the third one is where "
            f"each gate says which shipped defect it encodes")
        for l in lines[start + 2:]:
            if not l.startswith("|"):
                break
            cells = [c.strip() for c in l.split("|")[1:-1]]
            assert len(cells) == width, (
                f"{doc}: row {cells[0]!r} has {len(cells)} cells against a "
                f"{width}-column header — markdown drops the overflow and the "
                f"text disappears from the rendered page")
            assert cells[2], (
                f"{doc}: gate {cells[0]!r} states no shipped defect. Every "
                f"threshold here was measured on a real edit; a gate that "
                f"cannot say which one is a number the next person will tune")


def test_every_gate_function_says_why_it_exists():
    """Five gates shipped with no docstring at all.

    Audio, Cover, Captions, Pill and Delivery — the oldest and most central of
    them — carried their reasoning only in the failure message, which is read
    when a build is BLOCKED and never by the person changing the threshold.
    CONTRIBUTING requires provenance for a new gate; nothing enforced it for the
    ones that predate the rule.
    """
    src = (ROOT / "gates.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)}
    registered = re.findall(
        r'^\s*\("(\w+)",\s*(?:lambda[^:]*:\s*)?(\w+)', src, re.M)
    thin = []
    for label, fn in registered:
        doc = ast.get_docstring(funcs[fn]) if fn in funcs else None
        if not doc or len(doc) < 60:
            thin.append(label)
    assert not thin, (
        f"gate(s) with no explanation of their own: {thin} — the docstring is "
        f"where the person EDITING a threshold learns what it cost to find it")


# ── the lesson pages state the count in prose AND in code ───────────────

LESSONS = [p for p in (ROOT / "docs").glob("lesson*.html")]


@pytest.mark.parametrize("page", sorted(_rel(p) for p in LESSONS))
def test_lesson_pages_agree_with_gates_py(page):
    """The .md guards above glob *.md, so the lesson pages were outside them.

    Both pages hard-code the total in running prose ("19 checks", "19 道") and
    again as a literal list in their own JS, and the count moved from 17 to 19
    in the middle of the session that wrote them — gate_pacing and
    gate_monologue landed while the page was being drafted. A reader who counts
    the rows and gets a different number than the sentence above them stops
    trusting the whole page, and that is the one thing a page like this sells.

    Historical statements are exempt, the same way CHANGELOG.md is exempt from
    `test_gate_count_in_docs_matches_gates_py`: both pages deliberately tell the
    story of a build that passed "all 12 checks that existed at the time", and
    editing that to 19 would falsify the incident it exists to report. The
    marker is an explicit past reference on the same line.
    """
    text = (ROOT / page).read_text(encoding="utf-8") if (ROOT / page).exists() \
        else (REPO_ROOT / page).read_text(encoding="utf-8")
    src = (ROOT / "gates.py").read_text()
    n = len(re.findall(r'^def gate_(\w+)', src, re.M))
    names = re.findall(r'^\s*\("(\w+)",', src, re.M)

    # 1. every gate is a row in the page's own list
    missing = [g for g in names if f'"{g}"' not in text and f'["{g}"' not in text]
    assert not missing, (
        f"{page} lists no row for {missing} — the interactive panel claims to be "
        f"the full set, so a short list is a false claim, not an omission"
    )

    # 2. no sentence claims a different total
    words = {12: ("twelve", "十二"), 13: ("thirteen", "十三"), 14: ("fourteen", "十四"),
             15: ("fifteen", "十五"), 16: ("sixteen", "十六"), 17: ("seventeen", "十七"),
             18: ("eighteen", "十八"), 19: ("nineteen", "十九"), 20: ("twenty", "二十")}
    past = ("at the time", "當時", "that existed")
    wrong = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if any(marker in line for marker in past):
            continue
        for m in re.finditer(r'(\d{1,2})\s*(?:[道項]|/\s*\d{1,2}\s*(?:green|綠)|'
                             r'(?:\w+\s+){0,2}(?:checks?|gates?|measurable|green)\b)', line):
            if int(m.group(1)) != n:
                wrong.append(f"{line_no}: {m.group(0).strip()}")
        for bad_n, forms in words.items():
            if bad_n == n:
                continue
            for w in forms:
                if re.search(rf'{w}\s*(?:[道項]|(?:\w+\s+){{0,2}}(?:checks?|gates?|measurable|green)\b)', line, re.I):
                    wrong.append(f"{line_no}: {w}")
    assert not wrong, f"gates.py defines {n} gates; {page} disagrees: {wrong}"


@pytest.mark.parametrize("page", sorted(_rel(p) for p in LESSONS))
def test_lesson_pages_embed_no_held_demo(page):
    """make_demos.py holds three demos back, each for a stated reason.

    The first draft of these pages embedded a frame from food-hotpot, held for
    "bystander faces incl. a child". Nothing objected; a person happened to read
    make_demos.py. The clips are base64 inside the page, so nothing can identify
    them after the fact — the page therefore DECLARES which ones it carries, in
    an HTML comment at the top, and that declaration is what this reads. Same
    shape as the rest of this repo: a contract stated as an artifact a check can
    read, not a convention someone has to honour.
    """
    path = (ROOT / page) if (ROOT / page).exists() else (REPO_ROOT / page)
    text = path.read_text(encoding="utf-8")
    m = re.search(r'<!-- embedded demo clips \(docs/demo/<name>\.gif\):([^\n]*)', text)
    assert m, (f"{page} embeds clips but declares none — add the "
               f"'embedded demo clips' comment so this check has something to read")
    used = [c.strip() for c in m.group(1).split(",") if c.strip()]
    assert used, f"{page} declares an empty clip list"

    spec = importlib.util.spec_from_file_location(
        "_make_demos", str(ROOT / "docs" / "make_demos.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    known = {d[0]: d[4] for d in mod.DEMOS}

    unknown = [c for c in used if c not in known]
    assert not unknown, f"{page} names clips make_demos.py does not know: {unknown}"
    held = {c: known[c] for c in used if known[c]}
    assert not held, (
        f"{page} embeds demos that are held back: {held} — that list is the "
        f"record of what may be published, and a page that ignores it "
        f"republishes exactly what was held")


def test_lesson_pages_state_the_real_test_count(request):
    """The pages cite the suite size as evidence the checks cannot rot.

    Adding this very test moved the count 264 -> 266 and made both pages wrong
    in the same commit that was written to stop exactly this. Skipped on a
    subset run, for the reason given in the CLAUDE.md version of this check.
    """
    o = request.config.option
    if o.keyword or o.markexpr or o.file_or_dir:
        pytest.skip("subset run — the count only means anything for the whole suite")
    actual = len(request.session.items)
    wrong, silent = {}, []
    for path in LESSONS:
        text = path.read_text(encoding="utf-8")
        found = list(re.finditer(r'(\d{3})\s*(?:tests|個測試)', text))
        # A page that states NO number passed this check for free. It is not a
        # hypothetical: a careless edit here deleted "321" and left " tests",
        # and the guard stayed green because it only ever compared numbers it
        # found. The CLAUDE.md version of this check already asserts presence;
        # this one did not, which made the pair look symmetrical and was not.
        if not found and re.search(r'\s(?:tests|個測試)\b', text):
            silent.append(_rel(path))
        for m in found:
            if int(m.group(1)) != actual:
                wrong.setdefault(_rel(path), []).append(m.group(0))
    assert not silent, f"these pages mention tests with no count: {silent}"
    assert not wrong, f"the suite collects {actual} tests; lesson pages say: {wrong}"



# ── the repo's own rule: no gate without a test ──────────────────────────

def test_every_gate_has_a_test():
    """ARCHITECTURE.md states this as a repo rule. gate_delivery had none."""
    gates = set(re.findall(r'^def gate_(\w+)', (ROOT / "gates.py").read_text(), re.M))
    # This file must not count as coverage for itself: naming a gate in a
    # docstring here would otherwise satisfy the check it exists to make. That
    # happened on the first run — gate_delivery "passed" because the sentence
    # above mentions it.
    tests = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                      for p in (ROOT / "tests").glob("*.py")
                      if p.name != "test_docs.py")
    missing = sorted(g for g in gates if f"gate_{g}" not in tests)
    assert not missing, (
        f"gates with no test: {sorted(missing)} — the rule is no gate without a "
        f"test reconstructing the defect it catches"
    )



@pytest.mark.parametrize("zh", sorted(_rel(p) for p in DOCS
                                      if p.name.endswith(".zh-TW.md")))
def test_translations_link_back_to_their_original(zh):
    """A translation that cannot be found from the English page is a page that
    silently rots: nobody who edits the original ever sees it.

    Both directions are required — the English page carries the switcher, and
    the translation names the file it was translated from. Matched by PATH, not
    by basename: this repo has three README.md files, and the first version of
    this test happily compared the root translation against sfx-library's.
    """
    zh_path = (ROOT / zh) if (ROOT / zh).exists() else (REPO_ROOT / zh)
    en_path = zh_path.with_name(zh_path.name.replace(".zh-TW.md", ".md"))
    assert en_path.exists(), f"{zh} translates a page that does not exist: {_rel(en_path)}"
    en, tw = en_path.read_text(), zh_path.read_text()
    assert zh_path.name in en, f"{_rel(en_path)} has no link to its translation {zh_path.name}"
    assert en_path.name in tw, f"{zh} does not link back to {en_path.name}"



# ── referenced code symbols still exist ─────────────────────────────────

def test_documented_functions_exist():
    """`some_function()` in prose should still be findable in the code."""
    bad = {}
    for path, text in DOCTEXT.items():
        for sym in sorted(set(re.findall(r'`([a-z_][a-z0-9_]{4,})\(\)`', text))):
            if not re.search(rf'\bdef {re.escape(sym)}\b', ALLCODE):
                bad.setdefault(_rel(path), []).append(sym + "()")
    assert not bad, f"documented functions that no longer exist: {bad}"


def test_documented_modules_exist():
    """`modules/x.py` and top-level scripts named in docs must be real files."""
    bad = {}
    for path, text in DOCTEXT.items():
        for ref in sorted(set(re.findall(r'`((?:modules|tests|references)/[\w/]+\.py)`',
                                         text))):
            if not (ROOT / ref).exists():
                bad.setdefault(_rel(path), []).append(ref)
        for ref in sorted(set(re.findall(r'`([a-z_]+\.py)`', text))):
            if not any((ROOT / d / ref).exists() if d else (ROOT / ref).exists()
                       for d in ("", "modules", "tests", "references", "docs")):
                # build scripts are written per-project, not shipped
                if ref in {"vp_build.py", "vp_compose.py", "build.py",
                           "captions.py", "render.py", "mix_bgm.py",
                           "make_cover.py", "duck_check.py", "timeline.py",
                           "asr_new.py", "your_build.py",
                           # a user's own earlier build config, named in the
                           # 2026-08-22 benchmark as the thing that leaked into
                           # the source folder. It is evidence, not a repo file.
                           "project_config.py"}:
                    continue
                bad.setdefault(_rel(path), []).append(ref)
    assert not bad, f"documented files that do not exist: {bad}"


# ── env vars are the machine-facing contract ────────────────────────────

def test_every_env_override_is_documented():
    env = sorted(set(re.findall(r'os\.environ\.get\(\s*["\'](YIIBU_[A-Z0-9_]+)',
                                ALLCODE)))
    cfg = (ROOT / "docs" / "CONFIGURATION.md").read_text()
    missing = [e for e in env if e not in cfg]
    assert not missing, (
        f"YIIBU_* overrides missing from docs/CONFIGURATION.md: {missing}")


def test_the_documented_test_count_is_the_real_one(request):
    """CLAUDE.md advertises how many tests there are. It said 221 for long
    enough that nobody remembers when it stopped being true, and it was wrong
    again within hours of being corrected — a number a human retypes is a
    number that rots.

    Only meaningful when the whole suite was collected, so a `-k`, a `-m`, or a
    named path skips it rather than failing on a subset it was never counting.
    """
    o = request.config.option
    if o.keyword or o.markexpr or o.file_or_dir:
        pytest.skip("subset run — the count only means anything for the whole suite")

    doc = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    m = re.search(r"pytest[^\n]*#\s*(\d+)\s+tests", doc)
    assert m, "CLAUDE.md no longer states a test count next to the pytest line"
    stated, actual = int(m.group(1)), len(request.session.items)
    assert stated == actual, (
        f"CLAUDE.md says {stated} tests, the suite collects {actual}. "
        f"Update the comment on the pytest line.")


def test_no_test_file_can_remove_itself_from_collection():
    """A module-level `importorskip` deletes a whole FILE from the run, and the
    only trace is one line that needs `-rs` to show.

    tests/test_cutout.py sat behind one for cv2 and mediapipe. All ten of its
    tests — the guard on the cutout variant argument — were absent from every
    CI run, on the only dependency set CI has, and the log said nothing. A
    function-level skip is fine: it is counted, it is named, and the file it
    lives in still reports. A module-level one is a silent cap.
    """
    import ast
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:                       # module scope only
            for n in ast.walk(node):
                if isinstance(n, ast.Attribute) and n.attr == "importorskip":
                    offenders.append(f"{_rel(path)}:{n.lineno}")
    assert not offenders, (
        "module-level importorskip removes whole files from collection "
        "invisibly; make the import lazy or skip per-test instead:\n  "
        + "\n  ".join(offenders))


def test_the_pre_rename_name_is_gone_from_the_code():
    """The rename to `yiibu` left one live env var behind: `_find_font` read
    `VIDEO_POSTPROD_FONT` while every document advertised `YIIBU_*`, so the
    documented way to point at a font file did nothing.

    The guard above could not see it, because it only ever looks for names
    matching `YIIBU_[A-Z0-9_]+` — a leftover from before the rename is exactly
    the string that pattern cannot match. CHANGELOG.md is exempt: it is the
    history of the rename and has to be able to say the old name.
    """
    stale = []
    for path in ROOT.rglob("*.py"):
        if any(part in {".venv", "__pycache__", ".pytest_cache"}
               for part in path.parts):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8",
                                                errors="replace").splitlines(), 1):
            if "VIDEO_POSTPROD" in line or "video-postprod" in line:
                if path.name == "test_docs.py":
                    continue
                stale.append(f"{_rel(path)}:{n}: {line.strip()[:70]}")
    assert not stale, (
        "the pre-rename name survives in code:\n  " + "\n  ".join(stale))


def test_documented_env_defaults_match_the_code():
    """Naming the variable is half the contract; the default is the other half.

    CONFIGURATION.md kept saying YIIBU_WORK_DIR_PREFIX defaulted to
    /tmp/video-postprod for a whole rename, because the guard above only ever
    checked that the NAME appeared somewhere on the page. A documented default
    that no longer matches the code is worse than an undocumented one: the
    reader has no reason to go and look.

    Only the row that DEFINES the variable is checked — the one whose first
    table cell is the name. Matching every line that mentions it made an
    ordinary cross-reference ("takes precedence over `YIIBU_FONT_NAME`") read
    as a drifted default, which is a guard that punishes writing a good doc.
    """
    pairs = re.findall(
        r'os\.environ\.get\(\s*["\'](YIIBU_[A-Z0-9_]+)["\']\s*,\s*["\']([^"\']+)["\']',
        ALLCODE)
    cfg = (ROOT / "docs" / "CONFIGURATION.md").read_text()
    wrong = []
    for name, default in pairs:
        for line in cfg.splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 1 and cells[1] == f"`{name}`" and default not in line:
                wrong.append(f"{name}: code says {default!r}, doc line says {line.strip()[:70]}")
    assert not wrong, "documented defaults that drifted from the code:\n  " + "\n  ".join(wrong)


@pytest.mark.parametrize("doc", [d for d in DOCS if d.name != "CHANGELOG.md"],
                         ids=lambda p: p.name)
def test_no_dead_relative_links(doc):
    """A broken link in a README is the first thing a new reader hits."""
    text = DOCTEXT[doc]
    bad = []
    for target in re.findall(r'\]\((?!https?:|#|mailto:)([^)#]+)', text):
        resolved = (doc.parent / target).resolve()
        if not resolved.exists():
            bad.append(target)
    assert not bad, f"{_rel(doc)} links to missing paths: {bad}"


# ── the reference examples are teaching material ────────────────────────

@pytest.mark.parametrize(
    "script",
    sorted(str(p.relative_to(ROOT))
           for p in (ROOT / "references" / "examples").rglob("*.py")))
def test_examples_pass_the_repos_own_linter(script):
    """An example that trips build_lint is teaching an antipattern.

    Two of them did on 2026-08-21: the event render used libx264 at 1080x1920,
    and the running build shipped BOTH documented audio defects —
    sidechaincompress+amix (which silently stopped passing the bed ~1.6s before
    the end) and loudnorm as an inline filter (which eats the tail and NaNs on
    silence). People copy these files; that is what they are for.

    Fixing them also exposed a linter false positive: `-loop 1` bounded by `-t`
    is safe, and the example's own comment said so. A linter that cries wolf on
    the shipped examples is one people learn to ignore.
    """
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "build_lint.py"),
                        str(ROOT / script)],
                       capture_output=True, text=True)
    assert "❌" not in r.stdout, f"{script}\n{r.stdout}"


def test_examples_compile():
    """A reference script that does not parse is worse than no reference."""
    import py_compile
    for p in sorted((ROOT / "references" / "examples").rglob("*.py")):
        py_compile.compile(str(p), doraise=True)


# ── every shipped module must at least import ───────────────────────────

@pytest.mark.parametrize(
    "mod",
    sorted([p.stem for p in ROOT.glob("*.py") if p.stem != "conftest"] +
           [f"modules.{p.stem}" for p in (ROOT / "modules").glob("*.py")
            if p.stem != "__init__"] +
           [p.stem for p in (ROOT / "references").glob("*.py")]))
def test_module_imports(mod):
    """resolve_music.py raised TypeError on import under Python 3.9.

    `path: str | None` is PEP 604, which needs 3.10, while SETUP.md declares a
    3.9 floor — and 3.9 is the stock python3 on macOS. The annotation is
    evaluated when the dataclass is created, so this was not a deprecation
    warning: the module was unusable, and so was every entry point that touched
    the music ladder. 189 tests passed throughout, because nothing imported it.

    An import test is the cheapest possible check and it would have caught this
    the day it landed.
    """
    import importlib
    sys.path[:0] = [str(ROOT / "references")]      # reference tools live there
    try:
        importlib.import_module(mod)
    except ImportError as e:
        # modules/cutout.py imports cv2 and mediapipe at the top, and neither is
        # in the core install. Skipping keeps `pytest` green on the ffmpeg +
        # Pillow + numpy machine the README promises — but only for a THIRD-PARTY
        # name. An ImportError naming one of our own modules is a real break and
        # still fails. The source is compiled either way, so the syntax half of
        # this check never goes missing.
        missing = (getattr(e, "name", "") or "").split(".")[0]
        ours = {p.stem for p in (ROOT / "modules").glob("*.py")} | {"config", "modules"}
        if not missing or missing in ours:
            raise
        src = ROOT / (mod.replace(".", "/") + ".py")
        if src.exists():
            compile(src.read_text(encoding="utf-8"), str(src), "exec")
        pytest.skip(f"{mod} needs the optional package {missing!r}")


# ── the visual gallery ──────────────────────────────────────────────────

def test_gallery_tiles_exist():
    """CAPABILITIES.md is the human-facing half of the capability map.

    An <img> pointing at nothing is worse than no gallery: it says the effect
    exists AND that somebody showed you it, while showing you a broken icon.
    """
    page = ROOT / "docs" / "CAPABILITIES.md"
    assert page.exists(), "docs/CAPABILITIES.md is missing"
    missing = [src for src in re.findall(r'<img src="([^"]+)"', page.read_text())
               if not (page.parent / src).exists()]
    assert not missing, f"gallery images referenced but not rendered: {missing}"


def test_gallery_generator_covers_every_tile():
    """Every tile on the page has to come from a generator, or it is a hand-made
    picture that will drift from the code the first time a house value moves —
    which is exactly what happened to caption-geometry.png.

    Two generators are allowed: make_gallery.py draws tiles from the code, and
    make_demos.py cuts them out of finished projects. Both are commands; a tile
    that came from neither is somebody's screenshot.
    """
    gen = (ROOT / "docs" / "make_gallery.py").read_text()
    demos = (ROOT / "docs" / "make_demos.py").read_text()
    page = (ROOT / "docs" / "CAPABILITIES.md").read_text()
    used = {os.path.basename(s) for s in re.findall(r'<img src="gallery/([^"]+)"', page)}
    made = {n + ".png" for n in re.findall(r'save\(im, "([^"]+)"\)', gen)}
    # make_demos writes some tiles through a loop variable, so it declares the
    # full list instead of leaving it to be regexed out of the code.
    block = re.search(r'GALLERY_FILES = \((.*?)\)', demos, re.S)
    made |= set(re.findall(r'"([^"]+)"', block.group(1))) if block else set()
    assert used <= made, f"tiles on the page that nothing generates: {used - made}"
