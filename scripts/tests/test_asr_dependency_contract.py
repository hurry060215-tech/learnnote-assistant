"""All optional ASR installers must share the decoder compatibility constraint."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[2]

class AsrDependencyContractTests(unittest.TestCase):
    def test_server_and_optional_installer_share_compatible_requirements(self):
        requirements = (ROOT / "backend/requirements.asr.txt").read_text()
        self.assertIn("faster-whisper>=1.1.1", requirements)
        self.assertIn("av>=11,<19", requirements)
        self.assertIn("-r requirements.asr.txt", (ROOT / "backend/requirements.deploy.txt").read_text())
        startup = (ROOT / "start-backend.ps1").read_text()
        self.assertIn("-r requirements.asr.txt", startup)
        self.assertIn("av.__version__", startup)
        self.assertIn("backend/requirements.asr.txt /app/backend/", (ROOT / "Dockerfile").read_text())
        for filename in ("LearnNote.spec", "LearnNote.macos.spec"):
            self.assertIn("backend/requirements.asr.txt", (ROOT / filename).read_text())
        self.assertIn('"local_asr_install_hint": "python -m pip install -r backend/requirements.asr.txt"', (ROOT / "backend/app/main.py").read_text(encoding="utf-8"))
