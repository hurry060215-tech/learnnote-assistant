import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReleasePublishingTests(unittest.TestCase):
    def test_validation_checks_real_assets_and_never_invokes_github(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell is required for the Windows publishing script")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gh.cmd").write_text("@echo unexpected github call\n@exit /b 99\n")
            names = ["LearnNote-a.zip", "LearnNote-b.exe", "LearnNote-c.json"]
            entries = []
            for name in names:
                value = f"fixture {name}".encode()
                (root / name).write_bytes(value)
                entries.append(f"{hashlib.sha256(value).hexdigest()}  {name}")
            (root / "SHA256SUMS.txt").write_text("\n".join(entries))
            command = [pwsh, "-NoProfile", "-File", str(ROOT / "scripts/publish-release.ps1"), "-Tag", "v0.0.0", "-Repository", "fixture/example", "-ValidateOnly"]
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ.get("PATH", "")}
            valid = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertIn("no network calls", valid.stdout)
            (root / names[0]).write_bytes(b"tampered")
            invalid = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertNotIn("unexpected github call", invalid.stdout)


if __name__ == "__main__":
    unittest.main()
