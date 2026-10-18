import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReleasePublishingTests(unittest.TestCase):
    def test_reviewed_notes_are_preferred_with_old_tag_fallback(self):
        source = (ROOT / "scripts/publish-release.ps1").read_text(encoding="utf-8")
        self.assertIn("$Tag.TrimStart('v').Replace('.', '')", source)
        self.assertIn('--notes-file $releaseNotes', source)
        self.assertIn('--generate-notes', source)
        self.assertIn('--draft --verify-tag --notes-file', source)

    def test_current_release_has_complete_packaged_and_published_notes(self):
        notes = json.loads((ROOT / "web/release-notes.json").read_text(encoding="utf-8"))
        current = notes["current"]
        versions = [release["version"] for release in notes["releases"]]
        self.assertEqual(versions[0], current)
        self.assertEqual(len(versions), len(set(versions)))
        release = notes["releases"][0]
        for field in ("title", "summary", "date"):
            self.assertTrue(release[field].strip(), field)
        self.assertGreater(len(release["highlights"]), 0)
        for highlight in release["highlights"]:
            self.assertTrue(highlight["title"].strip())
            self.assertTrue(highlight["description"].strip())
        published = ROOT / "docs" / ("RELEASE_" + current.replace(".", "") + ".md")
        self.assertTrue(published.is_file(), "Publishing must use reviewed current-version notes")
        self.assertTrue(published.read_text(encoding="utf-8").startswith(f"# LearnNote v{current}\n"))
        self.assertIn(f"## {current} - ", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))

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

    def test_empty_asset_fails_before_any_github_operation(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell is required for the Windows publishing script")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ["a.zip", "b.exe", "c.json"]
            for name in names:
                (root / name).write_bytes(b"")
            digest = hashlib.sha256(b"").hexdigest()
            (root / "SHA256SUMS.txt").write_text("\n".join(f"{digest}  {name}" for name in names), encoding="ascii")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "scripts/publish-release.ps1"), "-Tag", "v0.0.0", "-Repository", "fixture/example", "-ValidateOnly"], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Empty release asset", result.stderr)


if __name__ == "__main__":
    unittest.main()
