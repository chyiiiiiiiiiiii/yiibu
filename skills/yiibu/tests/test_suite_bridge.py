"""Make the script-style suites count under plain `pytest`.

`tests/test_gates.py` and `tests/test_house_style.py` are runnable scripts with
their own check() runner (that is what doctor.py executes), so pytest collects
zero tests from them. Without this bridge, `pytest` can be all green while the
house-style suite is red — which is how a broken fixture almost shipped on
2026-08-18. One subprocess each; red script → red pytest.
"""
import os
import subprocess
import sys

import pytest

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("script", ["test_gates.py", "test_house_style.py"])
def test_script_suite_is_green(script):
    r = subprocess.run([sys.executable, os.path.join(SKILL, "tests", script)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{script} failed:\n{r.stdout}\n{r.stderr}"
