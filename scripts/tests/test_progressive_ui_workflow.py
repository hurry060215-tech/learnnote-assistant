from fnmatch import fnmatchcase
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class ProgressiveUiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(
            (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

    def test_reference_gate_is_independent_required_and_read_only(self):
        job = self.workflow["jobs"]["progressive-reference"]
        self.assertEqual(job["runs-on"], "windows-latest")
        self.assertEqual(job["timeout-minutes"], "30")
        self.assertNotIn("needs", job)
        self.assertNotIn("if", job)
        self.assertNotIn("continue-on-error", job)
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", job)
        for step in job["steps"]:
            self.assertNotIn("continue-on-error", step)
        commands = [s for s in job["steps"] if "run" in s]
        self.assertEqual(len(commands), 5)
        self.assertIn("-c backend/requirements.windows-py312.lock.txt", commands[0]["run"])
        self.assertIn("python -m pip check", commands[0]["run"])
        self.assertIn("npm ci", commands[0]["run"])
        self.assertEqual(commands[0]["id"], "reference_dependencies")
        self.assertNotIn("if", commands[1])
        media = commands[2]
        self.assertEqual(media["id"], "visual_media_tools")
        self.assertEqual(media["if"], "${{ !cancelled() && steps.reference_dependencies.outcome == 'success' }}")
        self.assertEqual(media["run"].strip(), "./scripts/install-visual-media-tools.ps1 -OutputDirectory build/progressive-visual-ui")
        install = (ROOT / "scripts/install-visual-media-tools.ps1").read_text(encoding="utf-8")
        self.assertIn("choco install ffmpeg --version=8.1.0 --source=https://community.chocolatey.org/api/v2/ --yes --no-progress", install)
        self.assertIn("@('ffmpeg', 'ffprobe')", install)
        self.assertIn("Unexpected pinned media version", install)
        self.assertIn('Join-Path $OutputDirectory "media-tools.json"', install)
        self.assertNotIn("--ignore-checksums", install)
        ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        steps = ci["jobs"]["checks"]["steps"]
        provision = next(i for i, step in enumerate(steps) if step.get("name") == "Provision pinned media tools for real fixture contracts")
        contracts = next(i for i, step in enumerate(steps) if step.get("name") == "Desktop and release checks")
        self.assertLess(provision, contracts)
        self.assertNotIn("continue-on-error", steps[provision])
        self.assertEqual(steps[provision]["run"], "./scripts/install-visual-media-tools.ps1 -OutputDirectory build/visual-media-tools")
        probe = commands[3]
        self.assertEqual(probe["if"], "${{ !cancelled() && steps.reference_dependencies.outcome == 'success' && steps.visual_media_tools.outcome == 'success' }}")
        self.assertEqual(probe["timeout-minutes"], "4")
        self.assertEqual(probe["run"].splitlines()[0], "python scripts/windows-media-stdin-probe.py build/media-stdin-probe")
        self.assertEqual(sum(step["run"].count("python scripts/windows-media-stdin-probe.py") for step in commands), 1)
        visual = commands[4]
        self.assertEqual(visual["if"], "${{ !cancelled() && steps.reference_dependencies.outcome == 'success' && steps.visual_media_tools.outcome == 'success' }}")
        self.assertEqual(visual["timeout-minutes"], "10")
        self.assertIn("Get-Command ffmpeg -ErrorAction Stop", visual["run"])
        self.assertIn("Get-Command ffprobe -ErrorAction Stop", visual["run"])
        self.assertEqual(visual["run"].count("node scripts/progressive-visual-api-acceptance.cjs"), 1)
        self.assertEqual(commands[1]["run"].count("node scripts/progressive-slo-api-acceptance.cjs"), 1)
        for step in commands:
            lines = step["run"].splitlines()
            for index, line in enumerate(lines):
                if line.startswith(("python ", "npm ", "node ", "choco ")):
                    self.assertIn('$LASTEXITCODE -ne 0', lines[index + 1])
                    self.assertIn('throw ', lines[index + 1])

    def test_failure_evidence_excludes_task_data_and_triggers_cover_fixture(self):
        upload = self.workflow["jobs"]["progressive-reference"]["steps"][-1]
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@"))
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["path"].splitlines(), [
            "build/progressive-slo-ui/*.json", "build/progressive-slo-ui/*.log",
            "build/progressive-slo-ui/*.png",
            "build/progressive-visual-ui/*.json", "build/progressive-visual-ui/*.log",
            "build/progressive-visual-ui/*.png",
            "build/media-stdin-probe/*.json", "build/media-stdin-probe/*.log",
        ])
        for event in ("push", "pull_request"):
            patterns = self.workflow["on"][event]["paths"]
            for filename in ("scripts/progressive-slo-api-acceptance.cjs",
                             "scripts/progressive-slo-fixture.py",
                             "scripts/tests/test_progressive_slo_fixture.py",
                             "scripts/tests/progressive-slo-api.test.cjs",
                             "scripts/tests/test_progressive_ui_workflow.py",
                             "scripts/progressive-visual-api-acceptance.cjs",
                             "scripts/progressive-visual-fixture.py",
                             "scripts/install-visual-media-tools.ps1",
                             "scripts/windows-media-stdin-probe.py",
                             "scripts/tests/test_windows_media_stdin_probe.py",
                             "docs/qa/windows-media-stdin-probe.md",
                             "scripts/tests/test_progressive_visual_fixture.py",
                             "web/tests/progressive_visual_fixture.test.mjs",
                             "docs/qa/progressive-visual-continuation.md",
                             "backend/app/progressive.py", "backend/app/processor.py",
                             "backend/app/task_queue.py", "backend/app/routers/task_events.py"):
                self.assertTrue(any(fnmatchcase(filename, p) for p in patterns), (event, filename))


if __name__ == "__main__":
    unittest.main()
