from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.checksum import sha256_file


def write_checksum(file_path: Path, output_path: Path | None = None) -> Path:
    target = file_path.resolve()
    if not target.is_file():
        raise FileNotFoundError(target)

    output = output_path or Path(f"{target}.sha256")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{sha256_file(target)} *{target.name}\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a release SHA-256 manifest.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = write_checksum(args.file, args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
