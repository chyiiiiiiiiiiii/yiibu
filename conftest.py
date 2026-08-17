"""Put the skill root on sys.path for the test suite.

Without this, `from modules.bgm import ...` in tests/ only resolves if pytest
happens to be invoked from the repo root with the right import mode — so a fresh
clone runs the suite and sees 9 of 11 files fail at import. A red suite on first
run is the fastest way to lose a reader's trust in a repo.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, os.path.join(ROOT, "modules")):
    if p not in sys.path:
        sys.path.insert(0, p)
