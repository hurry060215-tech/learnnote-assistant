from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from html.parser import HTMLParser


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
    extension = extension_audit()
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
        **extension,
        "passed": primary_language_declared and not missing and extension["extension_passed"] and i18n_index >= 0 and app_index >= 0 and i18n_index < app_index,
    }


class ExtensionMarkupAudit(HTMLParser):
    """Require explicit translation ownership; never translate an entire container."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.keys = set()
        self.unlocalized = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for marker in ("data-i18n", "data-i18n-aria", "data-i18n-title", "data-i18n-placeholder", "data-i18n-alt"):
            if attrs.get(marker):
                self.keys.add(attrs[marker])
        for attribute, marker in (("aria-label", "data-i18n-aria"), ("title", "data-i18n-title"), ("placeholder", "data-i18n-placeholder"), ("alt", "data-i18n-alt")):
            value = attrs.get(attribute, "")
            if re.search(r"[A-Za-z\u4e00-\u9fff]", value) and not attrs.get(marker):
                self.unlocalized.append(f"line {self.getpos()[0]}: {attribute}={value}")
        if tag not in {"input", "meta", "link", "img", "br", "hr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        value = data.strip()
        if not value or value == "LearnNote" or not re.search(r"[A-Za-z\u4e00-\u9fff]", value):
            return
        if self.stack and self.stack[-1][1].get("data-i18n"):
            return
        self.unlocalized.append(f"line {self.getpos()[0]}: text={value}")


def javascript_literals(source):
    """Small lexical scanner, including nested template expressions and comments.

    This is a copy guard, not a JavaScript parser. Node's syntax checks remain
    authoritative. Regex bodies, comments and interpolation code are not prose.
    """
    literals = []
    def scan(index, interpolation=False):
        depth = 0
        previous = ""
        while index < len(source):
            char = source[index]
            if source.startswith("//", index):
                end = source.find("\n", index)
                index = len(source) if end < 0 else end + 1
                continue
            if source.startswith("/*", index):
                end = source.find("*/", index + 2)
                index = len(source) if end < 0 else end + 2
                continue
            if char in "\"'":
                start = index
                quote = char
                index += 1
                while index < len(source):
                    if source[index] == "\\": index += 2; continue
                    if source[index] == quote: break
                    index += 1
                literals.append((source[start + 1:index], start, "string"))
                index += 1
                previous = "value"
                continue
            if char == "`":
                index += 1
                start = index
                while index < len(source):
                    if source[index] == "\\": index += 2; continue
                    if source.startswith("${", index):
                        literals.append((source[start:index], start, "template"))
                        index = scan(index + 2, True)
                        start = index
                        continue
                    if source[index] == "`":
                        literals.append((source[start:index], start, "template"))
                        index += 1
                        break
                    index += 1
                previous = "value"
                continue
            if char == "/" and previous in {"", "=", "(", ",", ":", "!", "?", "|", "&", "return", "=>"}:
                index += 1
                in_class = False
                while index < len(source):
                    if source[index] == "\\": index += 2; continue
                    if source[index] == "[": in_class = True
                    elif source[index] == "]": in_class = False
                    elif source[index] == "/" and not in_class: index += 1; break
                    index += 1
                while index < len(source) and source[index].isalpha(): index += 1
                previous = "value"
                continue
            if char == "{": depth += 1
            elif char == "}":
                if interpolation and depth == 0: return index + 1
                depth -= 1
            if char.isalpha() or char in "_$":
                start = index
                while index < len(source) and (source[index].isalnum() or source[index] in "_$"): index += 1
                previous = source[start:index]
                continue
            if not char.isspace(): previous = char
            index += 1
        return index
    scan(0)
    return literals


def hardcoded_extension_copy(source):
    findings = []
    for value, offset, kind in javascript_literals(source):
        visible = re.sub(r"<[^>]*(?:>|$)", "", value) if kind == "template" else value
        # CSS class lists and one intentionally internal exception are not UI.
        if value in {"secondary-button compact-button", "extension API unavailable"}:
            continue
        prose = re.search(r"[\u4e00-\u9fff]|[A-Za-z]+\s+[A-Za-z]+", visible)
        before = source[max(0, offset - 90):offset]
        literal_sink = re.search(r"(?:\.(?:textContent|innerHTML)\s*=\s*|new Error\(\s*|setAttribute\(\s*['\"](?:aria-label|title|placeholder)['\"]\s*,\s*)$", before)
        visible_markup = re.search(r">[^<]*[A-Za-z]", value) and visible.strip() not in {"", "LearnNote"}
        template_words = kind == "template" and re.search(r"(?:^\s+[A-Za-z]|[A-Za-z]\s+$)", visible) and visible.strip() not in {"LearnNote"}
        if prose or visible_markup or template_words or (literal_sink and re.search(r"[A-Za-z\u4e00-\u9fff]", visible)):
            findings.append(f"line {source.count(chr(10), 0, offset) + 1}: {value}")
    return findings


def unlocalized_service_errors(catalogs):
    known = {item["message"] for key, item in catalogs["zh_CN"].items() if key.startswith("service_")}
    findings = []
    for filename in ("background.js", "content.js", "content-study-evidence.js"):
        source = (ROOT / "extension" / filename).read_text(encoding="utf-8")
        for value, offset, kind in javascript_literals(source):
            before = source[max(0, offset - 120):offset]
            error_sink = re.search(r"(?:\berror\s*:\s*(?:[A-Za-z_?.]+\s*\|\|\s*)?|new Error\(\s*|backendJsonResponse\(\s*res,\s*)$", before)
            if error_sink and (re.search(r"[\u4e00-\u9fff]|[A-Za-z]\s+[A-Za-z]", value)) and value not in known:
                findings.append(f"{filename}:{source.count(chr(10), 0, offset) + 1}: {value}")
    return findings


def extension_audit():
    manifest = json.loads(EXTENSION_MANIFEST.read_text(encoding="utf-8"))
    catalogs = {locale: json.loads(path.read_text(encoding="utf-8")) for locale, path in EXTENSION_LOCALES.items()}
    html = (ROOT / "extension" / "sidepanel.html").read_text(encoding="utf-8")
    script = (ROOT / "extension" / "sidepanel.js").read_text(encoding="utf-8")
    runtime = (ROOT / "extension" / "i18n.js").read_text(encoding="utf-8")
    markup = ExtensionMarkupAudit()
    markup.feed(html)
    keys = set(re.findall(r"__MSG_([A-Za-z][A-Za-z0-9_]*)__", json.dumps(manifest))) | markup.keys
    keys |= set(re.findall(r'\bt\(\s*["\']([A-Za-z][A-Za-z0-9_]*)["\']', script))
    runtime_logic = runtime.split("/* END CATALOGS */", 1)[-1]
    keys |= set(re.findall(r'["\'](service_[A-Za-z0-9_]+)["\']', runtime_logic))
    missing = sorted(f"{locale}:{key}" for locale, messages in catalogs.items() for key in keys if not messages.get(key, {}).get("message"))
    mismatch = sorted(set(catalogs["zh_CN"]) ^ set(catalogs["en"]))
    parameters = lambda value: set(re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", value))
    parameter_mismatch = sorted(key for key in set(catalogs["zh_CN"]) & set(catalogs["en"])
        if parameters(catalogs["zh_CN"][key]["message"]) != parameters(catalogs["en"][key]["message"]))
    expected = {locale: {key: item["message"] for key, item in messages.items()} for locale, messages in catalogs.items()}
    embedded = re.search(r"/\* BEGIN CATALOGS \*/(.*?)/\* END CATALOGS \*/", runtime, re.S)
    fallback_matches = bool(embedded and json.loads(embedded[1]) == expected)
    unlocalized = markup.unlocalized + hardcoded_extension_copy(script)
    service_errors = unlocalized_service_errors(catalogs)
    scripts = re.findall(r'<script src="([^"]+)"', html)
    ordered = "i18n.js" in scripts and any(name.startswith("sidepanel.js") for name in scripts) and scripts.index("i18n.js") < next(i for i, name in enumerate(scripts) if name.startswith("sidepanel.js"))
    valid_default = manifest.get("default_locale") in catalogs
    return {
        "extension_locale_keys": {locale: len(messages) for locale, messages in catalogs.items()},
        "extension_referenced_key_count": len(keys),
        "extension_missing_keys": missing,
        "extension_locale_mismatch": mismatch,
        "extension_parameter_mismatch": parameter_mismatch,
        "extension_hardcoded_copy": unlocalized,
        "extension_unlocalized_service_errors": service_errors,
        "extension_fallback_matches_resources": fallback_matches,
        "extension_i18n_before_panel": ordered,
        "extension_passed": valid_default and not missing and not mismatch and not parameter_mismatch and not unlocalized and not service_errors and fallback_matches and ordered,
    }


def write_extension_runtime():
    path = ROOT / "extension" / "i18n.js"
    source = path.read_text(encoding="utf-8")
    catalogs = {locale: {key: item["message"] for key, item in json.loads(path.read_text(encoding="utf-8")).items()} for locale, path in EXTENSION_LOCALES.items()}
    serialized = json.dumps(catalogs, ensure_ascii=False, indent=2)
    source, count = re.subn(r"(?<=/\* BEGIN CATALOGS \*/).*?(?=/\* END CATALOGS \*/)", lambda _: serialized, source, flags=re.S)
    if count != 1: raise ValueError("Expected exactly one bundled locale catalog block")
    path.write_text(source, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-runtime", action="store_true", help="Regenerate bundled extension fallback from locale JSON")
    args = parser.parse_args()
    if args.write_runtime:
        write_extension_runtime()
    result = audit()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
