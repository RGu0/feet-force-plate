"""Open a disposable RAY-89 single-session deletion acceptance window."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from client.app.qt_shell import ScreeningWindow
from client.app.session_deletion import CompletedSessionDeletionService
from client.device.protocol import RawFrame
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore


class _KeyProvider:
    def get_key(self) -> bytes:
        return b"r" * 32


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="feetforceplate-ray89-delete-") as directory:
        root = Path(directory)
        keys = _KeyProvider()
        store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(keys))
        try:
            store.put_subject_ref("acceptance-subject", b"opaque")
            stager = ValidSessionStager(
                root / "data",
                session_id="ray89-ui-acceptance",
                key_provider=keys,
                store=store,
                subject_uuid="acceptance-subject",
                consent_id=None,
                versions={"acceptance": "ray89-ui/1"},
                started_at_ns=1,
            )
            values = np.zeros((48, 64), dtype=np.uint8)
            values.setflags(write=False)
            stager.append(
                RawFrame(
                    values=values,
                    host_monotonic_ns=1,
                    host_wall_time_ns=1,
                    source_index=1,
                    device_frame_seq=None,
                    device_timestamp_ns=None,
                    quality_flags=frozenset(),
                )
            )
            stager.commit_valid(ended_at_ns=2)
            app = QApplication.instance() or QApplication([])
            window = ScreeningWindow()
            window.show()
            window.show_session_deletion(
                CompletedSessionDeletionService(root=root / "data", store=store)
            )
            return app.exec()
        finally:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
