#!/usr/bin/env python3
"""Export every OSS object into a backup staging directory (RAY-405).

Walks the deployment's OSS bucket with the same credentials and settings the
service uses, downloads each object to ``--output-dir`` under its object key,
and appends ``sha256`` manifest lines to ``--manifest`` so the encrypted
backup bundle keeps covering objects after the storage backend moved off the
local disk.  No identifier is printed; secrets never leave the environment.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from cloud.api.seed import SeedSettings  # noqa: E402
from cloud.ingestion.aliyun_oss import build_aliyun_oss_sdk  # noqa: E402


def _iter_object_keys(client: object, sdk: object, bucket: str):
    continuation = None
    while True:
        result = client.list_objects_v2(
            sdk.ListObjectsV2Request(
                bucket=bucket,
                max_keys=1000,
                continuation_token=continuation,
            )
        )
        for item in result.contents or []:
            yield item.key
        if not result.is_truncated:
            return
        continuation = result.next_continuation_token


def export_bucket_objects(client: object, sdk: object, bucket: str,
                          output_dir: Path, manifest_path: Path) -> int:
    count = 0
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for key in _iter_object_keys(client, sdk, bucket):
            target = output_dir / key
            if (
                not key
                or key.startswith(("/", "\\"))
                or ".." in Path(key).parts
                or "\\" in key
            ):
                raise RuntimeError(f"object key escapes staging root: {key!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.parent.chmod(0o700)
            body = client.get_object(sdk.GetObjectRequest(bucket=bucket, key=key))
            digest = hashlib.sha256()
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            descriptor = os.open(target, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                for chunk in iter(lambda: body.read(1024 * 1024), b""):
                    handle.write(chunk)
                    digest.update(chunk)
            manifest.write(f"{digest.hexdigest()}  {key}\n")
            count += 1
    return count


def export_objects(output_dir: Path, manifest_path: Path) -> int:
    settings = SeedSettings.from_env()
    if settings.object_backend != "aliyun-oss":
        raise RuntimeError("oss backup export requires the aliyun-oss backend")
    client, sdk = build_aliyun_oss_sdk(settings)
    return export_bucket_objects(client, sdk, settings.oss_bucket,
                                 output_dir, manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args()
    count = export_objects(arguments.output_dir, arguments.manifest)
    print(f"oss_backup_objects_exported={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
