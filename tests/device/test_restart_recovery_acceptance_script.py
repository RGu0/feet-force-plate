from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import SensitiveBlobCodec, StateStore
from scripts import run_dop4864_runtime_acceptance as runtime_acceptance
from tests.spool.test_segments import _frame


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_dop4864_restart_recovery_acceptance.py"


def _load_script_module():
    spec = spec_from_file_location("restart_recovery_acceptance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RestartRecoveryAcceptanceScriptTests(unittest.TestCase):
    def test_key_provider_persists_a_complete_key_after_short_write(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as temporary:
            key_file = Path(temporary) / "acceptance.aes256"
            short_writing_os = SimpleNamespace(
                O_CREAT=os.O_CREAT,
                O_EXCL=os.O_EXCL,
                O_WRONLY=os.O_WRONLY,
                close=os.close,
                fsync=os.fsync,
                open=os.open,
                urandom=os.urandom,
                write=lambda descriptor, data: os.write(descriptor, data[:7]),
            )

            with patch.object(
                runtime_acceptance, "os", short_writing_os
            ):
                created_key = module.FileAesKeyProvider(key_file).get_key()

            self.assertEqual(
                module.FileAesKeyProvider(key_file).get_key(), created_key
            )

    def test_recovery_summary_discards_interrupted_staging_without_formal_session(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file())
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key_file = root / "acceptance.aes256"
            key_provider = module.FileAesKeyProvider(key_file)
            store = StateStore(root / "state.sqlite3", SensitiveBlobCodec(key_provider))
            store.put_subject_ref("hardware-acceptance-no-subject", b"local-only")
            stager = ValidSessionStager(
                root / "spool",
                session_id="interrupted",
                key_provider=key_provider,
                store=store,
                subject_uuid="hardware-acceptance-no-subject",
                consent_id=None,
                versions={"protocol": "observed-compact/1"},
                started_at_ns=1,
            )
            stager.append(_frame(0))
            stager.append(_frame(101))
            self.assertTrue(stager.staging_directory.exists())
            store.close()

            summary = module.recover_after_interruption(root, key_file)

            self.assertEqual(summary["recovery"]["interrupted_staging_discarded"], 1)
            self.assertEqual(summary["formal_storage"], {
                "sessions": 0,
                "segments": 0,
                "artifacts": 0,
            })
            self.assertFalse(stager.staging_directory.exists())


if __name__ == "__main__":
    unittest.main()
