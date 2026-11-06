"""The floor digest's deterministic selftest runs as part of the suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SELFTEST = Path(__file__).resolve().parents[1] / "reports" / "dashboard" / "selftest_floor_digest.py"


def test_floor_digest_selftest_passes():
    """``selftest_floor_digest.py`` builds its fixtures and every check passes."""
    res = subprocess.run([sys.executable, str(SELFTEST)], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS" in res.stdout.splitlines()[-1], res.stdout
