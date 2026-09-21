from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PlatformLauncherContractTests(unittest.TestCase):
    def test_macos_launcher_uses_browser_workspace_and_user_data(self) -> None:
        source = (ROOT / "scripts" / "start-macos.sh").read_text(encoding="utf-8")
        self.assertIn("Library/Application Support/LearnNote", source)
        self.assertIn("requirements.txt", source)
        self.assertIn("uvicorn app.main:app", source)
        self.assertIn('open "${URL}"', source)
        self.assertIn('PYTHONPATH="${ROOT}:${ROOT}/backend', source)
        self.assertNotIn("desktop/main.py", source)

    def test_linux_launcher_contract_remains_explicit(self) -> None:
        source = (ROOT / "scripts" / "start-linux.sh").read_text(encoding="utf-8")
        self.assertIn("XDG_DATA_HOME", source)
        self.assertIn("requirements.desktop.txt", source)
        self.assertIn("desktop/main.py", source)

    def test_windows_browser_entry_points_are_one_click(self) -> None:
        batch = (ROOT / "start-learnnote.bat").read_text(encoding="utf-8")
        powershell = (ROOT / "start-learnnote.ps1").read_text(encoding="utf-8")
        command = (ROOT / "start-learnnote.command").read_text(encoding="utf-8")
        self.assertIn("-OpenBrowser", batch)
        self.assertIn("[switch]$OpenBrowser", powershell)
        self.assertIn("open-browser-after-health.ps1", powershell)
        self.assertIn("start-macos.sh", command)

    def test_windows_launcher_keeps_project_root_on_python_path(self) -> None:
        source = (ROOT / "start-desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("PYTHONPATH", source)
        self.assertIn("$projectRoot", source)


if __name__ == "__main__":
    unittest.main()
