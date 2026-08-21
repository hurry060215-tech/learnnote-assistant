from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "index.html"
RESOURCE = ROOT / "web" / "i18n.js"


def audit() -> dict[str, object]:
    html = HTML.read_text(encoding="utf-8")
    resource = RESOURCE.read_text(encoding="utf-8")
    html_keys = set(re.findall(r'data-i18n(?:-aria)?="([A-Za-z0-9_-]+)"', html))
    resource_keys = set(re.findall(r"^\s{6}([A-Za-z][A-Za-z0-9_]*)\s*:", resource, re.MULTILINE))
    missing = sorted(html_keys - resource_keys)
    script_order = [match.group(1) for match in re.finditer(r'<script src="([^"]+)"', html)]
    i18n_index = next((index for index, value in enumerate(script_order) if "/i18n.js" in value), -1)
    app_index = next((index for index, value in enumerate(script_order) if "/app.js" in value), -1)
    return {
        "html_key_count": len(html_keys),
        "resource_key_count": len(resource_keys),
        "missing_keys": missing,
        "i18n_before_app": i18n_index >= 0 and app_index >= 0 and i18n_index < app_index,
        "passed": not missing and i18n_index >= 0 and app_index >= 0 and i18n_index < app_index,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
