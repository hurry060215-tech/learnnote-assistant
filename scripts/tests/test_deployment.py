from __future__ import annotations

import subprocess
import sys
import os
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DeploymentContractTests(unittest.TestCase):
    def test_container_runs_as_non_root_with_persistent_data_and_healthcheck(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("USER learnnote", dockerfile)
        self.assertIn('VOLUME ["/app/data"]', dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("LEARNNOTE_DEPLOYMENT_MODE=server", dockerfile)
        self.assertIn("learnnote-data:/app/data", compose)
        self.assertIn("LEARNNOTE_PUBLIC_PASSWORD", compose)
        self.assertIn("restart: unless-stopped", compose)

    def test_public_mode_refuses_short_or_missing_password(self) -> None:
        code = "import app.config"
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "backend"),
            "LEARNNOTE_DEPLOYMENT_MODE": "server",
            "LEARNNOTE_PUBLIC_PASSWORD": "short",
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least 12 characters", result.stderr)

    def test_container_workflow_publishes_ghcr_image(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "container.yml").read_text(encoding="utf-8")

        self.assertIn("packages: write", workflow)
        self.assertIn("docker/build-push-action", workflow)
        self.assertIn("ghcr.io/${{ github.repository }}", workflow)

    def test_public_release_versions_stay_aligned(self) -> None:
        manifest_version = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]
        backend_source = (ROOT / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
        installer_source = (ROOT / "scripts" / "learnnote-installer.iss").read_text(encoding="utf-8")
        site_source = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        backend_version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', backend_source)
        installer_version = re.search(r'#define MyAppVersion\s+"([^"]+)"', installer_source)

        self.assertIsNotNone(backend_version)
        self.assertIsNotNone(installer_version)
        self.assertEqual(manifest_version, backend_version.group(1))
        self.assertEqual(manifest_version, installer_version.group(1))
        self.assertIn(f"v{manifest_version}", site_source)


if __name__ == "__main__":
    unittest.main()
