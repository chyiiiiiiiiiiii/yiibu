"""Shared LLM text generation via the google-genai SDK (run in the skill's .venv).

Replaces the `gemini -p` CLI for TEXT generation, which was (a) disallowed by the
user's global policy and (b) unreliable (returned malformed JSON / empty output,
breaking auto B-roll planning and subtitle segmentation).

Scope, so this docstring stops overclaiming: five call sites still shell out to
the CLI — four in modules/broll.py, one in modules/bgm.py, listed in SETUP.md.
Two of them pass `--file` for vision and have no equivalent here yet. All five
fall back cleanly when the CLI is absent.

Key resolution: the shell rc file is treated as the source of truth (an
interactive shell's exported key is usually the maintained one, while a stale
copy can linger in a launchd/CI environment), so ~/.zshrc is read first and the
process environment is the fallback. Set YIIBU_GEMINI_KEY to override both.
"""
import json
import os
import re
import subprocess
import tempfile
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CACHED_KEY = None


def _venv_python() -> str:
    p = os.path.join(SKILL_DIR, ".venv", "bin", "python3")
    return p if os.path.exists(p) else "python3"


def resolve_gemini_key() -> str:
    """Return a working Gemini API key.

    Order: YIIBU_GEMINI_KEY env override, then ~/.zshrc's GEMINI_API_KEY /
    GOOGLE_API_KEY, then the process environment. Cached per process.
    """
    global _CACHED_KEY
    if _CACHED_KEY is not None:
        return _CACHED_KEY
    override = os.environ.get("YIIBU_GEMINI_KEY")
    if override:
        _CACHED_KEY = override
        return override
    key = ""
    try:
        with open(os.path.expanduser("~/.zshrc"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*export\s+(?:GEMINI_API_KEY|GOOGLE_API_KEY)=["\']?([^"\'\s]+)', line)
                if m:
                    key = m.group(1)  # last wins
    except OSError:
        pass
    key = key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    _CACHED_KEY = key
    return key


def gemini_generate(prompt: str, model: str = "gemini-2.5-flash", timeout: int = 120) -> Optional[str]:
    """Generate text from Gemini via the .venv SDK. Returns text or None on failure."""
    key = resolve_gemini_key()
    if not key:
        print("  LLM: no GEMINI_API_KEY resolved")
        return None

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(prompt)
        prompt_file = f.name

    # Key travels via the child's environment, NOT the -c script: argv is
    # world-readable in `ps` for the lifetime of the call.
    script = (
        "import os, sys\n"
        "from google import genai\n"
        f"model = {json.dumps(model)}\n"
        f"prompt = open({json.dumps(prompt_file)}, encoding='utf-8').read()\n"
        "client = genai.Client(api_key=os.environ['YIIBU_LLM_KEY'])\n"
        "resp = client.models.generate_content(model=model, contents=prompt)\n"
        "sys.stdout.write(resp.text or '')\n"
    )
    try:
        result = subprocess.run(
            [_venv_python(), "-c", script],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "YIIBU_LLM_KEY": key},
        )
        if result.returncode != 0:
            print(f"  LLM SDK error: {result.stderr.strip()[-200:]}")
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("  LLM SDK timeout")
        return None
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass
