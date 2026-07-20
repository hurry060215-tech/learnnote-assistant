from __future__ import annotations

import argparse
import json
from pathlib import Path


FORBIDDEN_PARTS = {"tests", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
REQUIRED_EXTENSION_FILES = {
    "manifest.json",
    "background.js",
    "content.js",
    "page_hook.js",
    "sidepanel.html",
    "sidepanel.css",
    "sidepanel.js",
    "INSTALL.txt",
}


def audit_release_tree(root: Path) -> dict:
    root = root.resolve()
    files = [path for path in root.rglob("*") if path.is_file()]
    forbidden = sorted(
        str(path.relative_to(root))
        for path in files
        if FORBIDDEN_PARTS.intersection(path.relative_to(root).parts)
    )
    extension = root / "extension"
    extension_files = {path.name for path in extension.iterdir() if path.is_file()} if extension.is_dir() else set()
    missing_extension = sorted(REQUIRED_EXTENSION_FILES - extension_files)
    unexpected_extension = sorted(extension_files - REQUIRED_EXTENSION_FILES)
    return {
        "root": str(root),
        "file_count": len(files),
        "forbidden": forbidden,
        "missing_extension": missing_extension,
        "unexpected_extension": unexpected_extension,
        "passed": root.is_dir() and not forbidden and not missing_extension and not unexpected_extension,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject development-only files from a LearnNote release tree.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_release_tree(args.root)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
