from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

DFY = Path(__file__).resolve().parent.parent / "examples" / "abs.dfy"


def _docker_image_exists(name: str) -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "image", "inspect", name], capture_output=True).returncode == 0


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
@pytest.mark.skipif(not _docker_image_exists("veripy-dafny"), reason="veripy-dafny image not available")
def test_abs_verifies():
    try:
        result = subprocess.run(["uv", "run", "python", "-m", "veripy", "examples/abs.py"])
        assert result.returncode == 0
        assert DFY.exists()
        assert "method abs" in DFY.read_text()
    finally:
        DFY.unlink(missing_ok=True)
