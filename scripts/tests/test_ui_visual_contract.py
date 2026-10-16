from __future__ import annotations

import unittest
from fnmatch import fnmatchcase
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class UiVisualContractTests(unittest.TestCase):
    def test_runtime_dependency_updates_trigger_existing_visual_gate(self) -> None:
        workflow = yaml.load((ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for event in ("pull_request", "push"):
            patterns = workflow["on"][event]["paths"]
            for path in ("backend/requirements.txt", "backend/requirements.test.txt",
                         "backend/requirements.asr.txt", "backend/requirements.ocr.txt",
                         "backend/requirements.windows-py312.lock.txt", "backend/constraints.linux-py312.txt"):
                self.assertTrue(any(fnmatchcase(path, pattern) for pattern in patterns), (event, path))

    def test_visual_runtime_uses_production_constraints_and_refreshes_cache(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["accessibility-visual"]
        self.assertEqual(job["runs-on"], "windows-latest")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", job)
        setup = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
        patterns = setup["with"]["cache-dependency-path"].splitlines()
        for path in ("backend/requirements.windows-py312.lock.txt", "backend/requirements.txt",
                     "backend/constraints.linux-py312.txt"):
            self.assertTrue(any(fnmatchcase(path, pattern) for pattern in patterns), path)
        install = next(step for step in job["steps"] if step.get("name") == "Install visual test dependencies")
        self.assertIn("-r backend/requirements.test.txt", install["run"])
        self.assertIn("-c backend/requirements.windows-py312.lock.txt", install["run"])

    def test_visual_dependency_failures_stop_before_browser_checks(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8"))
        install = next(step for step in workflow["jobs"]["accessibility-visual"]["steps"]
                       if step.get("name") == "Install visual test dependencies")
        lines = [line.strip() for line in install["run"].splitlines() if line.strip()]
        for command in ("python -m pip install", "python -m pip check", "npm ci"):
            index = next(index for index, line in enumerate(lines) if line.startswith(command))
            self.assertRegex(lines[index + 1], r'^if \(\$LASTEXITCODE -ne 0\) \{ throw ".+" \}$')
        self.assertNotIn("continue-on-error", install)

    def test_visual_script_covers_locale_scale_viewports_and_overflow(self) -> None:
        script = (ROOT / "scripts" / "accessibility-visual-acceptance.cjs").read_text(encoding="utf-8")
        for marker in ("en-US", "zh-CN", "data-value=\"200\"", "1440", "768", "390", "horizontalOverflow", "keyboard"):
            self.assertIn(marker, script)

    def test_workflow_uses_isolated_backend_and_retains_artifacts(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ui-visual.yml").read_text(encoding="utf-8")
        self.assertIn("LEARNNOTE_DATA_DIR", workflow)
        self.assertIn("uvicorn", workflow)
        self.assertIn("accessibility-visual-acceptance.cjs", workflow)
        self.assertIn("actions/upload-artifact", workflow)

    def test_local_player_gate_is_hosted_and_retains_real_media_evidence(self) -> None:
        workflow = yaml.load((ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for event in ("pull_request", "push"):
            patterns = workflow["on"][event]["paths"]
            for path in ("scripts/local-player-fixture.py", "scripts/local-player-visual-acceptance.cjs"):
                self.assertTrue(any(fnmatchcase(path, pattern) for pattern in patterns), (event, path))
        job = workflow["jobs"]["accessibility-visual"]
        self.assertEqual(job["runs-on"], "windows-latest")
        execution = next(step["run"] for step in job["steps"] if step.get("name") == "Start isolated local backend")
        self.assertIn("node scripts/local-player-visual-acceptance.cjs build/local-player-ui", execution)
        upload = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertIn("build/local-player-ui", upload["with"]["path"])

    def test_i18n_audit_script_is_present(self) -> None:
        script = (ROOT / "scripts" / "audit-i18n.py").read_text(encoding="utf-8")
        self.assertIn("missing_keys", script)
        self.assertIn("i18n_before_app", script)
        self.assertIn("extension_locale_mismatch", script)

    def test_home_video_shortcut_uses_normalized_source_url(self) -> None:
        script = (ROOT / "web" / "desk-product.js").read_text(encoding="utf-8")
        self.assertIn('$("url").value = result.source.normalized_url || result.source.url || "";', script)

    def test_local_document_import_is_not_presented_as_video_ai_generation(self) -> None:
        script = (ROOT / "web" / "desk.js").read_text(encoding="utf-8")
        batch = (ROOT / "web" / "desk-material-batch.js").read_text(encoding="utf-8")
        self.assertIn(
            'state.input === "browser" || (state.input === "file" && !hasVideo)',
            script,
        )
        self.assertIn('!queue.canSubmit', batch)
        self.assertIn(
            '"先选择文件"', batch
        )
        self.assertIn(
            '"导入并阅读资料"', batch
        )
        self.assertIn(
            '$("contentModeChoices").hidden = hideVideoOptions;', script
        )

    def test_first_run_assets_use_a_fresh_browser_cache_key(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        entry = (ROOT / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn("desk.js?v=local-player-20261016", html)
        self.assertIn("desk-product.js?v=first-run-20260923", entry)


if __name__ == "__main__":
    unittest.main()
