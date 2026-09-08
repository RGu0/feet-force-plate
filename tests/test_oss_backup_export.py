from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "deploy" / "aliyun" / "seed"))

from oss_backup_export import export_bucket_objects  # noqa: E402


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:  # noqa: ARG002
        value, self._payload = self._payload[:size], self._payload[size:]
        return value


class _Bucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects
        self._pages: list[list[str]] = []
        keys = sorted(objects)
        while keys:
            self._pages.append(keys[:2])
            keys = keys[2:]

    def list_objects_v2(self, request: SimpleNamespace) -> SimpleNamespace:
        token = getattr(request, "continuation_token", None)
        index = 0 if token is None else int(token)
        page = self._pages[index]
        more = index + 1 < len(self._pages)
        return SimpleNamespace(
            contents=[SimpleNamespace(key=key) for key in page],
            is_truncated=more,
            next_continuation_token=str(index + 1) if more else None,
        )

    def get_object(self, request: SimpleNamespace) -> _Body:
        return _Body(self._objects[request.key])


class _Sdk:
    class ListObjectsV2Request(SimpleNamespace):
        pass

    class GetObjectRequest(SimpleNamespace):
        pass


def test_export_walks_pages_writes_files_and_manifest(tmp_path: Path) -> None:
    objects = {
        "tenants/t1/sessions/s1/segments/0-abc.ffps": b"segment-bytes",
        "tenants/t1/sessions/s1/manifests/def.json": b"manifest-bytes",
        "tenants/t2/sessions/s2/segments/0-ghi.ffps": b"more-bytes",
    }
    bucket = _Bucket(objects)
    manifest = tmp_path / "object-manifest.sha256"
    manifest.write_text("", encoding="utf-8")

    count = export_bucket_objects(bucket, _Sdk, "the-bucket",
                                  tmp_path / "objects", manifest)

    assert count == 3
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        digest, _, key = line.partition("  ")
        stored = (tmp_path / "objects" / key).read_bytes()
        assert stored == objects[key]
        assert digest == hashlib.sha256(objects[key]).hexdigest()
    mode = (tmp_path / "objects" / "tenants" / "t1" / "sessions" / "s1"
            / "segments").stat().st_mode & 0o777
    assert mode == 0o700
    file_mode = (tmp_path / "objects" / "tenants" / "t1" / "sessions" / "s1"
                 / "segments" / "0-abc.ffps").stat().st_mode & 0o777
    assert file_mode == 0o600
