from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PlatformLauncherContractTests(unittest.TestCase):
    def test_unix_launchers_use_user_data_and_desktop_requirements(self) -> None:
        for name, marker in (("start-macos.sh", "Library/Application Support/LearnNote"), ("start-linux.sh", "XDG_DATA_HOME")):
            source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("requirements.desktop.txt", source)
            self.assertIn("desktop/main.py", source)
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
