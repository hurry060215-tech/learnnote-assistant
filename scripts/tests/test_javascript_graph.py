from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from javascript_graph import javascript_analysis, javascript_violations, js_tokens, local_specifiers


class JavaScriptArchitectureTests(unittest.TestCase):
    def repository(self, files):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return root

    def test_dependencies_ignore_comments_strings_templates_and_regular_expressions(self):
        source = """// import "./fake.js";
        /* importScripts("fake.js"); */
        const example = "import('./fake.js')";
        const template = \x60export { x } from './fake.js'\x60;
        const pattern = /importScripts\\("fake.js"\\)/;
        import { x } from "/web/real.js?v=1";
        export { x } from "./other.js";
        import("./lazy.js");"""
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual(errors, [])
        self.assertEqual(injections, [])
        self.assertEqual([item[0] for item in specs], ["/web/real.js?v=1", "./other.js", "./lazy.js"])

    def test_new_es_module_cycle_and_missing_file_fail(self):
        root = self.repository({
            "web/alpha.js": 'import { x } from "/web/beta.js?v=1";',
            "web/beta.js": 'export { x } from "./alpha.js"; import("./missing.js");',
        })
        errors = javascript_violations(root)
        self.assertTrue(any("dependency cycle" in error for error in errors))
        self.assertTrue(any("missing local script" in error for error in errors))

    def test_nested_runtime_modules_are_resolved_but_test_fixtures_are_excluded(self):
        root = self.repository({
            "web/entry.js": 'import { value } from "./parts/value.mjs";',
            "web/parts/value.mjs": "export const value = 1;",
            "web/tests/example.js": 'import "./deliberately-missing.js";',
        })
        self.assertEqual(javascript_violations(root), [])

    def test_computed_and_remote_dependencies_fail_closed(self):
        root = self.repository({"web/a.js": 'import(\x60./\u0024{name}.js\x60); import("./" + name); import("https://example.test/a.js");'})
        errors = javascript_violations(root)
        self.assertTrue(any("computed import" in error for error in errors))
        self.assertTrue(any("non-local script" in error for error in errors))

    def test_classic_worker_dependency_order_is_checked(self):
        root = self.repository({
            "extension/background.js": 'importScripts("capture-classification.js", "capture-ranking.js");',
            "extension/capture-classification.js": 'globalThis.LearnNoteCaptureClassification = {};',
            "extension/capture-ranking.js": 'const types = globalThis.LearnNoteCaptureClassification; globalThis.LearnNoteCaptureRanking = {};',
        })
        self.assertEqual(javascript_violations(root), [])
        (root / "extension/background.js").write_text('importScripts("capture-ranking.js", "capture-classification.js");', encoding="utf-8")
        self.assertTrue(any("before its classic script is loaded" in error for error in javascript_violations(root)))

    def test_injected_chapter_only_helper_loads_in_its_own_realm(self):
        root = self.repository({
            "extension/background.js": 'chrome.scripting.executeScript({target: {tabId: 1}, files: ["content-study-evidence.js", "content.js"]});',
            "extension/content-study-evidence.js": 'globalThis.LearnNoteStudyEvidence = Object.freeze({collectChapterEvidence: () => []});',
            "extension/content.js": 'globalThis.LearnNoteStudyEvidence.collectChapterEvidence({});',
        })
        self.assertEqual(javascript_violations(root), [])
        (root / "extension/background.js").write_text(
            'chrome.scripting.executeScript({target: {tabId: 1}, files: ["content.js", "content-study-evidence.js"]});',
            encoding="utf-8",
        )
        self.assertTrue(any("content.js reads" in error for error in javascript_violations(root)))
        (root / "extension/background.js").write_text(
            'importScripts("content-study-evidence.js"); chrome.scripting.executeScript({target: {tabId: 1}, files: ["content.js"]});',
            encoding="utf-8",
        )
        errors = javascript_violations(root)
        self.assertTrue(any("content.js reads" in error for error in errors), errors)

    def test_chapter_helper_cannot_import_background_orchestration(self):
        root = self.repository({
            "extension/background.js": 'chrome.scripting.executeScript({files: ["content-study-evidence.js", "content.js"]});',
            "extension/content-study-evidence.js": 'importScripts("background.js"); globalThis.LearnNoteStudyEvidence = Object.freeze({collectChapterEvidence: () => []});',
            "extension/content.js": 'globalThis.LearnNoteStudyEvidence.collectChapterEvidence({});',
        })
        errors = javascript_violations(root)
        self.assertTrue(any("content-study-evidence.js crosses pure-module boundary" in error for error in errors))
        self.assertTrue(any("dependency cycle" in error for error in errors))

    def test_injection_cannot_use_computed_file_lists(self):
        root = self.repository({"extension/background.js": "chrome.scripting.executeScript({files: dynamicFiles});"})
        self.assertTrue(any("computed executeScript" in error for error in javascript_violations(root)))

    def test_classic_html_dependency_order_is_checked(self):
        root = self.repository({
            "web/task-format.js": 'globalThis.LearnNoteTaskFormat = {};',
            "web/task-display.js": 'const format = globalThis.LearnNoteTaskFormat; globalThis.LearnNoteTaskDisplay = {};',
            "web/app.js": 'const display = globalThis.LearnNoteTaskDisplay;',
            "web/classic.html": '<script src="/web/task-format.js"></script><script src="/web/task-display.js"></script><script src="/web/app.js"></script>',
        })
        self.assertEqual(javascript_violations(root), [])
        (root / "web/classic.html").write_text('<script src="/web/app.js"></script>', encoding="utf-8")
        self.assertTrue(any("before its classic script is loaded" in error for error in javascript_violations(root)))

    def test_pure_reverse_dependency_and_cross_surface_import_fail(self):
        root = self.repository({
            "extension/capture-classification.js": 'importScripts("background.js");',
            "extension/background.js": 'importScripts("capture-classification.js");',
            "web/app.js": 'import "/extension/background.js";',
        })
        errors = javascript_violations(root)
        self.assertTrue(any("pure-module boundary" in error for error in errors))
        self.assertTrue(any("web/extension boundary" in error for error in errors))
        self.assertTrue(any("dependency cycle" in error for error in errors))

    def test_capture_dependency_cannot_escape_existing_bundle_budget(self):
        root = self.repository({
            "extension/background.js": 'importScripts("helper.js");',
            "extension/helper.js": "const value = 1;",
        })
        self.assertTrue(any("budget omits" in error for error in javascript_violations(root, ("background.js",))))
        self.assertEqual(javascript_violations(root, ("background.js", "helper.js")), [])

    def test_unreferenced_future_study_contract_requires_no_helper_file(self):
        root = self.repository({
            "extension/background.js": 'chrome.scripting.executeScript({files: ["content.js"]});',
            "extension/content.js": "const page = {};",
        })
        self.assertEqual(javascript_violations(root), [])

    def test_repo_graph_and_real_extension_load_order_pass(self):
        edges, errors, _imports, injections, _namespaces = javascript_analysis(SCRIPTS.parent)
        self.assertEqual(errors, [])
        self.assertGreater(len(edges), 20)
        self.assertTrue(any("extension/content.js" in sequence for sequence in injections["extension/background.js"]))
        self.assertEqual(javascript_violations(SCRIPTS.parent), [])


if __name__ == "__main__":
    unittest.main()
