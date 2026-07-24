from __future__ import annotations

import argparse
import json
import subprocess
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
REQUIRED_EXTENSION_ICONS = {
    "icon16.png",
    "icon32.png",
    "icon48.png",
    "icon128.png",
}
REQUIRED_ROOT_FILES = {
    "LICENSE",
    "NOTICE",
    "PRIVACY.md",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
}
GPL_LICENSE_PATH = Path("third_party/licenses/GPL-3.0.txt")
FFMPEG_SOURCE_PATH = Path("third_party/FFMPEG_SOURCE.md")


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
    icon_dir = extension / "icons"
    extension_icons = {path.name for path in icon_dir.iterdir() if path.is_file()} if icon_dir.is_dir() else set()
    missing_extension_icons = sorted(REQUIRED_EXTENSION_ICONS - extension_icons)
    root_files = {path.name for path in root.iterdir() if path.is_file()}
    missing_root = sorted(REQUIRED_ROOT_FILES - root_files)
    license_errors: list[str] = []
    ffmpeg_builds: list[dict] = []
    for executable in files:
        if not executable.name.lower().startswith("ffmpeg") or executable.suffix.lower() != ".exe":
            continue
        process = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        output = f"{process.stdout}\n{process.stderr}"
        is_gpl = "--enable-gpl" in output
        is_nonfree = "--enable-nonfree" in output
        ffmpeg_builds.append(
            {
                "path": str(executable.relative_to(root)),
                "version": output.splitlines()[0].strip() if output.splitlines() else "",
                "gpl": is_gpl,
                "nonfree": is_nonfree,
            }
        )
        if process.returncode != 0:
            license_errors.append(f"Unable to inspect bundled FFmpeg: {executable.relative_to(root)}")
        if is_nonfree:
            license_errors.append(f"Bundled FFmpeg is non-redistributable: {executable.relative_to(root)}")
        if is_gpl:
            if not (root / GPL_LICENSE_PATH).is_file():
                license_errors.append(f"GPL FFmpeg requires {GPL_LICENSE_PATH.as_posix()}")
            if not (root / FFMPEG_SOURCE_PATH).is_file():
                license_errors.append(f"GPL FFmpeg requires {FFMPEG_SOURCE_PATH.as_posix()}")
    return {
        "root": str(root),
        "file_count": len(files),
        "forbidden": forbidden,
        "missing_extension": missing_extension,
        "unexpected_extension": unexpected_extension,
        "missing_extension_icons": missing_extension_icons,
        "missing_root": missing_root,
        "ffmpeg_builds": ffmpeg_builds,
        "license_errors": license_errors,
        "passed": (
            root.is_dir()
            and not forbidden
            and not missing_extension
            and not unexpected_extension
            and not missing_extension_icons
            and not missing_root
            and not license_errors
        ),
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
