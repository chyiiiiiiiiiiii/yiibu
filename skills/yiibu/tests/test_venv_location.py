"""Where the venv that holds faster-whisper and the SDKs lives.

It used to live only at SKILL_DIR/.venv. Claude Code installs a plugin by
copying the skill into a new versioned cache folder, so that venv was either
copied along (710 MB of it, 2026-10-26) or, from a git source, missing — and
every plugin update lost it. The venv now lives outside the skill, at
$YIIBU_VENV (default ~/.yiibu/venv); the in-skill .venv is still found so an
existing setup keeps working.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "modules")]

import config  # noqa: E402


def _fake_venv(root):
    b = root / "bin"
    b.mkdir(parents=True)
    (b / "python3").write_text("")
    return str(b / "python3")


def test_shared_venv_wins_over_the_in_skill_one(tmp_path, monkeypatch):
    shared = _fake_venv(tmp_path / "shared")
    skill = tmp_path / "skill"
    _fake_venv(skill / ".venv")
    monkeypatch.setenv("YIIBU_VENV", str(tmp_path / "shared"))
    monkeypatch.setattr(config, "SKILL_DIR", str(skill))
    assert config.venv_python() == shared


def test_in_skill_venv_still_found_when_no_shared_one(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    legacy = _fake_venv(skill / ".venv")
    monkeypatch.setenv("YIIBU_VENV", str(tmp_path / "absent"))
    monkeypatch.delenv("YIIBU_SKILL_DIR", raising=False)
    monkeypatch.setattr(config, "SKILL_DIR", str(skill))
    assert config.venv_python() == legacy


def test_none_when_no_venv_anywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("YIIBU_VENV", str(tmp_path / "absent"))
    monkeypatch.delenv("YIIBU_SKILL_DIR", raising=False)
    monkeypatch.setattr(config, "SKILL_DIR", str(tmp_path / "skill"))
    assert config.venv_python() is None


def test_no_script_builds_its_own_venv_path():
    # every caller goes through config.venv_python(), so the location is decided once
    offenders = []
    for p in list(ROOT.glob("*.py")) + list((ROOT / "modules").glob("*.py")):
        if p.name == "config.py":
            continue
        if '".venv", "bin"' in p.read_text(encoding="utf-8"):
            offenders.append(p.name)
    assert offenders == []
