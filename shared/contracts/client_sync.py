from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel

from .cloud import SegmentMetadata


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        rendered = value.isoformat()
        return rendered.replace("+00:00", "Z")
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def encode_segment_metadata(metadata: SegmentMetadata) -> str:
    return base64.urlsafe_b64encode(canonical_json_bytes(metadata)).rstrip(b"=").decode("ascii")


def decode_segment_metadata(value: str) -> SegmentMetadata:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        decoded = json.loads(raw)
    except (UnicodeEncodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("invalid X-Segment-Metadata header") from exc
    return SegmentMetadata.model_validate(decoded)
