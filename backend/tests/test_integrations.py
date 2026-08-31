from __future__ import annotations

import unittest
import json

from app.integrations import integration_manifest, notion_export_payload
from app.models import TaskRecord


class IntegrationManifestTests(unittest.TestCase):
    def test_manifest_is_versioned_and_privacy_explicit(self) -> None:
        manifest = integration_manifest()
        self.assertEqual(manifest["schema_version"], 2)
        self.assertIn("sanitized_bundle", manifest["exports"])
        self.assertIn("word", manifest["exports"])
        self.assertIn("pdf", manifest["exports"])
        self.assertIn("events_stream", manifest["exports"])
        self.assertIn("note_document", manifest["exports"])
        self.assertIn("study_dashboard", manifest["local_services"])
        self.assertFalse(manifest["privacy"]["official_cloud"])
        self.assertIn("media_adapter_contract_version", manifest)

    def test_notion_export_is_local_payload_only(self) -> None:
        task = TaskRecord(
            id="abc123def456", source_type="local", mode="local", title="本地课程",
            created_at="2026-08-21T00:00:00+00:00", updated_at="2026-08-21T00:00:00+00:00",
        )
        payload = notion_export_payload(task, "# 标题\n- 要点一")
        self.assertEqual(payload["integration"], "notion")
        self.assertFalse(payload["privacy"]["network_request_performed"])
        self.assertEqual(payload["children"][0]["type"], "heading_1")

    def test_notion_export_redacts_secrets_and_signed_urls(self) -> None:
        task = TaskRecord(
            id="safe-export", source_type="local", mode="local", title="Authorization: Bearer TITLESECRET",
            created_at="2026-08-21T00:00:00+00:00", updated_at="2026-08-21T00:00:00+00:00",
        )
        payload = notion_export_payload(
            task,
            "# 笔记\nCookie: sid=COOKIESECRET; csrf=SECONDSECRET\n"
            "https://cdn.example.com/a?X-Amz-Signature=URLSECRET&v=1",
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        for secret in ("TITLESECRET", "COOKIESECRET", "SECONDSECRET", "URLSECRET"):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
