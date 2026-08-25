from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.record_foundation_release_baseline import (
    assert_performance_budget,
    build_release_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_release_evidence_records_locked_components_artifacts_and_reused_transport(
    tmp_path: Path,
) -> None:
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text(
        '''version = 1

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "cryptography"
version = "49.0.0"
source = { registry = "https://pypi.org/simple" }
''',
        encoding="utf-8",
    )
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "techflex_cloud_foundation-0.1.0-py3-none-any.whl").write_bytes(
        b"wheel"
    )

    evidence = build_release_evidence(
        package_name="techflex-cloud-foundation",
        package_version="0.1.0",
        source_revision="a" * 40,
        lockfile=lockfile,
        dist_dir=dist_dir,
        operations=4,
    )

    assert evidence["sbom"]["bomFormat"] == "CycloneDX"
    assert evidence["source"]["revision"] == "a" * 40
    assert evidence["artifacts"][0]["sha256"] == (
        "ba59926159d2aa256eb8739b8da7e2b574b960e1202c6d624cbe981cef996c91"
    )
    assert evidence["sbom"]["components"] == [
        {"name": "cryptography", "type": "library", "version": "49.0.0"},
        {"name": "httpx", "type": "library", "version": "0.28.1"},
    ]
    assert evidence["performance"]["operations"] == 4
    assert evidence["performance"]["transport_instances"] == 1
    json.dumps(evidence)


def test_release_evidence_compares_against_the_versioned_pre_extraction_workload(
    tmp_path: Path,
) -> None:
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text("version = 1\n", encoding="utf-8")
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "foundation.whl").write_bytes(b"wheel")

    evidence = build_release_evidence(
        package_name="techflex-cloud-foundation",
        package_version="0.1.1",
        source_revision="b" * 40,
        lockfile=lockfile,
        dist_dir=dist_dir,
        operations=4,
    )

    assert evidence["performance_baseline"]["source_revision"] == (
        "6e76234f0ec466f4fa62f6368ea646ec8b37979e"
    )
    assert evidence["performance_baseline"]["workload"] == "legacy-httpx-client/1"
    assert evidence["performance_baseline"]["performance"]["operations"] == 4


def test_release_workflow_enforces_the_pre_extraction_performance_comparison() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "--baseline-strategy legacy-httpx-client/1" in workflow


def test_performance_budget_rejects_regressions_beyond_agreed_limits() -> None:
    baseline = {"p95_operation_seconds": 1.0, "peak_memory_bytes": 100}

    assert_performance_budget(
        {"p95_operation_seconds": 1.05, "peak_memory_bytes": 110}, baseline
    )

    with pytest.raises(ValueError, match="P95"):
        assert_performance_budget(
            {"p95_operation_seconds": 1.051, "peak_memory_bytes": 110}, baseline
        )
    with pytest.raises(ValueError, match="memory"):
        assert_performance_budget(
            {"p95_operation_seconds": 1.05, "peak_memory_bytes": 111}, baseline
        )


def test_release_workflow_uses_the_supported_noninteractive_pip_audit_option() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "uv export --locked --extra dev --no-emit-workspace" in workflow
    assert "pip-audit --strict -r audited-requirements.txt --progress-spinner off" in workflow
    assert "--no-progress-spinner" not in workflow


def test_foundation_package_allows_the_audited_cryptography_fix_release() -> None:
    package_project = (
        PROJECT_ROOT / "packages/techflex-cloud-foundation/pyproject.toml"
    ).read_text(encoding="utf-8")

    assert 'version = "0.1.1"' in package_project
    assert '"cryptography>=42,<51"' in package_project
