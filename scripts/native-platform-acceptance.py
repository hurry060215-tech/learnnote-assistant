"""Real process acceptance with synthetic data; never uses credentials or media sites.

macOS launches the built .app executable with its normal native window. Linux
launches the source backend, so that result is explicitly not desktop parity.
Restart and backup restore are tested; neither is an application-version rollback.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
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


@contextmanager
def running(executable, data, output, phase):
    port = free_port()
    command = ([str(executable), "--port", str(port)] if executable else
               [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)])
    with (output / f"{phase}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=isolated_environment(data, port), stdout=log, stderr=log)
        api = Api(port)
        try:
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
                    time.sleep(0.25)
            assert 'LearnNote' in api.call("GET", "/").text
            if executable:
                # This callback exists only after native window creation.
                deadline = time.monotonic() + 30
                while True:
                    result = api.call("POST", "/api/desktop/focus", json={"view": "workspace"}).json()
                    if result.get("focused"):
                        break
                    if time.monotonic() >= deadline:
                        raise AssertionError("Native window did not become available")
                    time.sleep(0.5)
                time.sleep(3)
                subprocess.run(["screencapture", "-x", str(output / f"{phase}.png")], check=True)
            yield api, health
        finally:
            api.session.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


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
            assert backup["personal"]["annotations"][0]["text"] == PERSONAL
            (output / "synthetic-backup.json").write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
            checks.append("personal_note_backup_export")
        with running(executable, data, output, "restart") as (api, _):
            assert api.call("GET", prefix + "/source").content == TEXT.encode()
            assert api.call("GET", f"/api/personal/material/{material_id}").json()["annotations"][0]["text"] == PERSONAL
            checks.append("real_process_restart_preserves_material_and_personal_note")
        with running(executable, restored, output, "restore") as (api, _):
            result = api.call("POST", "/api/study/backup/restore", json=backup).json()
            assert result["merge"]["restored_annotations"] == 1
            assert api.call("GET", f"/api/personal/material/{material_id}").json()["annotations"][0]["text"] == PERSONAL
            checks.append("backup_restore_to_fresh_data_directory")
    return {"status": "pass", "platform": platform.platform(), "architecture": platform.machine(),
            "app_version": health["app_version"], "commit": os.getenv("GITHUB_SHA", "local"),
            "runtime": "unsigned_macos_native_app" if executable else "linux_source_backend",
            "fixture_sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "checks": checks,
            "not_tested": ["signing", "notarization", "version_upgrade_or_rollback", "credential_migration",
                           "extension_pairing", "remote_models", "real_media_sites"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = None
    if args.app:
        if sys.platform != "darwin":
            parser.error("--app requires an actual macOS host")
        executable = args.app.resolve() / "Contents/MacOS/LearnNote"
        if not executable.is_file():
            parser.error(f"Missing packaged executable: {executable}")
    report = {"status": "failed", "commit": os.getenv("GITHUB_SHA", "local")}
    try:
        report = exercise(executable, output)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
