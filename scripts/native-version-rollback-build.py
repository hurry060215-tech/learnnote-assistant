"""Build the two immutable unsigned macOS rollback fixtures, with auditable provenance.

Only the old spec's missing COLLECT stage is backported. Application source and
versions are never rewritten. Each build uses its own virtualenv and checkout;
all logs/inventories survive a failed build. This is not a release or a claim of
bit-reproducibility: runtime dependency resolutions are recorded, not locked.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import traceback

OLD_COMMIT = "5a1db274f68df792149658ff2bb27894870eb608"
NEW_COMMIT = "ee32db1e1c78bbe46c7a5aaa444d4f990383c3d1"
OLD_SPEC_SHA256 = "9ed79c77e2524a492de7a11b88d50c3a84e8fb21d337015ebd163928783b0ede"
NEW_SPEC_SHA256 = "f6c34344238535a988d859eeca1519828f6cb2ccec1a7f2c174c9fe3b33eaa22"
PYINSTALLER_VERSION = "6.22.2"
HOOKS_VERSION = "2026.7"
OLD_BUNDLE = b'\nBUNDLE(\n    exe,\n'
COLLECT_BUNDLE = (
    b'\ncollection = COLLECT(\n'
    b'    exe, a.binaries, a.datas, strip=False, upx=False, name="LearnNote",\n'
    b')\n\nBUNDLE(\n    collection,\n'
)
BACKPORT = "Only insert COLLECT(exe, a.binaries, a.datas) and pass it to BUNDLE; no application/runtime/version changes."


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def path_entry(root: Path, path: Path) -> dict:
    info = path.lstat()
    entry = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(info.st_mode)}
    if stat.S_ISLNK(info.st_mode):
        entry.update(type="symlink", target=os.readlink(path))
    elif stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        entry.update(type="file", size=info.st_size, sha256=digest.hexdigest())
    else:
        raise ValueError(f"Unsupported tree entry: {entry['path']}")
    return entry


def tree_inventory(root: Path) -> list[dict]:
    """Relative files and symlinks, sorted by path; never traverse symlink dirs.

    Empty directories and timestamps are excluded. Full permission bits, file
    size/content, and symlink target text are included. No target is dereferenced.
    """
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Expected a real tree directory: {root}")
    entries = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_dir():
                entries.append(path_entry(root, path))
    return sorted(entries, key=lambda entry: entry["path"])


def tree_digest(root: Path) -> str:
    return sha256(canonical_json(tree_inventory(root)))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=source, text=True, encoding="utf-8").strip()


def tracked_inventory(source: Path) -> list[dict]:
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode("utf-8").split("\0")
    return [path_entry(source, source / name) for name in sorted(filter(None, names))]


def app_version(source: Path) -> str:
    parsed = ast.parse((source / "backend/app/__init__.py").read_text(encoding="utf-8"))
    values = [ast.literal_eval(node.value) for node in parsed.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)]
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError("Expected exactly one literal APP_VERSION assignment")
    return values[0]


def patch_old_spec(original: bytes) -> bytes:
    if sha256(original) != OLD_SPEC_SHA256 or original.count(OLD_BUNDLE) != 1:
        raise ValueError("Old spec differs from the approved immutable v0.2.14 spec")
    return original.replace(OLD_BUNDLE, COLLECT_BUNDLE, 1)


def prepare_source(source: Path, label: str, evidence: Path) -> dict:
    expected_commit, expected_version, spec_hash = {
        "old": (OLD_COMMIT, "0.2.14", OLD_SPEC_SHA256),
        "new": (NEW_COMMIT, "0.2.15", NEW_SPEC_SHA256),
    }[label]
    evidence.mkdir(parents=True, exist_ok=True)
    actual_commit = git(source, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(f"{label} source commit mismatch: {actual_commit}")
    if git(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError(f"{label} checkout must be pristine before preparation")
    version = app_version(source)
    if version != expected_version:
        raise ValueError(f"{label} APP_VERSION mismatch: {version}")
    tag_commit = git(source, "rev-parse", "refs/tags/v0.2.14^{commit}") if label == "old" else None
    if label == "old" and tag_commit != OLD_COMMIT:
        raise ValueError(f"v0.2.14 tag does not resolve to approved source: {tag_commit}")
    original_inventory = tracked_inventory(source)
    write_json(evidence / "source-original-tree.json", original_inventory)
    spec_path = source / "LearnNote.macos.spec"
    original = spec_path.read_bytes()
    (evidence / "LearnNote.macos.original.spec").write_bytes(original)
    if sha256(original) != spec_hash:
        raise ValueError(f"{label} original spec hash mismatch")
    used = patch_old_spec(original) if label == "old" else original
    (evidence / "LearnNote.macos.used.spec").write_bytes(used)
    patch = "".join(difflib.unified_diff(original.decode().splitlines(keepends=True),
                                       used.decode().splitlines(keepends=True),
                                       fromfile="LearnNote.macos.original.spec", tofile="LearnNote.macos.used.spec"))
    (evidence / "packaging-only.patch").write_text(patch, encoding="utf-8")
    if label == "old":
        spec_path.write_bytes(used)
    prepared_inventory = tracked_inventory(source)
    write_json(evidence / "source-build-tree.json", prepared_inventory)
    return {
        "status": "prepared", "source_commit": actual_commit,
        "source_git_tree": git(source, "rev-parse", "HEAD^{tree}"),
        "source_path": str(source), "tag": "v0.2.14" if label == "old" else None,
        "tag_commit": tag_commit, "expected_app_version": expected_version, "app_version": version,
        "source_tree_sha256": sha256(canonical_json(original_inventory)),
        "build_source_tree_sha256": sha256(canonical_json(prepared_inventory)),
        "spec_original_sha256": sha256(original), "spec_used_sha256": sha256(used),
        "packaging_backport": BACKPORT if label == "old" else None,
        "app_path": str(source / "dist/LearnNote.app"), "app_tree_sha256": None,
        "app_tree_inventory": str(evidence / "app-tree.json"),
        "evidence_path": str(evidence),
    }


def build_environment() -> dict[str, str]:
    # Source checkouts contain synthetic builds only; do not inherit user/provider
    # configuration. Offline model flags still allow installing build dependencies.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LEARNNOTE_", "OPENAI_", "ANTHROPIC_", "LLM_", "_PYI"))
           and key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env.update(PYTHONNOUSERSITE="1", PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
               ORT_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_TELEMETRY="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


def run_logged(command: list[str], source: Path, log: Path, env: dict) -> None:
    with log.open("a", encoding="utf-8") as output:
        output.write("$ " + " ".join(command) + "\n")
        output.flush()
        subprocess.run(command, cwd=source, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)


def build_source(source: Path, environment: Path, evidence: Path, record: dict) -> None:
    if environment.exists():
        raise ValueError(f"Build environment must be new: {environment}")
    env = build_environment()
    env.update(PYINSTALLER_CONFIG_DIR=str(environment / "pyinstaller-cache"),
               PIP_CACHE_DIR=str(environment / "pip-cache"))
    log = evidence / "build.log"
    run_logged([sys.executable, "-m", "venv", str(environment)], source, log, env)
    python = str(environment / "bin/python")
    run_logged([python, "-m", "pip", "install", "-r", "backend/requirements.test.txt",
                f"pyinstaller=={PYINSTALLER_VERSION}", f"pyinstaller-hooks-contrib=={HOOKS_VERSION}"], source, log, env)
    run_logged([python, "-m", "pip", "check"], source, log, env)
    with (evidence / "resolved-requirements.txt").open("w", encoding="utf-8") as output:
        subprocess.run([python, "-m", "pip", "freeze", "--all"], cwd=source, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)
    toolchain_code = (
        "import importlib.metadata as m, json, platform; "
        "print(json.dumps({'python': platform.python_version(), 'platform': platform.platform(), "
        "'pyinstaller': m.version('pyinstaller'), 'pyinstaller-hooks-contrib': m.version('pyinstaller-hooks-contrib')}))"
    )
    toolchain = json.loads(subprocess.check_output([python, "-c", toolchain_code], cwd=source, env=env, text=True))
    write_json(evidence / "toolchain.json", toolchain)
    record["toolchain"] = toolchain
    if toolchain["pyinstaller"] != PYINSTALLER_VERSION or toolchain["pyinstaller-hooks-contrib"] != HOOKS_VERSION:
        raise ValueError("Resolved build toolchain differs from required pins")
    run_logged([python, "-m", "PyInstaller", "--noconfirm", "--clean", "LearnNote.macos.spec"], source, log, env)
    if sha256(canonical_json(tracked_inventory(source))) != record["build_source_tree_sha256"]:
        raise ValueError("Tracked source changed during build beyond the disclosed packaging backport")
    app = Path(record["app_path"])
    if not (app / "Contents/MacOS/LearnNote").is_file():
        raise ValueError("Build did not produce the native app executable")
    inventory = tree_inventory(app)
    write_json(Path(record["app_tree_inventory"]), inventory)
    record["app_tree_sha256"] = sha256(canonical_json(inventory))
    record["status"] = "built"


def validate_paths(old: Path, new: Path, output: Path, environments: Path) -> None:
    paths = [old, new, output, environments]
    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError("Source, evidence and environment directories must be separate non-nested paths")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-source", type=Path, required=True)
    parser.add_argument("--new-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environments", type=Path, required=True)
    args = parser.parse_args()
    old, new, output, environments = (path.resolve() for path in (args.old_source, args.new_source, args.output, args.environments))
    validate_paths(old, new, output, environments)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "build-manifest.json"
    if manifest_path.exists():
        raise ValueError("Refusing to overwrite existing build provenance; use a fresh output directory")
    manifest = {
        "schema_version": 1, "status": "building", "platform": platform.platform(),
        "scope": "Unsigned macOS synthetic rollback fixtures. No release, signing, live media or model execution.",
        "reproducibility": "Immutable source and pinned packaging tools; all resolved dependencies recorded. Not bit-reproducible builds.",
        "tree_digest_algorithm": "sha256(canonical JSON of sorted non-directory relative-path entries; file mode/size/sha256 or symlink mode/target; no symlink traversal, timestamps or empty directories)",
        "builds": {},
    }
    write_json(manifest_path, manifest)
    if sys.platform != "darwin":
        manifest.update(status="failed", error="Native fixture builds require macOS")
        write_json(manifest_path, manifest)
        raise RuntimeError(manifest["error"])
    for label, source in (("old", old), ("new", new)):
        evidence = output / "builds" / label
        evidence.mkdir(parents=True, exist_ok=True)
        record = {"status": "preparing", "source_path": str(source)}
        manifest["builds"][label] = record
        try:
            record.update(prepare_source(source, label, evidence))
            write_json(manifest_path, manifest)
            build_source(source, environments / label, evidence, record)
        except Exception as exc:
            record.update(status="failed", error=str(exc))
            (evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            # PyInstaller warnings remain useful when the bundle never completes.
            try:
                for warning in sorted((source / "build").glob("*/warn-*.txt")):
                    shutil.copyfile(warning, evidence / warning.name)
            except OSError as exc:
                record["warning_copy_error"] = str(exc)
            write_json(manifest_path, manifest)
    manifest["status"] = "built" if all(record["status"] == "built" for record in manifest["builds"].values()) else "failed"
    write_json(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "manifest": str(manifest_path)}))
    return 0 if manifest["status"] == "built" else 1


if __name__ == "__main__":
    raise SystemExit(main())
