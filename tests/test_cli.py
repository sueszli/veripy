import subprocess
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_cli_writes_dfy_file(tmp_path):
    src = tmp_path / "f.py"
    src.write_text("def f(x: int) -> int:\n    return x\n")
    subprocess.run(["uv", "run", "veripy", "--dfy", str(src)], capture_output=True, check=True)


def test_cli_dfy_content_matches_expected(tmp_path):
    src = tmp_path / "f.py"
    src.write_text("def f(x: int) -> int:\n    return x\n")
    r = subprocess.run(["uv", "run", "veripy", "--dfy", str(src)], capture_output=True, text=True, check=True)
    assert "method f(x: int) returns (r: int)" in r.stdout
    assert "r := x;" in r.stdout


def test_cli_nonexistent_file_exits_with_error():
    r = subprocess.run(["uv", "run", "veripy", "--dfy", "nonexistent.py"], capture_output=True)
    assert r.returncode != 0
