from __future__ import annotations

import hashlib
import json
from base64 import b64decode
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_MATERIALS = PROJECT_ROOT / "client" / "cloud" / "public_materials"


def test_project_keeps_the_approved_license_verification_public_key_with_provenance() -> None:
    key_file = PUBLIC_MATERIALS / "license-public.key.base64"
    metadata_file = PUBLIC_MATERIALS / "license-public.key.json"

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

    assert key_file.is_file()
    public_key = b64decode(
        key_file.read_text(encoding="ascii").strip(), validate=True
    )
    assert len(public_key) == 32
    assert hashlib.sha256(public_key).hexdigest() == metadata["sha256"]
    assert metadata == {
        "artifact": "license-verification-public-key",
        "encoding": "base64",
        "key_type": "Ed25519",
        "purpose": "License verification only; not an approval-signature trust anchor",
        "sha256": "40b50ea2f5ac5287c8716652722d6b8129f6a342888ce6f554953cc879abe0d7",
        "source": "RAY-321 historical public integration delivery",
    }
