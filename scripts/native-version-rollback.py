"""Two immutable native builds, explicit stopped-data snapshot restoration.

No newer-schema downgrade is implied. All data, captions and notes are synthetic;
no model, ASR, real media site or installed user profile participates.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
OLD = "5a1db274f68df792149658ff2bb27894870eb608"
NEW = "ee32db1e1c78bbe46c7a5aaa444d4f990383c3d1"
TEXT = "# Rollback synthetic material\n\n本地学习 café 日本語 🧭. The learning rate controls every update.\n"
PERSONAL = "Original synthetic annotation 原始批注 café"
NEW_EDIT = "New-version-only annotation 升级后的独立批注"
CUES = [dict(start=0.0, end=10.0, text="SYNTHETIC_ONE The learning rate controls the size of every update."),
        dict(start=10.0, end=20.0, text="SYNTHETIC_TWO Validation compares the retained evidence across versions.")]

spec = importlib.util.spec_from_file_location("native_platform", ROOT / "scripts/native-platform-acceptance.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def inventory(root):
    """Complete owned data inventory; reject links rather than follow outside data."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Snapshot must not follow symlink: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    return result


def snapshot(source, destination):
    if destination.exists():
        raise ValueError("Snapshot destination already exists")
    before = inventory(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    assert inventory(source) == before == inventory(destination), "Stopped-data snapshot changed bytes"
    return before


def owned_capture(pid, output, phase):
    """Wait for the actual pywebview loaded title, then capture only its window."""
    deadline = time.monotonic() + 60
    while True:
        result = subprocess.run(["swift", str(ROOT / "scripts/native-version-window.swift"), str(pid)],
                                check=True, capture_output=True, text=True, timeout=30)
        windows = json.loads(result.stdout)
        if len(windows) == 1 and windows[0]["title"] == "LearnNote - Video Learning Notes":
            break
        if time.monotonic() >= deadline:
            raise AssertionError(f"Owned loaded window unavailable: {windows}")
        time.sleep(.25)
    window = windows[0]
    subprocess.run(["screencapture", "-x", "-l", str(window["id"]), str(output / f"{phase}.png")],
                   check=True, timeout=20)
    image = (output / f"{phase}.png").read_bytes()
    assert image.startswith(b"\x89PNG\r\n\x1a\n") and len(image) > 24, "Owned screenshot is not a PNG"
    after = subprocess.run(["swift", str(ROOT / "scripts/native-version-window.swift"), str(pid)],
                           check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(after.stdout) == windows, "Owned native window changed during capture"
    return {"pid": pid, **window, "image": f"{phase}.png",
            "image_sha256": hashlib.sha256(image).hexdigest(), "visual_review_required": True}


@contextmanager
def running(app, data, output, phase, version):
    port = native.free_port()
    executable = app / "Contents/MacOS/LearnNote"
    env = native.isolated_environment(data, port)
    env.pop("PYTHONPATH", None)
    with (output / f"{phase}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(executable), "--port", str(port)], cwd=app.parent,
                                   env=env, stdout=log, stderr=log)
        api = None
        failure = None
        try:
            api = native.Api(port)
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise AssertionError(f"{phase} exited: {process.returncode}")
                try:
                    health = api.call("GET", "/health").json()
                    break
                except requests.ConnectionError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"{phase} health timeout")
                    time.sleep(.25)
            assert health["ok"] and health["app_version"] == version, health
            deadline = time.monotonic() + 30
            while not api.call("POST", "/api/desktop/focus", json={"view": "workspace"}).json().get("focused"):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Native window focus callback unavailable")
                time.sleep(.25)
            capture = owned_capture(process.pid, output, phase)
            yield api, {"health": {key: health[key] for key in ("ok", "app_version", "backend_version")}, "window": capture}
        except BaseException as error:
            failure = error
            raise
        finally:
            cleanup_errors = []
            try:
                if api is not None:
                    api.session.close()
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            except BaseException as error:
                cleanup_errors.append(error)
            if cleanup_errors:
                if failure is None:
                    raise cleanup_errors[0]
                print(f"Secondary cleanup failures: {cleanup_errors}", file=sys.stderr)



def seed(api):
    material = api.call("POST", "/api/library/materials/import",
                        files={"file": ("rollback.md", TEXT.encode(), "text/markdown")}).json()["material"]
    material_id = material["material_id"]
    api.call("POST", f"/api/personal/material/{material_id}", json={"text": PERSONAL, "quote": "learning rate"})
    payload = dict(page_url="https://example.com/synthetic-rollback", title="Synthetic rollback captions",
                   handoff_id="native-rollback-synthetic-caption", mode="subtitle_only",
                   browser_subtitles=CUES, active_video={"duration": 20},
                   options={"content_mode": "subtitles", "visual_understanding": False})
    task_id = api.call("POST", "/api/tasks/from-current-page", json=payload).json()["task_id"]
    deadline = time.monotonic() + 60
    while True:
        task = api.call("GET", f"/api/tasks/{task_id}").json()["task"]
        if task["status"] == "success":
            break
        assert task["status"] not in ("failed", "canceled"), task
        if time.monotonic() >= deadline:
            raise TimeoutError("Synthetic caption task did not complete")
        time.sleep(.1)
    assert task["summary_source"] == "subtitle-extract", task
    return {"material_id": material_id, "task_id": task_id}


def read_evidence(api, ids, annotations):
    prefix = f'/api/tasks/{ids["task_id"]}'
    material = api.call("GET", f'/api/library/materials/{ids["material_id"]}/source').content
    assert material == TEXT.encode()
    notes = api.call("GET", f'/api/personal/material/{ids["material_id"]}').json()["annotations"]
    assert sorted(x["text"] for x in notes) == sorted(annotations)
    task = api.call("GET", prefix).json()["task"]
    assert task["status"] == "success" and task["summary_source"] == "subtitle-extract"
    transcript = api.call("GET", prefix + "/transcript").json()
    segments = transcript["segments"]
    assert [{k: x[k] for k in ("start", "end", "text")} for x in segments] == CUES
    exports = {}
    for kind in ("markdown", "subtitles"):
        raw = api.call("GET", prefix + "/exports/" + kind).content
        assert all(cue["text"].encode() in raw for cue in CUES)
        exports[kind] = hashlib.sha256(raw).hexdigest()
    return {"task_id": ids["task_id"], "material_id": ids["material_id"], "exports": exports,
            "material_sha256": hashlib.sha256(material).hexdigest(), "segments": segments}


def exercise(old_app, new_app, output, launch=running):
    data = output / "active-data"
    if data.exists():
        raise ValueError("Fresh owned output directory required")
    phases = []
    with launch(old_app, data, output, "old-before-upgrade", "0.2.14") as (api, phase):
        ids = seed(api)
        before = read_evidence(api, ids, [PERSONAL])
        phases.append(phase)
    pre = snapshot(data, output / "pre-upgrade-snapshot")
    write_json(output / "pre-upgrade-inventory.json", pre)
    with launch(new_app, data, output, "new-after-upgrade", "0.2.15") as (api, phase):
        assert read_evidence(api, ids, [PERSONAL]) == before
        api.call("POST", f'/api/personal/material/{ids["material_id"]}', json={"text": NEW_EDIT, "quote": "update"})
        assert read_evidence(api, ids, [PERSONAL, NEW_EDIT]) == before
        phases.append(phase)
    upgraded = snapshot(data, output / "upgraded-snapshot")
    write_json(output / "upgraded-inventory.json", upgraded)
    # Keep the complete upgraded active tree. No recursive deletion is needed.
    data.rename(output / "upgraded-active-data")
    assert snapshot(output / "pre-upgrade-snapshot", data) == pre
    with launch(old_app, data, output, "old-after-snapshot-restore", "0.2.14") as (api, phase):
        assert read_evidence(api, ids, [PERSONAL]) == before
        phases.append(phase)
    assert inventory(output / "pre-upgrade-snapshot") == pre
    assert inventory(output / "upgraded-snapshot") == upgraded
    assert inventory(output / "upgraded-active-data") == upgraded
    (output / "snapshot-inventories.json").write_text(json.dumps({"pre_upgrade": pre, "upgraded": upgraded}, indent=2), encoding="utf-8")
    return {"status": "pass", "phases": phases, "evidence": before,
            "snapshot_files": {"pre_upgrade": len(pre), "upgraded": len(upgraded)},
            "rollback_method": "old executable with restored pre-upgrade data at the identical path",
            "new_edits_preserved_in_separate_snapshot": True,
            "not_tested": ["old binary opening newer-schema data", "post-upgrade edits downgraded", "signing", "notarization", "real media sites", "remote models", "ASR"]}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def verify_builds(manifest, old_app, new_app):
    build_spec = importlib.util.spec_from_file_location("rollback_build", ROOT / "scripts/native-version-rollback-build.py")
    build_module = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(build_module)
    for key, app, commit, version in (("old", old_app, OLD, "0.2.14"), ("new", new_app, NEW, "0.2.15")):
        build = manifest["builds"][key]
        assert build["source_commit"] == commit and build["app_version"] == version
        assert Path(build["app_path"]).resolve() == app.resolve()
        assert (app / "Contents/MacOS/LearnNote").is_file()
        assert build_module.tree_digest(app) == build["app_tree_sha256"], "Native app differs from recorded build"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-app", type=Path, required=True)
    parser.add_argument("--new-app", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Actual native macOS host required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "failed", "platform": platform.platform(), "architecture": platform.machine(),
              "commit": os.getenv("GITHUB_SHA", "local")}
    failure = None
    try:
        manifest = json.loads(args.build_manifest.read_text(encoding="utf-8"))
        report["build_manifest"] = manifest
        verify_builds(manifest, args.old_app, args.new_app)
        report.update(exercise(args.old_app.resolve(), args.new_app.resolve(), output))
        verify_builds(manifest, args.old_app, args.new_app)
    except BaseException as error:
        failure = error
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            write_json(output / "report.json", report)
        except BaseException as report_error:
            if failure is None:
                raise
            print(f"Secondary report write failure: {report_error}", file=sys.stderr)



if __name__ == "__main__":
    main()
