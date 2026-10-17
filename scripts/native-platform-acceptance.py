"""Real process acceptance with synthetic data; never uses credentials or media sites.

macOS launches the built .app executable with its normal native window. Linux
launches the source backend, so that result is explicitly not desktop parity.
Restart and backup restore are tested; neither is an application-version rollback.
The opt-in migration smoke runs the actual frozen helper on disposable data.
Its existing native Quit probe must prove Python shutdown ran; process exit alone
is not accepted as normal window-close or migration-UI acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
TEXT = "# Native platform fixture\n\n本地学习 café 日本語 🧭. Learning rate controls each update.\n"
PERSONAL = "个人批注 stays separate: café 日本語 🧭"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def isolated_environment(data, port):
    env = os.environ.copy()
    # Do not inherit optional providers or user-selected paths into this test.
    for key in list(env):
        if key.startswith(("LEARNNOTE_", "LLM_", "OPENAI_", "ANTHROPIC_")):
            env.pop(key)
    home = data.parent / (data.name + "-home")
    env.update(HOME=str(home), USERPROFILE=str(home), CFFIXED_USER_HOME=str(home),
               APPDATA=str(home / "appdata"), LOCALAPPDATA=str(home / "localappdata"),
               XDG_CONFIG_HOME=str(home / "config"), XDG_DATA_HOME=str(home / "data"),
               XDG_CACHE_HOME=str(home / "cache"), PYTHONNOUSERSITE="1",
               CLANG_MODULE_CACHE_PATH=str(home / "cache" / "clang"),
               SWIFT_MODULECACHE_PATH=str(home / "cache" / "swift"))
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONUSERBASE", None)
    env.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_BACKEND_ORIGIN=f"http://127.0.0.1:{port}",
               PYTHONPATH=str(ROOT / "backend"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               ORT_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_TELEMETRY="1")
    return env


class Api:
    def __init__(self, port):
        self.origin = f"http://127.0.0.1:{port}"
        self.session = requests.Session()
        self.session.trust_env = False

    def call(self, method, path, expected=200, **kwargs):
        if not path.startswith("/api/") and path not in ("/", "/health"):
            raise ValueError("Only local app paths are permitted")
        response = self.session.request(method, self.origin + path, timeout=20, allow_redirects=False, **kwargs)
        if response.status_code != expected:
            raise AssertionError(f"{method} {path}: {response.status_code}: {response.text[:1000]}")
        return response


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@contextmanager
def launched(executable, data, output, phase, port, arguments=()):
    command = ([str(executable), *arguments, "--port", str(port)] if executable else
               [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)])
    env = isolated_environment(data, port)
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    if executable:
        env.pop("PYTHONPATH", None)  # Frozen helpers must not import checkout code.
    with (output / f"{phase}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=executable.parent if executable else ROOT,
                                   env=env, stdout=log, stderr=log)
        api, failure = None, None
        try:
            api = Api(port)
            yield process, api
        except BaseException as error:
            failure = error
            raise
        finally:
            errors = []
            for cleanup in (lambda: api.session.close() if api else None, lambda: stop_process(process)):
                try:
                    cleanup()
                except BaseException as error:
                    errors.append(error)
            if errors:
                if failure is None:
                    raise errors[0]
                print(f"Secondary cleanup failures: {errors}", file=sys.stderr)


def capture_native_window(pid, output, phase):
    # Filter by the launched process, never capture another application or desktop.
    env = isolated_environment(output / "capture", 1)
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 60
    while True:
        result = subprocess.run(["swift", str(ROOT / "scripts/native-version-window.swift"), str(pid)],
                                env=env, check=True, capture_output=True, text=True, encoding="utf-8", timeout=30)
        windows = json.loads(result.stdout)
        if len(windows) == 1 and windows[0]["title"] == "LearnNote - Video Learning Notes":
            break
        if time.monotonic() >= deadline:
            raise AssertionError(f"{phase}: owned loaded window unavailable: {windows}")
        time.sleep(.25)
    window = windows[0]
    path = output / f"{phase}.png"
    subprocess.run(["screencapture", "-x", "-l", str(window["id"]), str(path)],
                   env=env, check=True, timeout=20)
    raw = path.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) > 24, "Native capture is not a PNG"
    return {"pid": pid, **window, "image": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "visual_review_required": True}


def await_ready(process, api, output, phase, *, native):
    deadline = time.monotonic() + 90
    while True:
        if process.poll() is not None:
            raise AssertionError(f"{phase}: process exited {process.returncode}; see log")
        try:
            health = api.call("GET", "/health").json()
            assert health["ok"] is True and health["service"] == "learnnote"
            break
        except requests.ConnectionError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{phase}: backend did not start")
            time.sleep(.25)
    assert 'LearnNote' in api.call("GET", "/").text
    if native:
        deadline = time.monotonic() + 30
        while not api.call("POST", "/api/desktop/focus", json={"view": "workspace"}).json().get("focused"):
            if time.monotonic() >= deadline:
                raise AssertionError("Native window did not become available")
            time.sleep(.5)
        capture = capture_native_window(process.pid, output, phase)
        write_json(output / f"{phase}-window.json", capture)
    return health


@contextmanager
def running(executable, data, output, phase):
    with launched(executable, data, output, phase, free_port()) as (process, api):
        health = await_ready(process, api, output, phase, native=bool(executable))
        yield api, health


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def assert_backup_annotation(backup, material_sha256):
    groups = backup["personal"]["annotations"]
    group = next(item for item in groups if item["key"] == f"material-{material_sha256}")
    assert len(group["items"]) == 1
    assert group["items"][0]["text"] == PERSONAL


def exercise(executable, output):
    checks = []
    with tempfile.TemporaryDirectory(prefix="learnnote-native-") as tmp:
        data = Path(tmp) / "synthetic-data"
        restored = Path(tmp) / "restored-data"
        with running(executable, data, output, "first-launch") as (api, health):
            checks.append("real_process_start_and_workspace")
            if executable:
                checks.append("native_window_focus_and_screenshot")
            imported = api.call("POST", "/api/library/materials/import", files={"file": ("native.md", TEXT.encode(), "text/markdown")}).json()
            material_id = imported["material"]["material_id"]
            prefix = f"/api/library/materials/{material_id}"
            assert "本地学习" in api.call("GET", prefix + "/content").json()["text"]
            original = api.call("GET", prefix + "/source").content
            assert original == TEXT.encode()
            checks.append("unicode_import_and_exact_original_export")
            api.call("GET", "/api/library/materials/nonexistent-native-fixture/content", expected=404)
            api.call("POST", "/api/library/materials/import", expected=422,
                     files={"file": ("broken.pdf", b"%PDF-1.4\ninvalid fixture", "application/pdf")})
            checks.append("missing_material_and_malformed_import_fail_closed")
            api.call("POST", f"/api/personal/material/{material_id}", json={"text": PERSONAL, "quote": "Learning rate"})
            backup = api.call("GET", "/api/study/backup").json()
            assert_backup_annotation(backup, imported["material"]["sha256"])
            (output / "synthetic-backup.json").write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
            checks.append("personal_note_backup_export")
        with running(executable, data, output, "restart") as (api, _):
            assert api.call("GET", prefix + "/source").content == TEXT.encode()
            assert api.call("GET", f"/api/personal/material/{material_id}").json()["annotations"][0]["text"] == PERSONAL
            checks.append("real_process_restart_preserves_material_and_personal_note")
        with running(executable, restored, output, "restore") as (api, _):
            # Learning backups carry annotations, not the original material bytes.
            # Reimporting the same original resolves its stable content identity.
            restored_material = api.call("POST", "/api/library/materials/import", files={"file": ("native.md", TEXT.encode(), "text/markdown")}).json()["material"]
            assert restored_material["sha256"] == imported["material"]["sha256"]
            restored_id = restored_material["material_id"]
            result = api.call("POST", "/api/study/backup/restore", json=backup).json()
            assert result["merge"]["restored_annotations"] == 1
            assert api.call("GET", f"/api/personal/material/{restored_id}").json()["annotations"][0]["text"] == PERSONAL
            checks.append("backup_restore_to_fresh_data_directory")
    return {"status": "pass", "platform": platform.platform(), "architecture": platform.machine(),
            "app_version": health["app_version"], "commit": os.getenv("GITHUB_SHA", "local"),
            "runtime": "unsigned_macos_native_app" if executable else "linux_source_backend",
            "fixture_sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "checks": checks,
            "not_tested": ["signing", "notarization", "version_upgrade_or_rollback", "credential_migration",
                           "extension_pairing", "remote_models", "real_media_sites"]}


def packaged_application_root(executable):
    # Match desktop.main.application_root, without importing a source launcher.
    resources = executable.parent.parent / "Resources" / "LearnNote"
    return resources if resources.is_dir() else executable.parent


@contextmanager
def copied_native_app(executable, output):
    temporary = tempfile.TemporaryDirectory(prefix=".native-migration-app-", dir=output)
    failure = None
    try:
        copied_app = Path(temporary.name).resolve() / "LearnNote.app"
        shutil.copytree(executable.parents[2], copied_app, symlinks=True)
        copied = copied_app / "Contents" / "MacOS" / "LearnNote"
        assert copied.resolve().is_relative_to(copied_app), "Executable escapes disposable bundle"
        assert hashlib.sha256(copied.read_bytes()).digest() == hashlib.sha256(executable.read_bytes()).digest()
        yield copied
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            temporary.cleanup()
        except BaseException as error:
            if failure is None:
                raise
            print(f"Secondary app cleanup failure: {error}", file=sys.stderr)


def assert_waiting(old, helper, app_root, target, request, previous):
    assert old.poll() is None, "Old native app exited before the wait gate"
    assert helper.poll() is None, "Frozen migration helper exited while waiting"
    assert (app_root / "learnnote-config.json").read_bytes() == previous, "Config activated before old app exit"
    assert not list(target.iterdir()), "Destination populated before old app exit"
    assert not (target.parent / (".learnnote-migration-" + request["token"])).exists(), "Staging began before old app exit"
    receipt = json.loads((app_root / ".data-migrations" / request["token"] / "receipt.json").read_bytes())
    assert receipt["status"] == "scheduled", "Migration advanced before old app exit"


def quit_native_app(process, executable, source, target, api, output):
    """Probe native Quit without equating an accepted request with graceful cleanup."""
    proof = {"pid": process.pid, "executable": str(executable.resolve()),
             "method": "NSRunningApplication.terminate", "status": "failed"}
    failure = None
    try:
        assert process.poll() is None, "Owned app exited before native Quit was requested"
        endpoint = source / ".desktop-session.json"
        assert endpoint.is_file(), "Source desktop session marker missing before Quit"
        result = subprocess.run(["swift", str(ROOT / "scripts/native-migration-quit.swift"),
                                 str(process.pid), str(executable.resolve())],
                                env=isolated_environment(source, 1), capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        proof.update(request_exit_code=result.returncode, request_stdout=result.stdout,
                     request_stderr=result.stderr)
        assert result.returncode == 0, "Verified owned native Quit request failed"
        request = json.loads(result.stdout)
        assert request == {"pid": process.pid, "executable": str(executable.resolve()), "quit_requested": True}
        proof["exit_code"] = process.wait(timeout=10)
        assert proof["exit_code"] == 0, "Owned native Quit did not exit successfully"
        marker = f"LearnNote Desktop closed. Data kept at {source}"
        proof["python_shutdown_marker"] = marker in (output / "old-app.log").read_text(encoding="utf-8").splitlines()
        proof["session_marker_removed"] = not endpoint.exists()
        # The helper may already have reused the port. A source-root backend is
        # never accepted as proof that the old backend shut down and switched.
        try:
            response = api.session.get(api.origin + "/health", timeout=2, allow_redirects=False)
        except requests.ConnectionError:
            proof["backend_after_exit"] = "unavailable"
        else:
            assert response.status_code == 200, "Backend closure could not be verified"
            backend_root = Path(response.json()["data_paths"]["root"])
            proof.update(backend_after_exit="destination", backend_root=str(backend_root))
            assert backend_root == target, "Source backend still available after native Quit"
        assert proof["python_shutdown_marker"], "Native Quit exited without the existing Python shutdown marker"
        assert proof["session_marker_removed"], "Native Quit did not remove the source desktop session marker"
        proof["status"] = "pass"
        return proof
    except BaseException as error:
        failure = error
        proof["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            write_json(output / "native-quit.json", proof)
        except BaseException as error:
            if failure is None:
                raise
            print(f"Secondary native Quit evidence failure: {error}", file=sys.stderr)


def migration_exports(api, material, output, phase):
    prefix = f'/api/library/materials/{material["material_id"]}'
    raw = api.call("GET", prefix + "/source").content
    assert raw == TEXT.encode(), "Original material bytes changed"
    content = api.call("GET", prefix + "/content").json()["text"]
    assert "本地学习" in content
    annotations = api.call("GET", f'/api/personal/material/{material["material_id"]}').json()["annotations"]
    assert len(annotations) == 1 and annotations[0]["text"] == PERSONAL
    backup = api.call("GET", "/api/study/backup").json()
    assert_backup_annotation(backup, material["sha256"])
    (output / f"{phase}-original.md").write_bytes(raw)
    evidence = {"material_id": material["material_id"], "source_sha256": hashlib.sha256(raw).hexdigest(),
                "content": content, "annotations": annotations, "personal_export": backup["personal"]}
    write_json(output / f"{phase}-exports.json", evidence)
    return evidence


def migration_smoke(executable, output):
    if sys.platform != "darwin" or not executable:
        raise ValueError("Packaged migration evidence requires a native macOS app")
    # Only the external harness imports the production mapper from this checkout.
    # Both native processes run the same copied frozen executable, without source paths.
    sys.path.insert(0, str(ROOT))
    from desktop.data_migration import preview_migration, prepare_request
    from desktop.data_migration_inventory import inventory, same_snapshot

    output = output.resolve() / "migration-smoke"
    output.mkdir()  # A previous attempt must not be overwritten or silently reused.
    source, target = output / "source", output / "destination"
    source.mkdir()
    target.mkdir()
    with copied_native_app(executable, output) as copied:
        copied_app = copied.parents[2]
        app_root = packaged_application_root(copied)
        assert app_root.resolve().is_relative_to(copied_app), "App root escapes disposable bundle"
        assert not (app_root / "learnnote-config.json").exists(), "Expected a fresh unsigned build without config"
        assert not (app_root / ".data-migrations").exists(), "Expected a build without migration requests"
        previous = json.dumps({"data_dir": str(source), "synthetic_marker": "preserve café 日本語"},
                              ensure_ascii=False, indent=2).encode()
        (app_root / "learnnote-config.json").write_bytes(previous)
        (output / "previous-config.bin").write_bytes(previous)
        failure = None
        try:
            port = free_port()
            with launched(copied, source, output, "old-app", port) as (old, api):
                health = await_ready(old, api, output, "old-app", native=True)
                assert Path(health["data_paths"]["root"]) == source
                material = api.call("POST", "/api/library/materials/import",
                    files={"file": ("native.md", TEXT.encode(), "text/markdown")}).json()["material"]
                api.call("POST", f'/api/personal/material/{material["material_id"]}',
                         json={"text": PERSONAL, "quote": "Learning rate"})
                before = migration_exports(api, material, output, "before")
                plan = preview_migration(source, target, app_root)
                request = prepare_request(app_root, plan)
                write_json(output / "before-inventory.json", plan["snapshot"])
                arguments = ["--apply-data-migration", request["token"], "--migration-digest", request["digest"],
                             "--wait-for-parent", str(old.pid)]
                with launched(copied, source, output, "migration-helper", port, arguments) as (helper, migrated):
                    started = time.monotonic()
                    while time.monotonic() - started < 3:
                        assert_waiting(old, helper, app_root, target, request, previous)
                        time.sleep(.1)
                    write_json(output / "wait-gate.json", {"old_pid": old.pid, "helper_pid": helper.pid,
                        "seconds": time.monotonic() - started, "status": "scheduled", "stage_absent": True,
                        "config_unchanged": True, "destination_empty": True, "helper_arguments": arguments,
                        "executable_sha256": hashlib.sha256(copied.read_bytes()).hexdigest()})
                    quit_native_app(old, copied, source, target, api, output)
                    # The native Quit probe reaps the old PID only after verified cleanup.
                    stopped = inventory(source)
                    write_json(output / "stopped-source-inventory.json", stopped)
                    assert same_snapshot(plan["snapshot"], stopped), "Stopping the old process changed durable source data"
                    health = await_ready(helper, migrated, output, "migration-helper", native=True)
                    # Environment still names source: only persisted config may select destination.
                    assert Path(health["data_paths"]["root"]) == target, "Helper backend did not switch to persisted destination"
                    assert health["data_paths"]["all_under_data_dir"] is True
                    write_json(output / "restarted-backend.json", {"pid": helper.pid,
                        "app_version": health["app_version"], "data_paths": health["data_paths"]})
                    assert migration_exports(migrated, material, output, "after") == before, "Migration changed material or annotation exports"
                    active = json.loads((app_root / "learnnote-config.json").read_bytes())
                    assert active == {**json.loads(previous), "data_dir": str(target)}
                    receipt_dir = app_root / ".data-migrations" / request["token"]
                    assert (receipt_dir / "previous-config.bin").read_bytes() == previous
                    receipt = json.loads((receipt_dir / "receipt.json").read_bytes())
                    assert receipt["status"] == "complete", "Frozen helper did not complete migration"
            after = inventory(source)
            write_json(output / "after-inventory.json", after)
            assert same_snapshot(plan["snapshot"], after), "Migration changed durable source bytes, names or mtimes"
            return {"status": "pass", "runtime": "unsigned_macos_native_app", "old_pid": old.pid,
                    "helper_pid": helper.pid, "request_token": request["token"],
                    "not_tested": ["native_window_close", "migration_settings_bridge"],
                    "checks": ["live_parent_blocks_staging_and_activation", "native_quit_reaches_python_shutdown",
                               "frozen_helper_migration_and_native_restart",
                               "persisted_destination_backend", "exact_material_and_annotation_exports",
                               "unchanged_durable_source_inventory", "previous_config_and_receipt_preserved"]}
        except BaseException as error:
            failure = error
            raise
        finally:
            # Persist the exact app-owned transaction before the disposable bundle is removed.
            # Source/destination/staging already live under output, including on failure.
            try:
                archive = output / "app-root"
                archive.mkdir()
                for name in ("learnnote-config.json", ".data-migrations", "startup-error.log"):
                    path = app_root / name
                    if path.is_dir():
                        shutil.copytree(path, archive / name.lstrip("."))
                    elif path.exists():
                        shutil.copy2(path, archive / name)
            except BaseException as error:
                if failure is None:
                    raise
                print(f"Secondary migration archive failure: {error}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--migration-smoke", action="store_true", help="Verify native Quit cleanup, frozen migration helper and restart")
    args = parser.parse_args()
    if args.migration_smoke and not args.app:
        parser.error("--migration-smoke requires --app on a native macOS host")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = None
    if args.app:
        if sys.platform != "darwin":
            parser.error("--app requires an actual macOS host")
        executable = args.app.resolve() / "Contents/MacOS/LearnNote"
        if not executable.is_file():
            parser.error(f"Missing packaged executable: {executable}")
        app_root = packaged_application_root(executable)
        if any((app_root / name).exists() for name in ("learnnote-config.json", ".data-migrations")):
            parser.error("Acceptance requires a fresh built app without stored config or migration requests")
    report = {"status": "failed", "commit": os.getenv("GITHUB_SHA", "local")}
    failure = None
    try:
        report = exercise(executable, output)
        if args.migration_smoke:
            report["migration"] = migration_smoke(executable, output)
        else:
            report["not_tested"].append("packaged_data_migration")
    except BaseException as error:
        failure = error
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            write_json(output / "report.json", report)
        except BaseException as error:
            if failure is None:
                raise
            print(f"Secondary report failure: {error}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
