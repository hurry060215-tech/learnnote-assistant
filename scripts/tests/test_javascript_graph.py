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

    def test_catalog_recovery_components_keep_one_way_dependencies(self):
        root = self.repository({
            "web/material-catalog-recovery.js": 'import "./catalog-recovery-view.js"; import "./task-catalog-recovery.js";',
            "web/task-catalog-recovery.js": 'import "./catalog-recovery-view.js";',
            "web/catalog-recovery-view.js": "export const make = () => {};",
        })
        self.assertEqual(javascript_violations(root), [])
        for source, dependency in (
            ("catalog-recovery-view.js", "task-catalog-recovery.js"),
            ("task-catalog-recovery.js", "material-catalog-recovery.js"),
        ):
            path = root / "web" / source
            original = path.read_text(encoding="utf-8")
            path.write_text(original + f'\nimport "./{dependency}";', encoding="utf-8")
            errors = javascript_violations(root)
            self.assertTrue(any("pure-module boundary" in error for error in errors), errors)
            self.assertTrue(any("dependency cycle" in error for error in errors), errors)
            path.write_text(original, encoding="utf-8")

    def test_new_es_module_cycle_and_missing_file_fail(self):
        root = self.repository({
            "web/alpha.js": 'import { x } from "/web/beta.js?v=1";',
            "web/beta.js": 'export { x } from "./alpha.js"; import("./missing.js");',
        })
        errors = javascript_violations(root)
        self.assertTrue(any("dependency cycle" in error for error in errors))
        self.assertTrue(any("missing local script" in error for error in errors))

    def test_template_interpolation_cycles_and_missing_files_fail_with_lf_and_crlf(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                source = newline.join((
                    'const text = `inert import("./fake.js")',
                    '${import("./beta.js")}',
                    '${import("./missing.js")}',
                    '`;',
                ))
                specs, injections, errors = local_specifiers(js_tokens(source))
                self.assertEqual(specs, [("./beta.js", 2, "import"), ("./missing.js", 3, "import")])
                self.assertEqual((injections, errors), ([], []))
                root = self.repository({
                    "web/alpha.js": source,
                    "web/beta.js": 'import("./alpha.js");',
                })
                self.assertEqual(javascript_violations(root), [
                    "web/alpha.js imports missing local script web/missing.js",
                    "JavaScript dependency cycle: web/alpha.js <-> web/beta.js",
                ])

    def test_nested_templates_and_expression_braces_preserve_every_import(self):
        source = '''const text = `head ${(() => {
            const object = {first: import("./first.js"), nested: {brace: "}"}};
            return `nested ${({value: import("./second.js")}).value}
                ${`deeper ${import("./third.js")}`}`;
        })()} tail ${import("./fourth.js")}`;
        import("./after.js");'''
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual([item[0] for item in specs], [
            "./first.js", "./second.js", "./third.js", "./fourth.js", "./after.js",
        ])
        self.assertEqual((injections, errors), ([], []))

    def test_interpolation_strings_comments_and_regex_do_not_end_expression(self):
        source = r'''const text = `${(() => {
            const single = '} import("./fake-single.js")';
            const double = "} import('./fake-double.js')";
            const plain = `} import("./fake-template.js")`;
            // } ` ${import("./fake-line.js")}
            /* } ` ${import("./fake-block.js")} */
            const pattern = /[{}]import\("\.\/fake-regex\.js"\)\`/;
            return /}/.test(single) ? import("./real.js") : plain;
        })()} import("./fake-tail.js")`;
        const other = `${/[}]/.test("}") ? import("./other.js") : ""}`;'''
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual([item[0] for item in specs], ["./real.js", "./other.js"])
        self.assertEqual((injections, errors), ([], []))

    def test_escaped_template_text_is_inert_and_even_backslashes_allow_interpolation(self):
        source = r'''const text = String.raw`\${import("./fake.js")} \` still text`;
        const live = `\\${import("./real.js")}`;
        import(`./plain.js`);
        import(`./\${literal}.js`);'''
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual([item[0] for item in specs], ["./real.js", "./plain.js", "./${literal}.js"])
        self.assertEqual((injections, errors), ([], []))

    def test_computed_imports_in_templates_fail_without_inventing_paths(self):
        source = '''const text = `${import("./" + name)}`;
        import(`./${name}.js`);
        import(`./${import("./real.js")}.js`);
        const nested = `${import(`./${name}.js`)}`;'''
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual([item[0] for item in specs], ["./real.js"])
        self.assertEqual(injections, [])
        self.assertEqual(len(errors), 4, errors)
        self.assertTrue(all("computed import path is not auditable" in error for error in errors), errors)

    def test_template_boundaries_preserve_injection_lists_and_division(self):
        source = '''chrome.scripting.executeScript({
            func: () => `inert ${({files: ["fake.js"]})}`,
            files: ["content.js"]
        });
        const text = `${importScripts("helper.js")}`;
        const fraction = `${1}` / 2;
        const literalFraction = `1` / 2;
        import("./after.js");'''
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual([item[0] for item in specs], ["helper.js", "./after.js"])
        self.assertEqual(injections, [["content.js"]])
        self.assertEqual(errors, [])

    def test_regex_operands_and_control_bodies_stay_inert_in_interpolations(self):
        source = r'''const text = `${1 + /}import("fake-add.js")/.source}`;
        const keywords = `${(() => {
            if (ready && (enabled)) /}import("fake-if.js")/.test(value);
            while (false) /}import("fake-while.js")/.test(value);
            throw /}import("fake-throw.js")/;
        })()}`;
        const divided = `${(() => {
            const values = [count++ / 2, count-- / 2, "return" / 2, object.if() / 2];
            const properties = [object.in / 2, object?.return / 2, object.await / 2];
            return import("./real.js");
        })()}`;'''
        specs, injections, errors = local_specifiers(js_tokens(source))
        self.assertEqual([item[0] for item in specs], ["./real.js"])
        self.assertEqual((injections, errors), ([], []))

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

    def test_task_list_requires_both_helpers_before_app(self):
        files = {
            "web/task-format.js": "globalThis.LearnNoteTaskFormat = {};",
            "web/task-display.js": "globalThis.LearnNoteTaskFormat; globalThis.LearnNoteTaskDisplay = {};",
            "web/task-list.js": "globalThis.LearnNoteTaskFormat; globalThis.LearnNoteTaskDisplay; globalThis.LearnNoteTaskList = {};",
            "web/app.js": "globalThis.LearnNoteTaskList;",
        }
        root = self.repository(files)
        order = list(files)
        html = root / "web/classic.html"
        html.write_text("".join(f'<script src="/{name}?v=fixture"></script>' for name in order), encoding="utf-8")
        self.assertEqual(javascript_violations(root), [])
        for sequence in (order[:-2] + order[-2:][::-1], [order[0], order[2], order[1], order[3]], order[:2] + [order[3]]):
            with self.subTest(sequence=sequence):
                html.write_text("".join(f'<script src="/{name}"></script>' for name in sequence), encoding="utf-8")
                self.assertTrue(any("before its classic script is loaded" in error for error in javascript_violations(root)))

    def test_task_list_reverse_dependency_and_missing_helper_fail(self):
        root = self.repository({
            "web/task-list.js": 'import "./app.js"; globalThis.LearnNoteTaskFormat;',
            "web/app.js": "globalThis.LearnNoteTaskList;",
        })
        errors = javascript_violations(root)
        self.assertTrue(any("dependency cycle" in error for error in errors))
        self.assertTrue(any("pure-module boundary" in error for error in errors))
        self.assertTrue(any("missing local script web/task-format.js" in error for error in errors))

    def visual_study_repository(self):
        return self.repository({
            "web/task-format.js": "globalThis.LearnNoteTaskFormat = {};",
            "web/task-display.js": "globalThis.LearnNoteTaskFormat; globalThis.LearnNoteTaskDisplay = {};",
            "web/task-list.js": "globalThis.LearnNoteTaskFormat; globalThis.LearnNoteTaskDisplay; globalThis.LearnNoteTaskList = {};",
            "web/visual-window-evidence.js": "globalThis.LearnNoteTaskFormat; globalThis.LearnNoteVisualWindowEvidence = {};",
            "web/visual-study.js": "globalThis.LearnNoteTaskFormat; globalThis.LearnNoteTaskList; globalThis.LearnNoteVisualWindowEvidence; globalThis.LearnNoteVisualStudy = {};",
            "web/app.js": "globalThis.LearnNoteVisualStudy;",
        })

    def test_visual_study_requires_all_providers_before_app(self):
        root = self.visual_study_repository()
        order = ["task-format.js", "task-display.js", "task-list.js", "visual-window-evidence.js", "visual-study.js", "app.js"]
        html = root / "web/classic.html"

        def write_order(names):
            html.write_text("".join(f'<script src="/web/{name}?v=fixture"></script>' for name in names), encoding="utf-8")

        write_order(order)
        self.assertEqual(javascript_violations(root), [])
        for omitted in order[:-1]:
            with self.subTest(omitted=omitted):
                write_order([name for name in order if name != omitted])
                errors = javascript_violations(root)
                self.assertTrue(any("before its classic script is loaded" in error for error in errors), errors)
        write_order(order[:-2] + order[-2:][::-1])
        self.assertTrue(any("before its classic script is loaded" in error for error in javascript_violations(root)))

    def test_visual_study_rejects_reverse_edges_and_cycles(self):
        for source, target in (
            ("visual-study.js", "app.js"),
            ("visual-window-evidence.js", "visual-study.js"),
            ("task-list.js", "visual-study.js"),
            ("task-format.js", "visual-study.js"),
        ):
            with self.subTest(source=source, target=target):
                root = self.visual_study_repository()
                path = root / "web" / source
                path.write_text(path.read_text(encoding="utf-8") + f'\nimport "./{target}";', encoding="utf-8")
                errors = javascript_violations(root)
                self.assertTrue(any("pure-module boundary" in error for error in errors), errors)
                self.assertTrue(any("dependency cycle" in error for error in errors), errors)

    def test_visual_study_and_transitive_providers_cannot_escape_budget(self):
        root = self.visual_study_repository()
        names = tuple(path.name for path in (root / "web").glob("*.js"))
        self.assertEqual(javascript_violations(root, classic_task_scripts=names), [])
        for omitted in names:
            with self.subTest(omitted=omitted):
                errors = javascript_violations(root, classic_task_scripts=tuple(name for name in names if name != omitted))
                self.assertTrue(any(f"Classic task budget omits dependency web/{omitted}" in error for error in errors), errors)

    def test_classic_task_dependency_cannot_escape_combined_budget(self):
        root = self.repository({
            "web/app.js": "globalThis.LearnNoteTaskList;",
            "web/task-list.js": "globalThis.LearnNoteTaskDisplay;",
            "web/task-display.js": "globalThis.LearnNoteTaskFormat;",
            "web/task-format.js": "globalThis.LearnNoteTaskFormat = {};",
        })
        names = ("app.js", "task-list.js", "task-display.js", "task-format.js")
        self.assertEqual(javascript_violations(root, classic_task_scripts=names), [])
        for omitted in names:
            with self.subTest(omitted=omitted):
                errors = javascript_violations(root, classic_task_scripts=tuple(name for name in names if name != omitted))
                self.assertTrue(any(f"Classic task budget omits dependency web/{omitted}" in error for error in errors))

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

    def test_product_domains_cannot_import_orchestrators(self):
        providers = {
            "source-identity.js": "LearnNoteSourceIdentity",
            "request-context.js": "LearnNoteRequestContext",
            "cookie-context.js": "LearnNoteCookieContext",
            "backend-transport.js": "LearnNoteBackendTransport",
            "content-media-hints.js": "LearnNoteContentMediaHints",
        }
        for filename, namespace in providers.items():
            with self.subTest(filename=filename):
                root = self.repository({
                    "extension/background.js": f'importScripts("{filename}");',
                    "extension/" + filename: f'importScripts("background.js"); globalThis.{namespace} = {{}};',
                })
                errors = javascript_violations(root)
                self.assertTrue(any("pure-module boundary" in error for error in errors), errors)
                self.assertTrue(any("dependency cycle" in error for error in errors), errors)
                errors = javascript_violations(root, ("background.js",))
                self.assertTrue(any(f"budget omits dependency extension/{filename}" in error for error in errors), errors)

    def test_content_media_parser_requires_classification_in_its_own_realm(self):
        root = self.repository({
            "extension/background.js": 'chrome.scripting.executeScript({files: ["capture-classification.js", "content-media-hints.js", "content.js"]});',
            "extension/capture-classification.js": "globalThis.LearnNoteCaptureClassification = {};",
            "extension/content-media-hints.js": "globalThis.LearnNoteCaptureClassification; globalThis.LearnNoteContentMediaHints = {};",
            "extension/content.js": "globalThis.LearnNoteContentMediaHints;",
        })
        self.assertEqual(javascript_violations(root), [])
        (root / "extension/background.js").write_text(
            'importScripts("capture-classification.js"); chrome.scripting.executeScript({files: ["content-media-hints.js", "content.js"]});',
            encoding="utf-8",
        )
        self.assertTrue(any("before its classic script is loaded" in error for error in javascript_violations(root)))

    def test_repo_graph_and_real_extension_load_order_pass(self):
        edges, errors, _imports, injections, _namespaces = javascript_analysis(SCRIPTS.parent)
        self.assertEqual(errors, [])
        self.assertGreater(len(edges), 20)
        self.assertTrue(any("extension/content.js" in sequence for sequence in injections["extension/background.js"]))
        self.assertEqual(javascript_violations(SCRIPTS.parent), [])


if __name__ == "__main__":
    unittest.main()
