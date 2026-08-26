#!/usr/bin/env python3
"""Verify the private foundation wheel used by the governed FeetForcePlate runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "foundation-artifact.lock.json"
CACHE_DIRECTORY = PROJECT_ROOT / ".foundation-artifacts"
REPOSITORY = "RGu0/techflex-cloud-foundation"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_lock() -> dict[str, str]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    required = {"package", "release", "version", "wheel", "sha256"}
    if set(lock) != required or any(not isinstance(value, str) for value in lock.values()):
        raise ValueError("foundation artifact lock has an invalid schema")
    return lock


def ensure_artifact(*, download: bool) -> Path:
    lock = _load_lock()
    artifact = CACHE_DIRECTORY / lock["wheel"]
    if artifact.is_file() and _sha256(artifact) == lock["sha256"]:
        return artifact
    if not download:
        raise RuntimeError(
            "locked foundation artifact is absent or has a mismatched checksum; "
            "run ./dev setup while authenticated to the private repository"
        )
    gh = shutil.which("gh")
    if gh is None:
        raise RuntimeError("GitHub CLI is required to download the private foundation artifact")
    CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            gh,
            "release",
            "download",
            lock["release"],
            "--repo",
            REPOSITORY,
            "--pattern",
            lock["wheel"],
            "--dir",
            str(CACHE_DIRECTORY),
            "--clobber",
        ],
        check=True,
    )
    if not artifact.is_file() or _sha256(artifact) != lock["sha256"]:
        raise RuntimeError("downloaded foundation artifact failed SHA-256 verification")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    arguments = parser.parse_args()
    print(ensure_artifact(download=arguments.download))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
