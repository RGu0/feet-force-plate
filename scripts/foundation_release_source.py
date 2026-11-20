"""Digest-pinned foundation source for consumer tests; lookup never uses the network."""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import tomllib
import urllib.request

SOURCE_VERSION = "0.9.5"
SOURCE_SHA256 = "b75fca4d0501cb21e09c70b860e71530b5dfb8f0235b750da17c61645ec46a6b"
_RELEASE = "https://github.com/RGu0/techflex-cloud-foundation/releases/download/"
SOURCE_URL = f"{_RELEASE}v{SOURCE_VERSION}/techflex_cloud_foundation-{SOURCE_VERSION}.tar.gz"
_TOP = f"techflex_cloud_foundation-{SOURCE_VERSION}"


def _cache(project_root: Path | None) -> Path:
    root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pin = rf"techflex-cloud-foundation(?:\[[A-Za-z0-9_,. -]+\])?=={re.escape(SOURCE_VERSION)}"
    dependencies = project["project"]["dependencies"]
    url = project.get("tool", {}).get("uv", {}).get("sources", {}).get("techflex-cloud-foundation", {}).get("url")
    wheel = f"{_RELEASE}v{SOURCE_VERSION}/techflex_cloud_foundation-{SOURCE_VERSION}-py3-none-any.whl"
    if sum(bool(re.fullmatch(pin, item.strip())) for item in dependencies) != 1 or url != wheel:
        raise RuntimeError("consumer foundation pin/source URL must match approved source version")
    parent = root / ".foundation-source"
    if parent.is_symlink():
        raise RuntimeError("unsafe foundation source cache symlink")
    return parent / f"{SOURCE_VERSION}-{SOURCE_SHA256}"


def _contents(archive: Path) -> tuple[dict[Path, bytes | None], set[Path]]:
    if archive.is_symlink() or not archive.is_file():
        raise RuntimeError("foundation archive integrity failure")
    payload = archive.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("foundation source archive digest mismatch")
    contents: dict[Path, bytes | None] = {}
    executable: set[Path] = set()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
        for member in bundle:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or "\\" in member.name
                    or not name.parts or name.parts[0] != _TOP
                    or not (member.isdir() or member.isfile())):
                raise RuntimeError("unsafe foundation source archive member")
            path = Path(*name.parts)
            if path in contents:
                raise RuntimeError("unsafe duplicate foundation source archive member")
            stream = bundle.extractfile(member) if member.isfile() else None
            contents[path] = stream.read() if stream is not None else None
            if member.isfile() and member.mode & 0o111:
                executable.add(path)
    if not any(value is not None for value in contents.values()):
        raise RuntimeError("foundation source archive integrity failure: no files")
    return contents, executable


def _verify(cache: Path) -> Path:
    if cache.is_symlink() or not cache.is_dir():
        raise RuntimeError("foundation source cache missing; run setup/ensure first")
    if {p.name for p in cache.iterdir()} != {"archive.tar.gz", "source"}:
        raise RuntimeError("foundation source cache integrity failure")
    contents, executable = _contents(cache / "archive.tar.gz")
    tree = cache / "source"
    if tree.is_symlink() or not tree.is_dir():
        raise RuntimeError("foundation source tree integrity failure")
    expected_files = {p for p, value in contents.items() if value is not None}
    expected_dirs = {p for p, value in contents.items() if value is None}
    for path in contents:
        expected_dirs.update(p for p in path.parents if p != Path("."))
    actual_files, actual_dirs = set(), set()
    for path in tree.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("foundation source tree integrity failure: symlink")
        relative = path.relative_to(tree)
        if path.is_dir():
            actual_dirs.add(relative)
        elif path.is_file():
            actual_files.add(relative)
            if relative not in expected_files or path.read_bytes() != contents[relative]:
                raise RuntimeError("foundation extracted file integrity failure")
            expected_exec = 0o111 if relative in executable else 0
            if os.name != "nt" and path.stat().st_mode & 0o111 != expected_exec:
                raise RuntimeError("foundation extracted executable mode integrity failure")
        else:
            raise RuntimeError("foundation source tree integrity failure: special file")
    if actual_files != expected_files or actual_dirs != expected_dirs:
        raise RuntimeError("foundation source tree integrity failure: missing/extra entries")
    return tree / _TOP


def foundation_source_root(project_root: Path | None = None) -> Path:
    """Read and verify an existing cache. Never download, repair or write files."""
    return _verify(_cache(project_root))


def ensure_foundation_source(project_root: Path | None = None, offline: bool = False) -> Path:
    """Explicit setup operation; missing offline caches and tampered caches fail closed."""
    cache = _cache(project_root)
    if cache.exists() or cache.is_symlink():
        return _verify(cache)
    if offline or os.environ.get("UV_OFFLINE", "").lower() not in {"", "0", "false"}:
        raise RuntimeError("foundation source cache missing in offline mode")
    cache.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".source-", dir=cache.parent))
    try:
        archive = stage / "archive.tar.gz"
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
            if not getattr(response, "geturl", lambda: SOURCE_URL)().startswith("https://"):
                raise RuntimeError("foundation source download requires HTTPS")
            with archive.open("xb") as output:
                shutil.copyfileobj(response, output)
        contents, executable = _contents(archive)
        tree = stage / "source"
        tree.mkdir()
        for relative, value in contents.items():
            path = tree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if value is None:
                path.mkdir(exist_ok=True)
            else:
                path.write_bytes(value)
        for path in sorted(stage.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            is_executable = path.is_relative_to(tree) and path.relative_to(tree) in executable
            path.chmod(0o555 if path.is_dir() or is_executable else 0o444)
        stage.chmod(0o555)
        _verify(stage)
        # An existing identity is never overwritten (including a concurrent setup).
        if cache.exists() or cache.is_symlink():
            return _verify(cache)
        stage.rename(cache)
        return _verify(cache)
    finally:
        if stage.exists():
            stage.chmod(0o755)
            for path in stage.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
            shutil.rmtree(stage, onerror=_remove_readonly)


def _remove_readonly(function, path, _error) -> None:
    os.chmod(path, 0o755)
    function(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--print-root", action="store_true")
    args = parser.parse_args()
    root = ensure_foundation_source(offline=args.offline)
    if args.print_root:
        print(root)


if __name__ == "__main__":
    main()
