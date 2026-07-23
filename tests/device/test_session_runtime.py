import tempfile
from pathlib import Path
import json
import unittest
from unittest.mock import patch

import numpy as np

from client.device.acquisition import ConnectionStateMachine, LatestFrameMailbox
from client.device.protocol import DaoOneP4864Parser, ProtocolProfile
from client.device.session_runtime import (
    HardwareSessionRuntime,
    QualityDecision,
    SessionValidity,
)
from client.device.simulator import SyntheticP4864Transport
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineReference
from client.hardware_standardization.quality import DoP4864HardwareQualityGate
from client.spool.session_commit import ValidSessionStager
from client.spool.derived_artifact import read_derived_observation
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.device.simulator import FaultKind, FaultPlan


class Key:
    def get_key(self) -> bytes:
        return b"r" * 32


def _ready() -> ConnectionStateMachine:
    connection = ConnectionStateMachine()
    connection.start_connecting()
    connection.mark_ready()
    return connection


def _profile() -> ProtocolProfile:
    return ProtocolProfile.synthetic(
        version="runtime-test/1", length_byte_order="little", checksum_start=0, checksum_end=3077
    )


class SessionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(Key()))
        self.store.put_subject_ref("subject", b"opaque")
        self.data_root = root / "data"

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _runtime(
        self, *, decision: QualityDecision | None = None, quality_gate: object | None = None
    ) -> HardwareSessionRuntime:
        ticks = iter(range(1_000_000, 2_000_000))
        stager = ValidSessionStager(
            self.data_root,
            session_id="s1",
            key_provider=Key(),
            store=self.store,
            subject_uuid="subject",
            consent_id=None,
            versions={"protocol": "test/1", "quality": "test/1"},
            started_at_ns=1,
        )
        return HardwareSessionRuntime(
            transport=SyntheticP4864Transport(
                _profile(), realtime=False, max_frames=2,
                frame_source=lambda i: np.full((48, 64), i + 1, dtype=np.uint8),
            ),
            parser=DaoOneP4864Parser(
                _profile(), allow_unverified=True,
                monotonic_ns=lambda: next(ticks), wall_time_ns=lambda: 2,
            ),
            connection=_ready(),
            mailbox=LatestFrameMailbox(),
            stager=stager,
            quality_gate=(
                quality_gate
                or type(
                    "Gate", (), {"evaluate": lambda _, *, session_id, frames: decision}
                )()
            ),
            wall_time_ns=lambda: 10,
        )

    def test_quality_acceptance_commits_only_after_capture_finishes(self) -> None:
        result = self._runtime(decision=QualityDecision(SessionValidity.VALID)).capture(
            session_id="s1", target_frames=2
        )
        self.assertTrue(result.committed)
        self.assertEqual(self.store.session_status("s1"), ("CLOSED", "VALID", 10))

    def test_quality_rejection_discards_temporary_capture(self) -> None:
        result = self._runtime(
            decision=QualityDecision(SessionValidity.INVALID, "BAD_POINT_CLUSTER")
        ).capture(session_id="s1", target_frames=2)
        self.assertFalse(result.committed)
        self.assertEqual(result.reason, "BAD_POINT_CLUSTER")
        self.assertFalse((self.data_root / ".staging" / "s1").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("s1")

    def test_finalization_failure_discards_staging_and_never_creates_a_session(self) -> None:
        ticks = iter(range(1_000_000, 2_000_000))
        stager = ValidSessionStager(
            self.data_root,
            session_id="finalization-failure",
            key_provider=Key(),
            store=self.store,
            subject_uuid="subject",
            consent_id=None,
            versions={"protocol": "test/1", "quality": "test/1"},
            started_at_ns=1,
        )
        runtime = HardwareSessionRuntime(
            transport=SyntheticP4864Transport(
                _profile(), realtime=False, max_frames=2,
                frame_source=lambda i: np.full((48, 64), i + 1, dtype=np.uint8),
            ),
            parser=DaoOneP4864Parser(
                _profile(), allow_unverified=True,
                monotonic_ns=lambda: next(ticks), wall_time_ns=lambda: 2,
            ),
            connection=_ready(),
            mailbox=LatestFrameMailbox(),
            stager=stager,
            quality_gate=type(
                "Gate", (), {"evaluate": lambda _, *, session_id, frames: QualityDecision(SessionValidity.VALID)}
            )(),
            wall_time_ns=lambda: 10,
        )
        with patch.object(stager, "commit_valid", side_effect=OSError("disk full")):
            result = runtime.capture(session_id="finalization-failure", target_frames=2)

        self.assertFalse(result.committed)
        self.assertEqual(result.validity, SessionValidity.INVALID)
        self.assertIn("finalization failed", result.reason or "")
        self.assertFalse((self.data_root / ".staging" / "finalization-failure").exists())
        with self.assertRaises(KeyError):
            self.store.session_status("finalization-failure")

    def test_runtime_commits_raw_and_encrypted_v1_force_data_after_quality_gate(self) -> None:
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
        runtime = self._runtime(
            quality_gate=DoP4864HardwareQualityGate(baseline_reference=baseline)
        )

        result = runtime.capture(session_id="s1", target_frames=2)

        self.assertTrue(result.committed)
        artifacts = self.store.session_artifacts("s1")
        self.assertEqual(len(artifacts), 1)
        self.assertTrue((self.data_root / artifacts[0].relative_path).exists())
        manifest = json.loads(
            (self.data_root / "sessions" / "s1" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["versions"]["protocol_profile"], "runtime-test/1")
        self.assertEqual(
            manifest["versions"]["bad_point_policy"], "quality-policy/do-p4864-mvp/1"
        )
        self.assertEqual(
            manifest["versions"]["force_calibration_profile"],
            "do-p4864-voltage-force/mvp-screening-v1-20260722",
        )
        self.assertEqual(
            manifest["versions"]["maximum_no_valid_signal_ns"], "5000000000"
        )
        self.assertEqual(
            manifest["versions"]["reconstruction_policy"],
            "interpolate-adjacent-valid-frames/1",
        )

    def test_short_wire_fault_remains_absent_from_raw_segments_but_is_audited_in_derived_data(self) -> None:
        adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
        baseline = BaselineReference(
            schema_version="baseline-reference/1",
            baseline_window_id="baseline-1",
            layout_digest=adapter.layout.digest,
            zero_offset_count=(0.0,) * (48 * 64),
            noise_mad_count=(0.0,) * (48 * 64),
            rules_version="do-p4864-unloaded-baseline/1",
            threshold_version="do-p4864-quality/1",
            source_digest="b" * 64,
        )
        stager = ValidSessionStager(
            self.data_root,
            session_id="fault-tolerant",
            key_provider=Key(),
            store=self.store,
            subject_uuid="subject",
            consent_id=None,
            versions={"protocol": "runtime-test/1", "quality": "test/1"},
            started_at_ns=1,
        )
        runtime = HardwareSessionRuntime(
            transport=SyntheticP4864Transport(
                _profile(),
                realtime=False,
                max_frames=4,
                fault_plan=FaultPlan(events={1: (FaultKind.BAD_TAIL,)}),
                frame_source=lambda index: np.full(
                    (48, 64), 10 + index * 10, dtype=np.uint8
                ),
            ),
            parser=DaoOneP4864Parser(_profile(), allow_unverified=True),
            connection=_ready(),
            mailbox=LatestFrameMailbox(),
            stager=stager,
            quality_gate=DoP4864HardwareQualityGate(baseline_reference=baseline),
            wall_time_ns=lambda: 10,
        )

        result = runtime.capture(session_id="fault-tolerant", target_frames=3)

        self.assertTrue(result.committed)
        self.assertEqual(result.acquisition.frames_stored, 3)
        self.assertEqual(len(result.acquisition.reconstructed_frames), 1)
        manifest = json.loads(
            (self.data_root / "sessions" / "fault-tolerant" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["total_frames"], 3)
        artifact = self.store.session_artifacts("fault-tolerant")[0]
        derived = read_derived_observation(
            self.data_root / artifact.relative_path, key_provider=Key()
        )
        self.assertEqual(len(derived["frames"]), 4)
        self.assertTrue(
            any(
                "RECONSTRUCTED_FROM_NEIGHBORS" in frame["quality_flags"]
                for frame in derived["frames"]
            )
        )
        integrity = derived["hardware_processing"]["communication_integrity"]
        self.assertEqual(integrity["reconstructed_frame_count"], 1)
        self.assertEqual(integrity["events"][0]["failure_kind"], "TAIL")
