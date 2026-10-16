from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_acceptance", ROOT / "scripts/native-platform-acceptance.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativePlatformAcceptanceTests(unittest.TestCase):
    def test_isolated_environment_drops_provider_and_user_data_paths(self):
        with patch.dict(os.environ, {"LEARNNOTE_DATA_DIR": "/private", "OPENAI_API_KEY": "synthetic-secret", "LLM_API_KEY": "synthetic-secret", "LEARNNOTE_MODEL_CACHE": "/private/models"}):
            env = MODULE.isolated_environment(Path("/tmp/synthetic"), 12345)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("LLM_API_KEY", env)
        self.assertNotIn("LEARNNOTE_MODEL_CACHE", env)
        self.assertEqual(env["LEARNNOTE_DATA_DIR"], "/tmp/synthetic")
        self.assertEqual(env["LEARNNOTE_BACKEND_ORIGIN"], "http://127.0.0.1:12345")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")

    def test_http_does_not_follow_redirects_or_use_proxy_credentials(self):
        api = MODULE.Api(12345)
        self.assertFalse(api.session.trust_env)
        with patch.object(api.session, "request") as request:
            request.return_value.status_code = 200
            api.call("GET", "/health")
            self.assertFalse(request.call_args.kwargs["allow_redirects"])
            self.assertEqual(request.call_args.args[1], "http://127.0.0.1:12345/health")
        with self.assertRaises(ValueError):
            api.call("GET", "https://example.com")
        api.session.close()

    def test_unsigned_workflow_cannot_publish_or_access_signing_secrets(self):
        text = (ROOT / ".github/workflows/native-platform-acceptance.yml").read_text()
        workflow = yaml.safe_load(text)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", text)
        self.assertNotIn("gh release", text)
        self.assertNotIn("--clobber", text)
        job = workflow["jobs"]["native-core"]
        self.assertEqual(set(job["strategy"]["matrix"]["os"]), {"ubuntu-latest", "macos-latest"})
        self.assertNotIn("continue-on-error", text)
        self.assertIn("--app dist/LearnNote.app", text)
        self.assertIn("if: always()", text)

    def test_macos_bundle_collects_dependencies_for_excluded_binary_layout(self):
        spec = (ROOT / "LearnNote.macos.spec").read_text()
        self.assertIn("exclude_binaries=True", spec)
        self.assertIn("collection = COLLECT(", spec)
        self.assertIn("exe, a.binaries, a.datas", spec)
        self.assertIn("BUNDLE(\n    collection,", spec)

    def test_backup_annotation_uses_grouped_export_schema(self):
        backup = {"personal": {"annotations": [{"key": "material-fixture", "items": [{"text": MODULE.PERSONAL}]}]}}
        MODULE.assert_backup_annotation(backup, "fixture")
        backup["personal"]["annotations"][0]["items"][0]["text"] = "wrong"
        with self.assertRaises(AssertionError):
            MODULE.assert_backup_annotation(backup, "fixture")

    def test_failure_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.argv", ["native", "--output", directory]), patch.object(MODULE, "exercise", side_effect=RuntimeError("fixture failure")):
                with self.assertRaises(RuntimeError):
                    MODULE.main()
            import json
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertIn("fixture failure", report["error"])


if __name__ == "__main__":
    unittest.main()
