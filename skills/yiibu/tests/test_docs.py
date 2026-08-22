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
    to preserve.
    """
    n = len(re.findall(r'^def gate_(\w+)', (ROOT / "gates.py").read_text(), re.M))
    words = {12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen"}
    wrong = {}
    for path, text in DOCTEXT.items():
        if path.name == "CHANGELOG.md":
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
    assert not wrong, f"gates.py defines {n} gates; docs disagree: {wrong}"



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
                           "asr_new.py", "your_build.py"}:
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
