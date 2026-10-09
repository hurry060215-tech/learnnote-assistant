from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import classic_styles as styles


class ClassicStylesTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "web").mkdir()
        links = "".join(f'<link rel="stylesheet" href="/web/{name}?v=fixture">' for name in styles.CLASSIC_STYLE_ORDER)
        (root / "web/classic.html").write_text(f"<head>{links}</head>", encoding="utf-8")
        (root / "web/index.html").write_text('<head><link rel="stylesheet" href="/web/desk.css"></head>', encoding="utf-8")
        for name in styles.CLASSIC_STYLE_ORDER:
            (root / "web" / name).write_text(".fixture { color: inherit; }\n", encoding="utf-8")
        return root

    def change_html(self, root, before, after):
        path = root / "web/classic.html"
        path.write_text(path.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")

    def test_repository_contract_and_original_cascade_snapshot(self):
        self.assertEqual(styles.classic_style_violations(ROOT), [])
        snapshot = json.loads((ROOT / "scripts/tests/fixtures/classic_styles_v1.json").read_text(encoding="utf-8"))
        # read_text normalizes Windows checkout CRLF; CSS bytes otherwise stay exact.
        source = "".join((ROOT / "web" / name).read_text(encoding="utf-8") for name in styles.CLASSIC_STYLE_LIMITS)
        self.assertEqual(len(source.splitlines()), snapshot["lines"])
        self.assertEqual(len(source.encode("utf-8")), snapshot["utf8_bytes"])
        self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(), snapshot["sha256"])

    def test_order_duplicate_missing_and_conditional_links_fail(self):
        mutations = (
            ("classic-workbench.css", "classic-study.css", "load order"),
            ('<link rel="stylesheet" href="/web/classic-workbench.css?v=fixture">', "", "load order"),
            ("/web/styles.css?v=fixture", "https://example.invalid/web/styles.css?v=fixture", "load order"),
            ('href="/web/styles.css', 'media="print" href="/web/styles.css', "render-blocking"),
            ('href="/web/styles.css', 'disabled href="/web/styles.css', "render-blocking"),
            ('href="/web/styles.css', 'onload="this.media=\'all\'" href="/web/styles.css', "render-blocking"),
            ("styles.css?v=fixture", "styles.css?v=old", "cache version"),
        )
        for before, after, expected in mutations:
            with self.subTest(expected=expected, after=after):
                root = self.fixture()
                self.change_html(root, before, after)
                self.assertTrue(any(expected in error for error in styles.classic_style_violations(root)))

    def test_missing_and_unbudgeted_modules_fail(self):
        root = self.fixture()
        (root / "web/classic-study.css").unlink()
        (root / "web/classic-unbudgeted.css").write_text(".extra {}", encoding="utf-8")
        errors = styles.classic_style_violations(root)
        self.assertTrue(any("Missing classic stylesheet" in error for error in errors))
        self.assertTrue(any("explicitly ordered and budgeted" in error for error in errors))

    def test_module_and_aggregate_budgets_are_independent(self):
        root = self.fixture()
        with patch.object(styles, "CLASSIC_STYLE_BUDGET", 3):
            errors = styles.classic_style_violations(root)
        self.assertEqual(len(errors), 1)
        self.assertIn("4 lines; combined budget is 3", errors[0])
        (root / "web/classic-study.css").write_text(".fixture {}\n" * 92, encoding="utf-8")
        errors = styles.classic_style_violations(root)
        self.assertEqual(len(errors), 1)
        self.assertIn("92 lines; limit is 91", errors[0])

    def test_import_cycles_and_cross_file_rule_blocks_are_forbidden(self):
        for source in ('@import "classic-study.css";', '@IMPORT url("classic-study.css");', r'@\69mport "classic-study.css";', '@charset "UTF-8";', '@namespace svg "fixture";', '@media (width < 900px) { .fixture {}', '} .fixture {}'):
            with self.subTest(source=source):
                root = self.fixture()
                path = root / "web/classic-study.css"
                path.write_text(source, encoding="utf-8")
                self.assertTrue(styles.css_resource_violations(path, root))

    def test_local_assets_keep_sibling_base_and_queries(self):
        root = self.fixture()
        (root / "web/fonts").mkdir()
        (root / "web/fonts/local.woff2").write_bytes(b"fixture")
        path = root / "web/classic-study.css"
        path.write_text('''/* @import "ignored.css"; url(missing.png) } */
.icon { content: "@import url(missing.png) {"; background: url(data:image/svg+xml,fixture); mask: url(#icon); }
@font-face { font-family: "Fixture"; src: url("fonts/local.woff2?v=1#font"); }
.other { background: URL(/web/fonts/local.woff2); }
''', encoding="utf-8")
        self.assertEqual(styles.css_resource_violations(path, root), [])
        (root / "web/fonts/local.woff2").unlink()
        self.assertEqual(len(styles.css_resource_violations(path, root)), 2)

    def test_remote_missing_and_non_web_assets_fail(self):
        for address in ('missing.png', '//example.invalid/font.woff2', 'https://example.invalid/font.woff2', '../private.txt', '/web/%2e%2e/private.txt'):
            with self.subTest(address=address):
                root = self.fixture()
                (root / "private.txt").write_text("fixture", encoding="utf-8")
                path = root / "web/classic-study.css"
                path.write_text(f'.fixture {{ background: url("{address}"); }}', encoding="utf-8")
                self.assertTrue(styles.css_resource_violations(path, root))

    def test_classic_group_cannot_enter_default_reader(self):
        root = self.fixture()
        (root / "web/index.html").write_text('<link rel="stylesheet" href="/web/classic-study.css">', encoding="utf-8")
        self.assertTrue(any("default reader" in error for error in styles.classic_style_violations(root)))

    def test_both_desktop_specs_exclude_every_extracted_sheet(self):
        for filename in ("LearnNote.spec", "LearnNote.macos.spec"):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            web_tree = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Tree" and ast.literal_eval(node.args[0]) == "web")
            excluded = ast.literal_eval(next(keyword.value for keyword in web_tree.keywords if keyword.arg == "excludes"))
            with self.subTest(filename=filename):
                self.assertTrue(set(styles.CLASSIC_STYLE_LIMITS).issubset(excluded))


if __name__ == "__main__":
    unittest.main()
