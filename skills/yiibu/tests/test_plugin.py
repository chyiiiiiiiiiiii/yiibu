"""The delivery vehicle, which nothing was checking.

Every gate in this repo judges the VIDEO. Nothing judged the package that
carries the tool, and on 2026-08-22 that cost the plugin its own skill:
`commands/yiibu.md` and `skills/yiibu/SKILL.md` both claimed the name `yiibu`
in the plugin namespace, the command won, and `SKILL.md` — all 49,722
characters of it, including every trigger phrase — became unreachable. The
manifests validated. The suite was green. Four subagents loaded correctly. The
only thing that surfaced it was installing the plugin and asking a live session
what it could see.

That is a check that cannot live in a habit. These tests are the packaging
equivalent of the shipping gates: cheap, structural, and blind to nothing that
has already gone wrong once.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

SKILL = pathlib.Path(__file__).resolve().parent.parent
REPO = SKILL.parent.parent

pytestmark = pytest.mark.skipif(
    not (REPO / ".claude-plugin").is_dir(),
    reason="not laid out as a plugin (the skill can also be vendored alone)",
)


def _manifest(name):
    return json.loads((REPO / ".claude-plugin" / f"{name}.json").read_text())


def _frontmatter(path):
    """The loader reads YAML frontmatter; parse the subset without a dep."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ── the manifests ───────────────────────────────────────────────────────

def test_the_two_manifests_agree_on_name_and_version():
    """`claude plugin tag` refuses to tag a release when these disagree, so a
    drift here is found at the worst moment — mid-publish."""
    p = _manifest("plugin")
    entries = [e for e in _manifest("marketplace")["plugins"]
               if e["name"] == p["name"]]
    assert entries, f"marketplace.json has no entry for {p['name']!r}"
    assert entries[0]["version"] == p["version"], (
        f"plugin.json says {p['version']}, marketplace entry says "
        f"{entries[0]['version']}")


def test_the_marketplace_points_at_something_that_exists():
    src = _manifest("marketplace")["plugins"][0]["source"]
    if isinstance(src, str) and src.startswith("."):
        assert (REPO / src).is_dir(), f"source {src!r} is not a directory"


# ── the collision that shipped ──────────────────────────────────────────

def _components():
    """Everything that lands in the plugin's flat `plugin:name` namespace."""
    found = {}
    for md in sorted((REPO / "commands").glob("*.md")) if (REPO / "commands").is_dir() else []:
        found.setdefault(md.stem, []).append(f"commands/{md.name}")
    for skill_md in sorted((REPO / "skills").glob("*/SKILL.md")):
        name = _frontmatter(skill_md).get("name") or skill_md.parent.name
        found.setdefault(name, []).append(f"skills/{skill_md.parent.name}/SKILL.md")
    for md in sorted((REPO / "agents").glob("*.md")) if (REPO / "agents").is_dir() else []:
        name = _frontmatter(md).get("name") or md.stem
        found.setdefault(name, []).append(f"agents/{md.name}")
    return found


def test_no_two_components_claim_the_same_name():
    """The defect, reconstructed.

    Components share one flat namespace per plugin. When two claim a name, one
    silently shadows the other — no error at install, nothing in `validate`,
    and the loser is simply absent from what the model can see.
    """
    clashes = {n: where for n, where in _components().items() if len(where) > 1}
    assert not clashes, (
        "two plugin components claim the same name; one will shadow the "
        f"other at load time:\n  " +
        "\n  ".join(f"{n}: {', '.join(w)}" for n, w in clashes.items()))


def test_the_skill_is_among_the_components():
    """Cheap backstop: if the skill ever stops being discoverable, say so here
    rather than in a user's session."""
    assert "yiibu" in _components(), "the yiibu skill is not a discoverable component"


# ── the agents ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "agent",
    sorted(p.name for p in (REPO / "agents").glob("*.md"))
    if (REPO / "agents").is_dir() else [],
)
def test_every_agent_declares_what_the_loader_needs(agent):
    fm = _frontmatter(REPO / "agents" / agent)
    stem = agent[:-3]
    assert fm.get("name") == stem, (
        f"{agent}: frontmatter name {fm.get('name')!r} does not match the "
        f"filename; the filename is what the namespace uses")
    assert fm.get("description"), (
        f"{agent}: no description — the description is the ONLY thing the "
        f"caller sees when deciding whether to delegate")
    assert fm.get("tools"), f"{agent}: no tools declared"


def test_the_agents_the_docs_promise_are_the_agents_that_exist():
    """AGENTS.md tabulates each agent against its portable equivalent. An agent
    renamed on disk and not in that table is a broken promise to a non-Claude
    driver."""
    named = set()
    for doc in ("AGENTS.md", "CLAUDE.md"):
        text = (REPO / doc).read_text(encoding="utf-8")
        for p in (REPO / "agents").glob("*.md"):
            if p.stem in text:
                named.add(p.stem)
    on_disk = {p.stem for p in (REPO / "agents").glob("*.md")}
    assert named == on_disk, (
        f"agents on disk but undocumented: {sorted(on_disk - named)}")


# ── the CLI's own opinion, when it is available ─────────────────────────

def test_the_cli_validates_the_plugin():
    """Schema drift in Claude Code shows up here first. Skipped where the CLI
    is absent, which includes the Linux CI leg."""
    if not shutil.which("claude"):
        pytest.skip("claude CLI not on PATH")
    r = subprocess.run(["claude", "plugin", "validate", str(REPO)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"claude plugin validate failed:\n{r.stdout}{r.stderr}"
    assert "warning" not in (r.stdout + r.stderr).lower(), (
        f"validate passed with warnings:\n{r.stdout}{r.stderr}")
