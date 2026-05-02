from __future__ import annotations

import shutil
import subprocess

import pytest

ABS_SOURCE = """\
def abs(x: int) -> int:
    #@ ensures result >= 0
    #@ ensures result == x or result == -x
    if x >= 0:
        return x
    return -x
"""

EXPECTED_DFY = """\
method abs(x: int) returns (r: int)
  ensures r >= 0
  ensures r == x || r == -x
{
  if x >= 0 {
    r := x;
    return;
  }
  r := -x;
  return;
}
"""


def _docker_image_exists(name: str) -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "image", "inspect", name], capture_output=True).returncode == 0


def test_cli_writes_dfy_file(tmp_path):
    src = tmp_path / "abs.py"
    src.write_text(ABS_SOURCE)
    subprocess.run(["uv", "run", "python", "-m", "veripy", str(src)], check=False)
    assert (tmp_path / "abs.dfy").exists()


def test_cli_dfy_content_matches_expected(tmp_path):
    src = tmp_path / "abs.py"
    src.write_text(ABS_SOURCE)
    subprocess.run(["uv", "run", "python", "-m", "veripy", str(src)], check=False)
    assert (tmp_path / "abs.dfy").read_text() == EXPECTED_DFY


def test_cli_nonexistent_file_exits_1():
    result = subprocess.run(["uv", "run", "python", "-m", "veripy", "/nonexistent/path.py"], capture_output=True)
    assert result.returncode == 1


@pytest.mark.skipif(not _docker_image_exists("veripy-dafny"), reason="docker or veripy-dafny image not available")
def test_cli_dafny_verifies_abs(tmp_path):
    src = tmp_path / "abs.py"
    src.write_text(ABS_SOURCE)
    result = subprocess.run(["uv", "run", "python", "-m", "veripy", str(src)])
    assert result.returncode == 0
