import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from client.device.protocol import RawFrame
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineReference
from client.hardware_standardization.quality import DoP4864HardwareQualityGate
from client.spool.derived_artifact import read_derived_observation
from client.spool import session_commit
from client.spool.session_commit import ValidSessionStager, delete_completed_valid_session
from client.spool.state_store import SensitiveBlobCodec, StateStore
from shared.contracts.client_sync import FormalUploadEnvelope
from shared.contracts.cloud import (
    ConsentCreateRequest,
    SessionVersions,
    SubjectCreateRequest,
    TestProtocol as UploadTestProtocol,
)


class StaticKeyProvider:
    def get_key(self) -> bytes:
        return b"v" * 32


def _frame(index: int) -> RawFrame:
    values = np.full((48, 64), index, dtype=np.uint8)
    values.setflags(write=False)
    return RawFrame(
        values=values,
        host_monotonic_ns=index * 50_000_000,
        host_wall_time_ns=1_000_000_000 + index * 50_000_000,
        source_index=index,
        device_frame_seq=None,
        device_timestamp_ns=None,
        quality_flags=frozenset(),
    )


def _formal_upload_envelope(
    *, session_id, subject_id, consent_id
) -> FormalUploadEnvelope:
    return FormalUploadEnvelope(
        session_id=session_id,
        subject=SubjectCreateRequest(subject_uuid=subject_id),
        consent=ConsentCreateRequest(
            consent_record_id=consent_id,
            subject_uuid=subject_id,
            policy_version="consent/1",
            purpose_codes=("SCREENING",),
            data_categories=("SCREENING",),
            granted_at=datetime(2026, 8, 11, tzinfo=UTC),
            evidence_type="OPERATOR_CONFIRMED",
            terminal_signature="test-signature-value",
        ),
        client_installation_id=uuid4(),
        hardware_asset_id=uuid4(),
        site_id=None,
        test_protocol=UploadTestProtocol(id="standard-screening", version="1.0"),
        versions=SessionVersions(
            app="0.1.0",
            protocol_profile="do-p4864/1",
            payload_schema="raw-segment/1",
            calibration="calibration/1",
        ),
        config_snapshot={"quality_gate_id": "static-basic-quality"},
        started_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


class ValidSessionStagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.keys = StaticKeyProvider()
        self.store = StateStore(
            self.root / "state.sqlite3", SensitiveBlobCodec(self.keys)
        )
        self.store.put_subject_ref("subject-1", b"opaque")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _stager(self, session_id: str) -> ValidSessionStager:
        return ValidSessionStager(
            self.root / "data",
            session_id=session_id,
            key_provider=self.keys,
            store=self.store,
            subject_uuid="subject-1",
            consent_id=None,
            versions={"protocol": "observed-compact/1", "quality": "mvp/1"},
            started_at_ns=1_000_000_000,
        )

    def test_invalid_capture_discards_all_temporary_raw_data_and_creates_no_session(self) -> None:
        stager = self._stager("invalid")
        stager.append(_frame(0))
        stager.discard(reason="PARSER_RESYNC")

        self.assertFalse((self.root / "data" / ".staging" / "invalid").exists())
        self.assertFalse((self.root / "data" / "sessions" / "invalid").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("invalid")

    def test_valid_capture_is_promoted_then_registered_with_ready_network_handoff(self) -> None:
        stager = self._stager("valid")
        stager.append(_frame(0))
        committed = stager.commit_valid(ended_at_ns=1_100_000_000)

        self.assertFalse((self.root / "data" / ".staging" / "valid").exists())
        self.assertTrue((self.root / "data" / "sessions" / "valid" / "manifest.json").exists())
        self.assertEqual(self.store.session_status("valid"), ("CLOSED", "VALID", 1_100_000_000))
        self.assertEqual(committed.total_frames, 1)
        self.assertEqual(self.store.sync_handoff_state("valid"), "READY_FOR_NETWORK")

    def test_interrupted_staging_is_deleted_on_startup_recovery(self) -> None:
        stager = self._stager("interrupted")
        for index in range(101):
            stager.append(_frame(index))

        removed = ValidSessionStager.discard_interrupted_staging(self.root / "data")

        self.assertEqual(removed, 1)
        self.assertFalse((self.root / "data" / ".staging" / "interrupted").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("interrupted")

    def test_recovery_finishes_registration_after_promotion_before_sqlite_commit(self) -> None:
        stager = self._stager("post-promotion-crash")
        stager.append(_frame(10))
        original = self.store.commit_valid_session

        def simulated_power_loss(*args, **kwargs):
            raise SystemExit("simulated process loss")

        self.store.commit_valid_session = simulated_power_loss  # type: ignore[method-assign]
        try:
            with self.assertRaises(SystemExit):
                stager.commit_valid(ended_at_ns=1_100_000_000)
        finally:
            self.store.commit_valid_session = original  # type: ignore[method-assign]

        final = self.root / "data" / "sessions" / "post-promotion-crash"
        self.assertTrue((final / "registration.json").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("post-promotion-crash")

        recovered = ValidSessionStager.recover_promoted_sessions(
            self.root / "data", self.store, self.keys
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(
            self.store.session_status("post-promotion-crash"),
            ("CLOSED", "VALID", 1_100_000_000),
        )
        self.assertFalse((final / "registration.json").exists())

    def test_recovery_restores_the_same_formal_upload_envelope(self) -> None:
        session_id = uuid4()
        subject_id = uuid4()
        consent_id = uuid4()
        envelope = _formal_upload_envelope(
            session_id=session_id,
            subject_id=subject_id,
            consent_id=consent_id,
        )
        self.store.put_subject_ref(str(subject_id), b"opaque")
        self.store.put_consent_record(
            str(consent_id), str(subject_id), b"operator-confirmed", recorded_at_ns=1
        )
        stager = ValidSessionStager(
            self.root / "data",
            session_id=str(session_id),
            key_provider=self.keys,
            store=self.store,
            subject_uuid=str(subject_id),
            consent_id=str(consent_id),
            versions={"protocol": "observed-compact/1", "quality": "mvp/1"},
            started_at_ns=1_000_000_000,
            upload_envelope=envelope,
        )
        stager.append(_frame(10))
        original = self.store.commit_valid_session

        def simulated_power_loss(*args, **kwargs):
            raise SystemExit("simulated process loss")

        self.store.commit_valid_session = simulated_power_loss  # type: ignore[method-assign]
        try:
            with self.assertRaises(SystemExit):
                stager.commit_valid(ended_at_ns=1_100_000_000)
        finally:
            self.store.commit_valid_session = original  # type: ignore[method-assign]

        recovered = ValidSessionStager.recover_promoted_sessions(
            self.root / "data", self.store, self.keys
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(
            self.store.sync_handoff_envelope(str(session_id)), envelope
        )

    def test_valid_session_retains_an_encrypted_repaired_force_observation(self) -> None:
        stager = self._stager("derived")
        frames = tuple(_frame(index + 10) for index in range(2))
        for frame in frames:
            stager.append(frame)
        adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
        baseline = BaselineReference(
            schema_version="baseline-reference/1",
            baseline_window_id="baseline-1",
            layout_digest=adapter.layout.digest,
            zero_offset_count=(0.0,) * (48 * 64),
            noise_mad_count=(0.0,) * (48 * 64),
            rules_version="do-p4864-unloaded-baseline/1",
            threshold_version="do-p4864-quality/1",
            source_digest="a" * 64,
        )
        quality = DoP4864HardwareQualityGate(baseline_reference=baseline).evaluate(
            session_id="derived", frames=stager.staged_frames()
        )
        self.assertEqual(quality.validity.value, "VALID")
        assert quality.physical_session is not None
        stager.stage_derived_observation(
            quality.physical_session,
            processing_metadata=quality.processing_metadata,
        )
        stager.commit_valid(ended_at_ns=1_100_000_000)

        artifacts = self.store.session_artifacts("derived")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].kind, "HARDWARE_DERIVED_OBSERVATION")
        restored = read_derived_observation(
            self.root / "data" / artifacts[0].relative_path, key_provider=self.keys
        )
        self.assertEqual(restored["schema_version"], "hardware-derived-observation/1")
        self.assertEqual(restored["session_id"], "derived")
        processing = restored["hardware_processing"]
        assert isinstance(processing, dict)
        self.assertEqual(processing["bad_point_policy_version"], "quality-policy/do-p4864-mvp/3")
        first = restored["frames"][0]
        assert isinstance(first, dict)
        self.assertIsNotNone(first["estimated_force_n"])
        self.assertNotIn("raw_count", first)

    def test_committed_derived_observation_reopens_as_public_physical_session(
        self,
    ) -> None:
        stager = self._stager("local-analysis-source")
        frames = tuple(_frame(index + 10) for index in range(2))
        for frame in frames:
            stager.append(frame)
        adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
        baseline = BaselineReference(
            schema_version="baseline-reference/1",
            baseline_window_id="baseline-public-reopen",
            layout_digest=adapter.layout.digest,
            zero_offset_count=(0.0,) * (48 * 64),
            noise_mad_count=(0.0,) * (48 * 64),
            rules_version="do-p4864-unloaded-baseline/1",
            threshold_version="do-p4864-quality/1",
            source_digest="b" * 64,
        )
        quality = DoP4864HardwareQualityGate(baseline_reference=baseline).evaluate(
            session_id="local-analysis-source",
            frames=stager.staged_frames(),
        )
        self.assertEqual(quality.validity.value, "VALID")
        assert quality.physical_session is not None
        stager.stage_derived_observation(
            quality.physical_session,
            processing_metadata=quality.processing_metadata,
        )
        stager.commit_valid(ended_at_ns=1_100_000_000)

        reopened = session_commit.read_committed_physical_session(
            self.root / "data",
            session_id="local-analysis-source",
            store=self.store,
            key_provider=self.keys,
        )

        payload = reopened.to_dict()
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "session_id",
                "coordinate_frame",
                "coordinate_unit",
                "force_unit",
                "time_unit",
                "points",
                "frames",
            },
        )
        self.assertEqual(payload["schema_version"], "estimated-force-session/1.0")
        self.assertEqual(payload["session_id"], "local-analysis-source")
        self.assertEqual(len(payload["points"]), 48 * 64)
        self.assertEqual(len(payload["frames"]), 2)
        serialized = json.dumps(payload, sort_keys=True)
        for private_field in (
            "raw_count",
            "relative_load_count",
            "repaired_count",
            "quality_flags",
            "source_index",
            "hardware_processing",
        ):
            self.assertNotIn(private_field, serialized)

    def test_cloud_confirmation_retains_data_until_one_manual_session_delete(self) -> None:
        stager = self._stager("manual-delete")
        stager.append(_frame(10))
        stager.commit_valid(ended_at_ns=1_100_000_000)
        self.store.mark_cloud_confirmed("manual-delete", confirmed_at_ns=1_200_000_000)

        snapshot = self.store.valid_local_storage_snapshot()
        self.assertEqual(snapshot.valid_session_count, 1)
        self.assertGreater(snapshot.stored_bytes, 0)
        self.assertEqual(snapshot.pending_handoff_count, 0)
        self.assertEqual(snapshot.last_cloud_confirmed_at_ns, 1_200_000_000)
        self.assertTrue((self.root / "data" / "sessions" / "manual-delete").exists())
        self.assertEqual(self.store.completed_valid_session_ids(), ("manual-delete",))

        delete_completed_valid_session(
            self.root / "data", session_id="manual-delete", store=self.store
        )

        self.assertFalse((self.root / "data" / "sessions" / "manual-delete").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("manual-delete")
        self.assertEqual(self.store.valid_local_storage_snapshot().valid_session_count, 0)
        self.assertEqual(self.store.completed_valid_session_ids(), ())


if __name__ == "__main__":
    unittest.main()
