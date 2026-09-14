from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "classic.html"
PRIMARY = ROOT / "web" / "index.html"
RESOURCE = ROOT / "web" / "i18n.js"
EXTENSION_MANIFEST = ROOT / "extension" / "manifest.json"
EXTENSION_LOCALES = {
    "zh_CN": ROOT / "extension" / "_locales" / "zh_CN" / "messages.json",
    "en": ROOT / "extension" / "_locales" / "en" / "messages.json",
}


def audit() -> dict[str, object]:
    html = HTML.read_text(encoding="utf-8")
    resource = RESOURCE.read_text(encoding="utf-8")
    primary = PRIMARY.read_text(encoding="utf-8")
    primary_language_declared = 'lang="zh-CN"' in primary
    primary_keys = set(re.findall(r'data-i18n(?:-aria)?="([A-Za-z0-9_-]+)"', primary))
    html_keys = set(re.findall(r'data-i18n(?:-aria)?="([A-Za-z0-9_-]+)"', html))
    resource_keys = set(re.findall(r"^\s{6}([A-Za-z][A-Za-z0-9_]*)\s*:", resource, re.MULTILINE))
    missing = sorted((html_keys | primary_keys) - resource_keys)
    manifest = json.loads(EXTENSION_MANIFEST.read_text(encoding="utf-8"))
    extension_keys = set(re.findall(r"__MSG_([A-Za-z][A-Za-z0-9_]*)__", json.dumps(manifest)))
    extension_messages = {
        locale: set(json.loads(path.read_text(encoding="utf-8")))
        for locale, path in EXTENSION_LOCALES.items()
    }
    extension_missing = sorted(extension_keys - extension_messages.get(manifest.get("default_locale", ""), set()))
    extension_locale_mismatch = sorted(extension_messages.get("zh_CN", set()) ^ extension_messages.get("en", set()))
    script_order = [match.group(1) for match in re.finditer(r'<script src="([^"]+)"', html)]
    i18n_index = next((index for index, value in enumerate(script_order) if "/i18n.js" in value), -1)
    app_index = next((index for index, value in enumerate(script_order) if "/app.js" in value), -1)
    return {
        "primary_locale": "zh-CN",
        "primary_scope": "single-language redesign preview",
        "legacy_page": "classic.html",
        "html_key_count": len(html_keys),
        "resource_key_count": len(resource_keys),
        "missing_keys": missing,
        "i18n_before_app": i18n_index >= 0 and app_index >= 0 and i18n_index < app_index,
        "extension_locale_keys": {locale: len(keys) for locale, keys in extension_messages.items()},
        "extension_missing_keys": extension_missing,
        "extension_locale_mismatch": extension_locale_mismatch,
        "passed": primary_language_declared and not missing and not extension_missing and not extension_locale_mismatch and i18n_index >= 0 and app_index >= 0 and i18n_index < app_index,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
