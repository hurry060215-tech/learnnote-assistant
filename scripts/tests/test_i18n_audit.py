from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    spec = importlib.util.spec_from_file_location("i18n_audit", ROOT / "scripts" / "audit-i18n.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtensionI18nAuditTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        shutil.copytree(ROOT / "extension", root / "extension", ignore=shutil.ignore_patterns("tests", "icons"))
        self.module.ROOT = root
        self.module.EXTENSION_MANIFEST = root / "extension" / "manifest.json"
        self.module.EXTENSION_LOCALES = {locale: root / "extension" / "_locales" / locale / "messages.json" for locale in ("en", "zh_CN")}

    def append(self, name, source):
        path = self.module.ROOT / "extension" / name
        path.write_text(path.read_text(encoding="utf-8") + source, encoding="utf-8")

    def test_repo_extension_contract_passes(self):
        result = self.module.extension_audit()
        self.assertTrue(result["extension_passed"], result)
        self.assertGreater(result["extension_referenced_key_count"], 200)

    def test_missing_runtime_key_fails_even_with_matching_catalog_sets(self):
        self.append("sidepanel.js", '\nbutton.textContent = t("not_translated_yet");')
        result = self.module.extension_audit()
        self.assertIn("en:not_translated_yet", result["extension_missing_keys"])
        self.assertIn("zh_CN:not_translated_yet", result["extension_missing_keys"])
        self.assertFalse(result["extension_passed"])

    def test_new_background_and_content_errors_require_resources(self):
        self.append("background.js", '\nsendResponse({ error: "New service error" });')
        self.append("content.js", '\nsendResponse({ error: error?.message || "新的定位错误" });')
        result = self.module.extension_audit()
        self.assertEqual(len(result["extension_unlocalized_service_errors"]), 2)
        self.assertFalse(result["extension_passed"])

    def test_missing_html_key_fails(self):
        self.append("sidepanel.html", '<button data-i18n="new_control">新控件</button>')
        self.assertIn("en:new_control", self.module.extension_audit()["extension_missing_keys"])

    def test_hardcoded_english_chinese_aria_placeholder_and_markup_fail(self):
        for source in ('<button>New control</button>', '<input aria-label="Search">', '<input placeholder="Search">', '<p>新控件</p>'):
            parser = self.module.ExtensionMarkupAudit()
            parser.feed(source)
            self.assertTrue(parser.unlocalized, source)
        for source in ('button.textContent = "Retry";', 'const message = "New control";', 'button.innerHTML = "<p>Retry</p>";', 'button.textContent = `Saved ${count} results`;', 'const view = `<p>保存失败</p>`;', 'const view = `<button>Retry</button>`;', 'const view = `${ok ? "New control" : t("other")}`;'):
            self.assertTrue(self.module.hardcoded_extension_copy(source), source)

    def test_machine_strings_comments_and_user_values_are_not_translated(self):
        source = '// Keep the user title unchanged\nconst url = "http://127.0.0.1:8765";\nconst pattern = /字幕|caption/;\nnode.textContent = title;\nconst html = `<p>${escapeQuickHtml(note)}</p>`;'
        self.assertFalse(self.module.hardcoded_extension_copy(source))

    def test_mismatched_interpolation_and_stale_fallback_fail(self):
        path = self.module.EXTENSION_LOCALES["en"]
        content = json.loads(path.read_text(encoding="utf-8"))
        content["preview_counts"]["message"] = "{wrong} cues"
        path.write_text(json.dumps(content), encoding="utf-8")
        result = self.module.extension_audit()
        self.assertIn("preview_counts", result["extension_parameter_mismatch"])
        self.assertFalse(result["extension_fallback_matches_resources"])
        self.assertFalse(result["extension_passed"])

    def test_regeneration_catches_up_fallback_without_hiding_missing_keys(self):
        path = self.module.EXTENSION_LOCALES["en"]
        content = json.loads(path.read_text(encoding="utf-8"))
        content["openClient"]["message"] = "Open local workspace"
        path.write_text(json.dumps(content), encoding="utf-8")
        self.module.write_extension_runtime()
        self.assertTrue(self.module.extension_audit()["extension_passed"])
        for path in self.module.EXTENSION_LOCALES.values():
            content = json.loads(path.read_text(encoding="utf-8"))
            del content["service_network_failed"]
            path.write_text(json.dumps(content), encoding="utf-8")
        self.module.write_extension_runtime()
        self.assertIn("en:service_network_failed", self.module.extension_audit()["extension_missing_keys"])

    def test_invalid_default_and_wrong_script_order_fail(self):
        path = self.module.EXTENSION_MANIFEST
        content = json.loads(path.read_text(encoding="utf-8"))
        content["default_locale"] = "fr"
        path.write_text(json.dumps(content), encoding="utf-8")
        self.assertFalse(self.module.extension_audit()["extension_passed"])
        path = self.module.ROOT / "extension" / "sidepanel.html"
        path.write_text(path.read_text(encoding="utf-8").replace('<script src="i18n.js"></script>', ''), encoding="utf-8")
        self.assertFalse(self.module.extension_audit()["extension_i18n_before_panel"])


if __name__ == "__main__":
    unittest.main()
