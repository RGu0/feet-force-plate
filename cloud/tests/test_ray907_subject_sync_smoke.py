"""RAY-907 subject sync smoke script replayed against the in-process API."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from cloud.tests import test_subject_sync_api as subject_sync
from scripts import run_ray907_subject_sync_smoke as smoke


class _BridgedClient:
    """Sync smoke calls forwarded to the in-process app.

    The in-memory data repository has no RAY-728 D3 projections, so activation
    and revocation are mirrored into its terminal rows as the RAY-907 tests do.
    Every secret and synthetic identity the smoke sends or receives is kept so
    the test can require that none of it reaches the evidence.
    """

    def __init__(self, test: SubjectSyncSmokeTest, loop: asyncio.AbstractEventLoop) -> None:
        self._test = test
        self._loop = loop
        test.secrets_seen = []

    def call(self, method, path, *, token=None, body=None, headers=None, content=None):
        if path == "/health/ready":
            return 200, {"status": "ready"}
        merged = dict(headers or {})
        if token is not None:
            merged["Authorization"] = f"Bearer {token}"
        response = asyncio.run_coroutine_threadsafe(
            self._test.client.request(method, path, json=body, content=content, headers=merged),
            self._loop,
        ).result()
        payload = response.json()
        data = self._test.data
        tenant = self._test.tenant_id
        if response.status_code == 201 and path == "/v1/access/terminal-activate":
            data.add_terminal(tenant, None, UUID(payload["data"]["client_installation_id"]))
            self._test.secrets_seen += [
                payload["data"]["access_token"], payload["data"]["refresh_token"],
                payload["data"]["tenant_id"],
            ]
        elif path == "/v1/subjects" and method == "POST":
            self._test.secrets_seen += [
                body["external_identifier"]["external_id"],
                body["identity_profile"]["display_name"],
            ]
        elif response.status_code == 200 and path.endswith("/revoke") and "/terminals/" in path:
            data.set_terminal_status(tenant, UUID(path.split("/")[-2]), "REVOKED")
        return response.status_code, payload


class SubjectSyncSmokeTest(unittest.IsolatedAsyncioTestCase):
    activate = subject_sync.SubjectSyncApiTests.activate
    provision = subject_sync.SubjectSyncApiTests.provision
    create_subject = subject_sync.SubjectSyncApiTests.create_subject
    headers = staticmethod(subject_sync.SubjectSyncApiTests.headers)

    async def asyncSetUp(self) -> None:
        await subject_sync.SubjectSyncApiTests.asyncSetUp(self)

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def _run(self) -> dict:
        loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory:
            ca_file = Path(directory, "ca.pem")
            ca_file.write_text("not used by the bridged client\n")
            args = argparse.Namespace(
                base_url="https://cloud.test", ca_file=str(ca_file),
                account_name=self.account_name,
            )
            with patch.object(smoke, "Client", lambda *_: _BridgedClient(self, loop)):
                return await asyncio.to_thread(smoke.run, args, subject_sync.PASSWORD)

    async def smoke_terminal_statuses(self) -> list[str]:
        listing = await self.client.get(
            "/v1/access/terminals", headers=self.headers(self.terminal)
        )
        return [
            t["status"] for t in listing.json()["data"]["terminals"]
            if t["terminal_name"].startswith("ray907-smoke-")
        ]

    def assert_redacted(self, summary: dict) -> None:
        rendered = json.dumps(summary, ensure_ascii=False)
        self.assertTrue(self.secrets_seen)
        for secret in (subject_sync.PASSWORD, self.account_name, *self.secrets_seen):
            self.assertNotIn(secret, rendered)

    async def test_full_flow_passes_and_redacts(self) -> None:
        summary = await self._run()

        self.assertEqual(summary["result"], "passed", summary.get("failed_step"))
        self.assertEqual(
            [step["step"] for step in summary["steps"]],
            [
                "readiness", "terminal_activate", "subject_create", "subject_download",
                "subject_patch", "subject_patch_replay", "subject_patch_key_reused",
                "subject_patch_stale_revision", "subject_search_by_name",
                "tag_create", "tag_create_name_conflict", "subject_patch_tags",
                "tag_download", "subject_archive", "cleanup_terminal_self_revoke",
                "subject_download_after_revoke",
            ],
        )
        steps = {step["step"]: step for step in summary["steps"]}
        download = steps["subject_download"]
        self.assertEqual(
            (download["found"], download["revisions_ascending"], download["next_cursor_returned"]),
            (True, True, True),
        )
        self.assertGreater(steps["subject_patch"]["revision"], download["revision"])
        self.assertTrue(steps["subject_patch_replay"]["identical"])
        self.assertEqual(steps["subject_patch_key_reused"]["error_code"], "E-API-409")
        stale = steps["subject_patch_stale_revision"]
        self.assertEqual(stale["error_code"], "E-SUB-409-REVISION-CONFLICT")
        self.assertEqual(stale["current_revision"], steps["subject_patch"]["revision"])
        self.assertTrue(steps["subject_search_by_name"]["found"])
        self.assertEqual(steps["tag_create"]["status"], 201)
        conflict = steps["tag_create_name_conflict"]
        self.assertEqual((conflict["status"], conflict["conflict"]), (200, True))
        self.assertEqual(conflict["tag_id"], steps["tag_create"]["tag_id"])
        self.assertEqual(steps["subject_patch_tags"]["tag_ids"], [steps["tag_create"]["tag_id"]])
        self.assertTrue(steps["tag_download"]["found"])
        self.assertEqual(steps["subject_archive"]["subject_status"], "ARCHIVED")
        self.assertEqual(steps["cleanup_terminal_self_revoke"]["terminal_status"], "REVOKED")
        self.assertEqual(
            steps["subject_download_after_revoke"]["error_code"], "E-TRM-401-REVOKED"
        )
        self.assert_redacted(summary)
        self.assertEqual(await self.smoke_terminal_statuses(), ["REVOKED"])

    async def test_download_pages_with_the_cursor(self) -> None:
        for index in range(3):
            await self.create_subject(number=f"GAIT-{index:03d}")

        with patch.object(smoke, "SUBJECT_PAGE_MAX_LIMIT", 1):
            summary = await self._run()

        self.assertEqual(summary["result"], "passed", summary.get("failed_step"))
        steps = {step["step"]: step for step in summary["steps"]}
        self.assertEqual(steps["subject_download"]["pages"], 4)
        self.assertGreaterEqual(steps["tag_download"]["pages"], 1)
        self.assertEqual(
            [step["step"] for step in summary["steps"]].count("subject_download"), 1
        )

    async def test_out_of_order_download_fails(self) -> None:
        await self.create_subject(number="GAIT-001")

        def reversed_download(call):
            def wrapped(self, method, path, **kwargs):
                status, payload = call(self, method, path, **kwargs)
                if method == "GET" and path.startswith("/v1/subjects?"):
                    payload["data"]["items"].reverse()
                return status, payload

            return wrapped

        with patch.object(_BridgedClient, "call", reversed_download(_BridgedClient.call)):
            summary = await self._run()

        self.assertEqual(summary["failed_step"], "subject_download")
        steps = {step["step"]: step for step in summary["steps"]}
        self.assertFalse(steps["subject_download"]["revisions_ascending"])
        self.assertTrue(steps["cleanup_terminal_self_revoke"]["passed"])
        self.assertEqual(await self.smoke_terminal_statuses(), ["REVOKED"])

    async def test_missing_name_match_fails_and_still_releases_seat(self) -> None:
        def empty_search(call):
            def wrapped(self, method, path, **kwargs):
                if path == "/v1/subjects/search-by-name":
                    return 200, {"data": {"items": []}}
                return call(self, method, path, **kwargs)

            return wrapped

        with patch.object(_BridgedClient, "call", empty_search(_BridgedClient.call)):
            summary = await self._run()

        self.assertEqual(summary["failed_step"], "subject_search_by_name")
        steps = {step["step"]: step for step in summary["steps"]}
        self.assertFalse(steps["subject_search_by_name"]["found"])
        self.assertTrue(steps["cleanup_terminal_self_revoke"]["passed"])
        self.assert_redacted(summary)
        self.assertEqual(await self.smoke_terminal_statuses(), ["REVOKED"])

    async def test_conflict_without_current_record_fails(self) -> None:
        def bare_conflict(call):
            def wrapped(self, method, path, **kwargs):
                status, payload = call(self, method, path, **kwargs)
                if payload.get("error", {}).get("code") == "E-SUB-409-REVISION-CONFLICT":
                    payload["error"].pop("details", None)
                return status, payload

            return wrapped

        with patch.object(_BridgedClient, "call", bare_conflict(_BridgedClient.call)):
            summary = await self._run()

        self.assertEqual(summary["failed_step"], "subject_patch_stale_revision")
        steps = {step["step"]: step for step in summary["steps"]}
        self.assertFalse(steps["subject_patch_stale_revision"]["current_valid"])

    async def test_transport_error_is_recorded_and_cleans_up(self) -> None:
        def broken_tags(call):
            def wrapped(self, method, path, **kwargs):
                if path == "/v1/subject-tags":
                    raise ConnectionResetError("peer reset")
                return call(self, method, path, **kwargs)

            return wrapped

        with patch.object(_BridgedClient, "call", broken_tags(_BridgedClient.call)):
            summary = await self._run()

        self.assertEqual(summary["failed_step"], "transport:ConnectionResetError")
        self.assertEqual(summary["steps"][-1]["step"], "cleanup_terminal_self_revoke")
        self.assertEqual(await self.smoke_terminal_statuses(), ["REVOKED"])

    async def test_unexpected_exception_still_releases_seat(self) -> None:
        def broken_patch(call):
            def wrapped(self, method, path, **kwargs):
                if method == "PATCH":
                    raise KeyError("unexpected")
                return call(self, method, path, **kwargs)

            return wrapped

        with patch.object(_BridgedClient, "call", broken_patch(_BridgedClient.call)):
            with self.assertRaises(KeyError):
                await self._run()
        self.assertEqual(await self.smoke_terminal_statuses(), ["REVOKED"])


class RedactionGuardTest(unittest.TestCase):
    def test_a_leaked_value_drops_every_step(self) -> None:
        summary = {
            "schema_version": smoke.SCHEMA_VERSION, "started_at": "s", "finished_at": "f",
            "endpoint": "https://cloud.test", "script_commit": "c", "result": "passed",
            "secrets_included": False,
            "steps": [{"step": "subject_create", "echo": "RAY907 Smoke 0123"}],
        }

        self.assertIs(smoke._redacted(summary, ["", "absent"]), summary)
        guarded = smoke._redacted(summary, ["RAY907 Smoke 0123"])
        self.assertEqual(
            (guarded["result"], guarded["failed_step"], guarded["steps"]),
            ("failed", "redaction_check", []),
        )
        self.assertNotIn("RAY907 Smoke 0123", json.dumps(guarded))
