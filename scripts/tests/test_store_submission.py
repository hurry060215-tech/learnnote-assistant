from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "store-submit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("store_submit", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load store submission helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StoreSubmissionTests(unittest.TestCase):
    def test_preflight_never_calls_network_when_credentials_are_missing(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "extension.zip"
            output = Path(temporary) / "report.json"
            package.write_bytes(b"safe fixture")
            previous = {name: os.environ.pop(name, None) for name in (
                "LEARNNOTE_CHROME_ACCESS_TOKEN",
                "LEARNNOTE_CHROME_PUBLISHER_ID",
                "LEARNNOTE_CHROME_ITEM_ID",
            )}
            try:
                with mock.patch.object(module.requests, "post", side_effect=AssertionError("network called")):
                    previous_argv = sys.argv
                    sys.argv = [str(SCRIPT), "--provider", "chrome", "--package", str(package), "--output", str(output)]
                    try:
                        self.assertEqual(module.main(), 0)
                    finally:
                        sys.argv = previous_argv
                report = json.loads(output.read_text(encoding="utf-8"))
            finally:
                for name, value in previous.items():
                    if value is not None:
                        os.environ[name] = value
            self.assertEqual(report["status"], "ready")
            self.assertFalse(report["network_called"])
            self.assertEqual(sorted(report["missing_credentials"]), ["access_token", "item_id", "publisher_id"])


if __name__ == "__main__":
    unittest.main()
