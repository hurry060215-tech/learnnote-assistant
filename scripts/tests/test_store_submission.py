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
    def test_chrome_waits_for_upload_success_before_staged_submission(self):
        module = load_module()
        values = {'access_token':'fixture', 'publisher_id':'publisher', 'item_id':'item'}
        pending = mock.Mock(ok=True, status_code=200, headers={})
        pending.json.return_value = {'uploadState':'IN_PROGRESS'}
        ready = mock.Mock(ok=True)
        ready.json.return_value = {'lastAsyncUploadState':'SUCCEEDED'}
        published = mock.Mock(ok=True, status_code=200, headers={})
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / 'extension.zip'
            package.write_bytes(b'fixture')
            with mock.patch.object(module.requests, 'post', side_effect=[pending, published]) as post, mock.patch.object(module.requests, 'get', return_value=ready) as get, mock.patch.object(module.time, 'sleep'):
                result = module.submit('chrome', package, values, publish=True, edge_notes='')
            self.assertEqual(result['status'], 'submitted')
            get.assert_called_once()
            self.assertEqual(json.loads(post.call_args.kwargs['data'])['publishType'], 'STAGED_PUBLISH')

    def test_http_success_with_failed_upload_never_submits(self):
        module = load_module()
        response = mock.Mock(ok=True, status_code=200, headers={})
        response.json.return_value = {'uploadState':'FAILED'}
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / 'extension.zip'
            package.write_bytes(b'fixture')
            with mock.patch.object(module.requests, 'post', return_value=response) as post:
                result = module.submit('chrome', package, {'access_token':'fixture','publisher_id':'p','item_id':'i'}, publish=True, edge_notes='')
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(post.call_count, 1)

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
