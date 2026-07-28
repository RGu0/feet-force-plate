from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


def _runner_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_dop4864_runtime_acceptance.py"
    spec = importlib.util.spec_from_file_location("runtime_acceptance_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeAcceptanceScriptTests(unittest.TestCase):
    def test_main_writes_external_sanitized_summary_when_acceptance_raises(self) -> None:
        module = _runner_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "evidence" / "failure.json"
            arguments = [
                "run_dop4864_runtime_acceptance.py",
                "--device",
                "/dev/test-serial",
                "--output-root",
                str(root / "full-volume"),
                "--summary-output",
                str(summary),
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch.object(module, "run_acceptance", side_effect=OSError("No space left on device")),
            ):
                self.assertEqual(module.main(), 2)

            payload = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(payload["runtime"]["validity"], "INVALID")
            self.assertEqual(payload["runtime"]["reason"], "acceptance runner failed: OSError")
            self.assertNotIn("No space left on device", json.dumps(payload))
