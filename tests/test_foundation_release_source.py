from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import tarfile

import pytest

from scripts import foundation_release_source as source


def _project(root: Path, *, version: str = "0.9.4") -> Path:
    root.mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["techflex-cloud-foundation[server]==' + version + '"]\n'
        '[tool.uv.sources]\ntechflex-cloud-foundation = {url = '
        '"https://github.com/RGu0/techflex-cloud-foundation/releases/download/v'
        + version + '/techflex_cloud_foundation-' + version + '-py3-none-any.whl"}\n'
    )
    return root


def _archive(name: str = "techflex_cloud_foundation-0.9.4/tests/test_probe.py", *, link=False, executable=False) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        item = tarfile.TarInfo(name)
        payload = b"assert True\n"
        item.mode = 0o755 if executable else 0o644
        if link:
            item.type, item.linkname = tarfile.SYMTYPE, "/tmp/escaped"
        else:
            item.size = len(payload)
        archive.addfile(item, None if link else io.BytesIO(payload))
    return data.getvalue()


def _download(monkeypatch, payload: bytes) -> list[str]:
    calls = []
    monkeypatch.setattr(source, "SOURCE_SHA256", hashlib.sha256(payload).hexdigest())

    def open_url(url, **kwargs):
        calls.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr(source.urllib.request, "urlopen", open_url)
    monkeypatch.delenv("UV_OFFLINE", raising=False)
    return calls


def test_lookup_and_offline_ensure_never_download_when_missing(tmp_path, monkeypatch):
    root = _project(tmp_path)
    calls = _download(monkeypatch, _archive())
    with pytest.raises(RuntimeError, match="missing"):
        source.foundation_source_root(root)
    with pytest.raises(RuntimeError, match="missing"):
        source.ensure_foundation_source(root, offline=True)
    monkeypatch.setenv("UV_OFFLINE", "1")
    with pytest.raises(RuntimeError, match="missing"):
        source.ensure_foundation_source(root)
    assert calls == []
    assert not (root / ".foundation-source").exists()


def test_ensure_then_offline_lookup_verifies_content_and_does_not_fetch_again(tmp_path, monkeypatch):
    root = _project(tmp_path)
    calls = _download(monkeypatch, _archive())
    extracted = source.ensure_foundation_source(root)
    assert (extracted / "tests/test_probe.py").read_bytes() == b"assert True\n"
    assert source.foundation_source_root(root) == extracted
    assert source.ensure_foundation_source(root, offline=True) == extracted
    assert calls == [source.SOURCE_URL]


@pytest.mark.parametrize("target", ["archive", "extracted"])
def test_cache_tamper_is_rejected_without_repair_or_network(tmp_path, monkeypatch, target):
    root = _project(tmp_path)
    calls = _download(monkeypatch, _archive())
    extracted = source.ensure_foundation_source(root)
    path = next((root / ".foundation-source").rglob("*.tar.gz")) if target == "archive" else extracted / "tests/test_probe.py"
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="integrity|digest"):
        source.foundation_source_root(root)
    with pytest.raises(RuntimeError, match="integrity|digest"):
        source.ensure_foundation_source(root)
    assert path.read_bytes() == b"tampered"
    assert len(calls) == 1


@pytest.mark.parametrize("name,link", [
    ("../escaped", False), ("/tmp/escaped", False),
    ("techflex_cloud_foundation-0.9.4/../escaped", False),
    ("techflex_cloud_foundation-0.9.4/link", True),
])
def test_digest_valid_unsafe_archives_cannot_publish_cache(tmp_path, monkeypatch, name, link):
    root = _project(tmp_path)
    _download(monkeypatch, _archive(name, link=link))
    with pytest.raises(RuntimeError, match="unsafe"):
        source.ensure_foundation_source(root)
    assert list((root / ".foundation-source").iterdir()) == []
    assert not (root / "escaped").exists()


def test_download_digest_mismatch_never_publishes(tmp_path, monkeypatch):
    root = _project(tmp_path)
    _download(monkeypatch, _archive())
    monkeypatch.setattr(source, "SOURCE_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="digest"):
        source.ensure_foundation_source(root)
    assert list((root / ".foundation-source").iterdir()) == []


def test_consumer_version_mismatch_fails_before_download(tmp_path, monkeypatch):
    calls = _download(monkeypatch, _archive())
    with pytest.raises(RuntimeError, match="pin"):
        source.ensure_foundation_source(_project(tmp_path, version="0.9.3"))
    assert calls == []


def test_existing_different_cache_data_is_preserved(tmp_path, monkeypatch):
    root = _project(tmp_path)
    calls = _download(monkeypatch, _archive())
    identity = root / ".foundation-source" / f"{source.SOURCE_VERSION}-{source.SOURCE_SHA256}"
    identity.mkdir(parents=True)
    sentinel = identity / "operator-note"
    sentinel.write_text("preserve")
    with pytest.raises(RuntimeError, match="integrity"):
        source.ensure_foundation_source(root)
    assert sentinel.read_text() == "preserve"
    assert calls == []


def test_extra_extracted_file_is_not_trusted(tmp_path, monkeypatch):
    root = _project(tmp_path)
    _download(monkeypatch, _archive())
    extracted = source.ensure_foundation_source(root)
    directory = extracted / "tests"
    directory.chmod(0o755)
    (directory / "injected.py").write_text("raise AssertionError")
    with pytest.raises(RuntimeError, match="integrity"):
        source.foundation_source_root(root)


def test_consumer_source_url_mismatch_fails_before_download(tmp_path, monkeypatch):
    root = _project(tmp_path)
    calls = _download(monkeypatch, _archive())
    project = root / "pyproject.toml"
    project.write_text(project.read_text().replace("github.com/RGu0/", "github.com/other/"))
    with pytest.raises(RuntimeError, match="pin"):
        source.ensure_foundation_source(root)
    assert calls == []


def test_verified_archive_preserves_executable_script_semantics(tmp_path, monkeypatch):
    root = _project(tmp_path)
    _download(monkeypatch, _archive(executable=True))
    extracted = source.ensure_foundation_source(root)
    script = extracted / "tests/test_probe.py"
    assert script.read_bytes() == b"assert True\n"
    if os.name != "nt":
        assert os.access(script, os.X_OK)
        assert script.stat().st_mode & 0o777 == 0o555
    assert source.foundation_source_root(root) == extracted


@pytest.mark.skipif(os.name == "nt", reason="Windows chmod does not enforce POSIX execute bits")
@pytest.mark.parametrize("executable,tampered_mode", [(True, 0o444), (False, 0o555)])
def test_executable_mode_tamper_is_rejected_without_changing_contents(
    tmp_path, monkeypatch, executable, tampered_mode,
):
    root = _project(tmp_path)
    calls = _download(monkeypatch, _archive(executable=executable))
    extracted = source.ensure_foundation_source(root)
    script = extracted / "tests/test_probe.py"
    script.chmod(tampered_mode)
    assert script.read_bytes() == b"assert True\n"
    with pytest.raises(RuntimeError, match="mode integrity"):
        source.foundation_source_root(root)
    with pytest.raises(RuntimeError, match="mode integrity"):
        source.ensure_foundation_source(root)
    assert len(calls) == 1
