from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRIMARY = (
    "docs/产品需求文档_PRD.md",
    "docs/架构设计文档.md",
    "docs/数据库设计文档.md",
    "docs/通信接口设计文档.md",
)
MODULES = (
    "docs/modules/05-sync-upload.md",
    "docs/modules/06-cloud-ingestion.md",
    "docs/modules/10-device-management.md",
    "docs/modules/11-observability-support.md",
    "cloud/api/README.md",
)


def _text(paths: tuple[str, ...]) -> str:
    return "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)


def test_authoritative_docs_encode_the_approved_seed_access_model() -> None:
    combined = _text(PRIMARY)
    for token in (
        "tenant account", "license/2", "hardware binding", "client installation",
        "PLATFORM_OWNER", "PLATFORM_OPERATIONS", "PLATFORM_SUPPORT", "PLATFORM_ENGINEER",
        "SensitiveAccessGrant", "15-minute access token", "30-day idle",
        "180-day absolute", "6/12-month License", "24-hour offline grace",
        "1 -> 3 -> 2", "provider-provisioned",
    ):
        assert token in combined


def test_module_docs_distinguish_current_seed_and_legacy_terminal_compatibility() -> None:
    combined = _text(MODULES)
    for token in (
        "tenant access token", "feetforceplate-tenant", "feetforceplate-platform",
        "upload and report access continue", "private filesystem object store",
        "domain + public CA + 443", "legacy terminal compatibility",
    ):
        assert token in combined


def test_current_seed_sections_contain_no_rejected_onboarding_or_security_claims() -> None:
    module10 = (ROOT / "docs/modules/10-device-management.md").read_text(encoding="utf-8")
    seed_sections = "\n".join(
        text.split("## Seed MVP access model", 1)[-1]
        for text in (_text(PRIMARY), _text(MODULES))
    )
    assert "机构管理员生成一次性激活码" not in module10
    assert "customer searches or creates tenants" not in seed_sections
    assert "exactly one institution admin" not in seed_sections
    assert "License belongs to terminal_id" not in seed_sections
    assert "Platform role has BYPASSRLS" not in seed_sections
    assert "IP:7443 is production" not in seed_sections
