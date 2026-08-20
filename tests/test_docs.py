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
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

DOCS = sorted(p for p in ROOT.rglob("*.md")
              if ".git" not in p.parts and ".pytest_cache" not in p.parts
              and ".venv" not in p.parts)
PYFILES = sorted(p for p in ROOT.rglob("*.py")
                 if ".git" not in p.parts and ".venv" not in p.parts
                 and "__pycache__" not in p.parts)

DOCTEXT = {p: p.read_text(encoding="utf-8", errors="ignore") for p in DOCS}
ALLDOCS = "\n".join(DOCTEXT.values())
ALLCODE = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in PYFILES)

HOUSE = json.loads((ROOT / "house_style.json").read_text())


def _rel(p):
    return str(p.relative_to(ROOT))


# ── CLI flags, both directions ───────────────────────────────────────────

CODE_FLAGS = set(re.findall(r'add_argument\(\s*["\'](--[a-z0-9-]+)', ALLCODE))

# Flags that belong to tools this repo documents by reference rather than by
# listing, or that are generic shell conventions rather than our surface.
FLAG_ALLOWLIST = {"--dry-run", "--check"}


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
            m = re.search(r'\b(\d{1,2})\s+(?:blocking\s+)?gates?\b', line, re.I)
            if m and int(m.group(1)) != n:
                wrong.setdefault(_rel(path), []).append(f"{line_no}: {m.group(0)}")
            for bad_n, word in words.items():
                if bad_n != n and re.search(rf'\b{word}\b\s+(?:blocking\s+)?gates?',
                                            line, re.I):
                    wrong.setdefault(_rel(path), []).append(f"{line_no}: {word}")
    assert not wrong, f"gates.py defines {n} gates; docs disagree: {wrong}"


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
    importlib.import_module(mod)
