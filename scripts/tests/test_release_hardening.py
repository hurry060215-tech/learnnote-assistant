from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseHardeningContractTests(unittest.TestCase):
    def test_upgrade_gate_is_d_drive_scoped_and_checks_preservation(self) -> None:
        source = (ROOT / "scripts" / "test-upgrade-installer.ps1").read_text(encoding="utf-8")

        self.assertIn("D:\\LearnNoteUpgradeSmoke", source)
        self.assertIn("Assert-SafeChildPath", source)
        self.assertIn("PreviousInstallerPath", source)
        self.assertIn("CurrentInstallerPath", source)
        self.assertIn("user-data-must-survive.txt", source)
        self.assertIn("learnnote-config.json", source)
        self.assertIn("Current extension version", source)
        self.assertIn("Uninstall removed the configured external data directory", source)
        self.assertNotIn("Remove-Item -LiteralPath $safeBase", source)

    def test_model_provider_offline_contract_executes_without_credentials(self) -> None:
        script = ROOT / "scripts" / "model-provider-contract.py"
        source = script.read_text(encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["mode"], "offline")
        self.assertFalse(report["network_attempted"])
        self.assertGreaterEqual(report["provider_count"], 8)
        self.assertIn("response details were redacted", source)
        self.assertIn("content was redacted", source)
        self.assertNotIn("live check failed: {exc}", source)
        self.assertNotIn("unexpected response: {text", source)

    def test_long_video_gate_defaults_to_one_hour_without_asr_or_llm(self) -> None:
        source = (ROOT / "scripts" / "long-video-reliability.py").read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--duration-seconds", type=int, default=3600)', source)
        self.assertIn('"mode": "media-and-frames-only"', source)
        self.assertIn('"api_calls": 0', source)
        self.assertIn('"transcription_attempted": False', source)
        self.assertIn("extract_frames_adaptive", source)
        self.assertIn("build_frame_grids", source)
        self.assertNotIn("transcribe_audio(", source)
        self.assertNotIn("OpenAI(", source)

    def test_weekly_workflow_has_offline_and_public_sample_gates(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "reliability.yml").read_text(encoding="utf-8")

        self.assertIn("schedule:", workflow)
        self.assertIn("model-provider-contract.py", workflow)
        self.assertIn("long-video-reliability.py", workflow)
        self.assertIn("test_release_hardening.py", workflow)
        self.assertIn("samplelib.com/sample-mp4.html", workflow)
        self.assertIn("-RequireReady", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("interactive-login", workflow)

    def test_release_matrix_documents_manual_upgrade_and_credential_boundaries(self) -> None:
        matrix = (ROOT / "docs" / "RELEASE_TEST_MATRIX.md").read_text(encoding="utf-8")

        self.assertIn("test-upgrade-installer.ps1", matrix)
        self.assertIn("long-video-reliability.py", matrix)
        self.assertIn("model-provider-contract.py", matrix)
        self.assertIn("--live-provider", matrix)
        self.assertIn("does not use login state", matrix)
        self.assertIn("D:\\LearnNoteUpgradeSmoke", matrix)


if __name__ == "__main__":
    unittest.main()
