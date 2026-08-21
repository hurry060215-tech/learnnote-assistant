from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from zipfile import ZipFile


REQUIRED = {"manifest.json", "background.js", "content.js", "page_hook.js", "sidepanel.html", "sidepanel.css", "sidepanel.js", "INSTALL.txt"}
SECRET_RE = re.compile(r"(?:sk-[A-Za-z0-9]{20,}|BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY|Bearer\s+[A-Za-z0-9._-]{24,}|(?:api[_-]?key|password)\s*[:=]\s*['\"]?(?:sk-|[A-Za-z0-9]{32,}))", re.I)


def validate(path: Path, expected_version: str = "") -> dict[str, object]:
    with ZipFile(path) as archive:
        names = {name.replace("\\", "/") for name in archive.namelist()}
        missing = sorted(REQUIRED - names)
        if missing:
            raise ValueError(f"missing package files: {', '.join(missing)}")
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("unsafe archive path")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("manifest_version") != 3:
            raise ValueError("store package must be Manifest V3")
        version = str(manifest.get("version") or "")
        if expected_version and version != expected_version:
            raise ValueError(f"version mismatch: {version} != {expected_version}")
        scanned = []
        for name in names:
            if Path(name).suffix.lower() not in {".js", ".html", ".css", ".txt", ".json"}:
                continue
            text = archive.read(name).decode("utf-8", errors="replace")
            if SECRET_RE.search(text):
                scanned.append(name)
        if scanned:
            raise ValueError(f"secret-like content found in: {', '.join(sorted(scanned))}")
    return {"status": "pass", "version": version, "file_count": len(names), "path": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.package.expanduser().resolve(), args.version), ensure_ascii=False))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
