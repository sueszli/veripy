from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from veripy.ingestor import ingest
from veripy.printer import print_dafny


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()

    src_path: Path = args.file.resolve()
    if not src_path.exists():
        print(f"error: {src_path} does not exist", file=sys.stderr)
        sys.exit(1)

    source = src_path.read_text()
    module = ingest(source)
    dfy = print_dafny(module)

    dfy_path = src_path.with_suffix(".dfy")
    dfy_path.write_text(dfy + "\n")

    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{dfy_path.parent}:/work", "-w", "/work", "veripy-dafny", "dafny", "verify", dfy_path.name],
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
