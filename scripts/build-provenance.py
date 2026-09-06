"""Emit an installed-dependency SBOM and resolved versions for release audit."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
from urllib.parse import quote


def build_inventory():
    components, requirements = [], []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: (d.metadata.get("Name") or "").lower()):
        name = re.sub(r"[-_.]+", "-", distribution.metadata.get("Name") or "unknown").lower()
        version = distribution.version
        components.append({"type": "library", "name": name, "version": version, "purl": f"pkg:pypi/{quote(name)}@{quote(version)}"})
        requirements.append(f"{name}=={version}")
    try:
        import imageio_ffmpeg
        binary = Path(imageio_ffmpeg.get_ffmpeg_exe())
        components.append({"type": "file", "name": binary.name, "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(binary.read_bytes()).hexdigest()}]})
    except (ImportError, OSError, RuntimeError):
        pass
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": components}, requirements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root, text=True, encoding="utf-8").strip()
    source = {"schema_version": 1, "commit": git("rev-parse", "HEAD"), "commit_time": git("show", "-s", "--format=%cI", "HEAD"), "dirty": bool(git("status", "--porcelain")), "python": platform.python_version(), "platform": platform.system(), "scope": "Python build environment plus bundled ffmpeg; not a bit-reproducibility claim"}
    sbom, requirements = build_inventory()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("LearnNote-SBOM.json", sbom), ("LearnNote-Build-Source.json", source)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "LearnNote-Resolved-Requirements.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")
    print(json.dumps({"components": len(sbom["components"]), "commit": source["commit"], "dirty": source["dirty"]}))


if __name__ == "__main__":
    main()
