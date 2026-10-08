from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class PortableAsrCiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        cls.job = cls.workflow["jobs"]["portable-asr"]
        cls.commands = "\n".join(step.get("run", "") for step in cls.job["steps"])

    def test_portable_lane_has_read_only_permissions_and_offline_models(self) -> None:
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.job["runs-on"], "ubuntu-latest")
        self.assertNotIn("permissions", self.job)
        self.assertEqual(self.job["env"]["HF_HUB_OFFLINE"], "1")
        self.assertEqual(self.job["env"]["TRANSFORMERS_OFFLINE"], "1")

    def test_portable_lane_installs_and_checks_constrained_asr_runtime(self) -> None:
        for requirement in ("test", "asr"):
            self.assertIn(f"-r backend/requirements.{requirement}.txt", self.commands)
        self.assertIn("-c backend/requirements.windows-py312.lock.txt", self.commands)
        self.assertIn("-c backend/constraints.linux-py312.txt", self.commands)
        self.assertIn("python -m pip check", self.commands)
        self.assertIn("from faster_whisper.audio import decode_audio", self.commands)

    def test_portable_lane_executes_audio_regressions_without_allowing_failure(self) -> None:
        self.assertIn("python -m unittest backend.tests.test_cloud_qa_regressions", self.commands)
        self.assertNotIn("continue-on-error", self.job)
        for step in self.job["steps"]:
            self.assertNotIn("continue-on-error", step)
        self.assertNotIn("|| true", self.commands)


if __name__ == "__main__":
    unittest.main()
