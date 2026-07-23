"""Archive selected immutable DP-P4864 known-weight captures with verification."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
from shutil import copy2


ARCHIVE_NAME = "2026-07-22-known-weight-calibration"
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "tmp/hardware/force-calibration/20260722"
RECORDS = REPO_ROOT / "docs/evidence/linear/RAY-117"

CAPTURES = {
    "raw/group-a-original-contact/baseline": [
        "range-3p5-to-7/baseline/dop4864-parser-capture-20260723T014248Z.bin",
    ],
    "raw/group-a-original-contact/loads/3500g": [
        "range-3p5-to-7/3500g/dop4864-parser-capture-20260723T014406Z.bin",
    ],
    "raw/group-a-original-contact/loads/4500g": [
        "range-3p5-to-7/4500g/dop4864-parser-capture-20260723T014524Z.bin",
    ],
    "raw/group-a-original-contact/loads/5500g": [
        "range-3p5-to-7/5500g/dop4864-parser-capture-20260723T014614Z.bin",
    ],
    "raw/group-a-original-contact/loads/6500g": [
        "range-3p5-to-7/6500g/dop4864-parser-capture-20260723T014716Z.bin",
    ],
    "raw/group-a-original-contact/loads/7500g": [
        "range-3p5-to-7p5/7500g/dop4864-parser-capture-20260723T014808Z.bin",
    ],
    "raw/group-a-original-contact/loads/8000g": [
        "range-3p5-to-8/8000g-repeat/dop4864-parser-capture-20260723T015039Z.bin",
    ],
    "raw/group-b-small-contact/baseline": [
        "small-contact/baseline/dop4864-parser-capture-20260723T021406Z.bin",
    ],
    "raw/group-b-small-contact/loads/4500g": [
        "small-contact/4500g/dop4864-parser-capture-20260723T021517Z.bin",
    ],
    "raw/group-b-small-contact/loads/5500g": [
        "small-contact/5500g/dop4864-parser-capture-20260723T021615Z.bin",
    ],
    "raw/group-b-small-contact/loads/6000g": [
        "small-contact/6000g/dop4864-parser-capture-20260723T021653Z.bin",
    ],
    "raw/group-b-small-contact/loads/6500g": [
        "small-contact/6500g/dop4864-parser-capture-20260723T021800Z.bin",
    ],
    "raw/group-b-small-contact/loads/7500g": [
        "small-contact/7500g/dop4864-parser-capture-20260723T021920Z.bin",
    ],
    "raw/group-b-small-contact/loads/8000g": [
        "small-contact/8000g/dop4864-parser-capture-20260723T022001Z.bin",
    ],
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def archive(destination_parent: Path) -> Path:
    destination = destination_parent / ARCHIVE_NAME
    for relative_destination, relative_sources in CAPTURES.items():
        target_directory = destination / relative_destination
        target_directory.mkdir(parents=True, exist_ok=True)
        for relative_source in relative_sources:
            source = SOURCE_ROOT / relative_source
            target = target_directory / source.name
            if not source.is_file():
                raise FileNotFoundError(source)
            copy2(source, target)
            if digest(source) != digest(target):
                raise RuntimeError(f"SHA-256 verification failed for {target}")
    records = destination / "records"
    records.mkdir(parents=True, exist_ok=True)
    copy2(RECORDS / "known-weight-calibration-test-record-2026-07-22.md", records)
    copy2(RECORDS / "known-weight-calibration-sha256-2026-07-22.txt", records)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination_parent", type=Path)
    args = parser.parse_args()
    print(archive(args.destination_parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
