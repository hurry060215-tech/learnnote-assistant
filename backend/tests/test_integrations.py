from __future__ import annotations

import unittest

from app.integrations import integration_manifest


class IntegrationManifestTests(unittest.TestCase):
    def test_manifest_is_versioned_and_privacy_explicit(self) -> None:
        manifest = integration_manifest()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertIn("sanitized_bundle", manifest["exports"])
        self.assertFalse(manifest["privacy"]["official_cloud"])
        self.assertIn("media_adapter_contract_version", manifest)


if __name__ == "__main__":
    unittest.main()
