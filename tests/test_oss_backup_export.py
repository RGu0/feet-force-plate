from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "deploy" / "aliyun" / "seed"))

from oss_backup_export import export_bucket_objects  # noqa: E402


class _Stream:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        value, self._payload = self._payload[:size], self._payload[size:]
        return value


class _Bucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects
        self.requested_keys: list[str] = []

    def get_object(self, request: SimpleNamespace) -> SimpleNamespace:
        self.requested_keys.append(request.key)
        return SimpleNamespace(body=_Stream(self._objects[request.key]))


class _Sdk:
    class GetObjectRequest(SimpleNamespace):
        pass


def test_export_fetches_referenced_keys_and_records_digests(tmp_path: Path) -> None:
    objects = {
        "tenants/t1/sessions/s1/segments/0-abc.ffps": b"segment-bytes",
        "tenants/t1/sessions/s1/manifests/def.json": b"manifest-bytes",
        "tenants/t2/sessions/s2/segments/0-ghi.ffps": b"more-bytes",
    }
    bucket = _Bucket(objects)
    manifest = tmp_path / "object-manifest.sha256"
    manifest.write_text("", encoding="utf-8")

    count = export_bucket_objects(bucket, _Sdk, "the-bucket", sorted(objects),
                                  tmp_path / "objects", manifest)

    assert count == 3
    assert bucket.requested_keys == sorted(objects)
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        digest, _, key = line.partition("  ")
        stored = (tmp_path / "objects" / key).read_bytes()
        assert stored == objects[key]
        assert digest == hashlib.sha256(objects[key]).hexdigest()
    deepest = tmp_path / "objects" / "tenants" / "t1" / "sessions" / "s1" / "segments"
    assert deepest.stat().st_mode & 0o777 == 0o700
    file_mode = (deepest / "0-abc.ffps").stat().st_mode & 0o777
    assert file_mode == 0o600


def test_export_rejects_keys_that_escape_the_staging_root(tmp_path: Path) -> None:
    import pytest

    bucket = _Bucket({})
    manifest = tmp_path / "object-manifest.sha256"
    manifest.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError):
        export_bucket_objects(bucket, _Sdk, "the-bucket",
                              ["../outside/evil.ffps"], tmp_path / "objects", manifest)
