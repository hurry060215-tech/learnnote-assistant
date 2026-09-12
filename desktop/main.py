from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from zipfile import ZipFile

import requests
import uvicorn

from desktop.credentials import delete_secret, read_secret, write_secret
from desktop.startup import DesktopSession, backend_ready, protocol_port, wait_for_process_exit

MODEL_PROVIDER_KEY_URLS = {
    "openai": "https://platform.openai.com/api-keys",
    "groq": "https://console.groq.com/keys",
    "gemini": "https://aistudio.google.com/app/apikey",
    "dashscope": "https://bailian.console.aliyun.com/?apiKey=1",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "kimi": "https://platform.kimi.com/console/api-keys",
    "xiaomi": "https://platform.xiaomimimo.com/",
    "zhipu": "https://open.bigmodel.cn/usercenter/apikeys",
    "doubao": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    "minimax": "https://platform.minimaxi.com/console/access?tab=api-keys",
    "qianfan": "https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application",
}


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/hurry060215-tech/learnnote-assistant/releases/latest"
GITHUB_LATEST_RELEASE_PAGE = "https://github.com/hurry060215-tech/learnnote-assistant/releases/latest"
GITHUB_RELEASE_BASE = "https://github.com/hurry060215-tech/learnnote-assistant/releases"
WINDOWS_INSTALLER_NAME = "LearnNote-Setup-x64.exe"
EXTENSION_ASSET_PREFIX = "LearnNote-Browser-Extension-v"
EXTENSION_ASSET_SUFFIX = ".zip"
MAX_UPDATE_BYTES = 500 * 1024 * 1024


class _UpdateCancelled(Exception):
    pass


def supported_browser() -> tuple[Path | None, str]:
    candidates = [
        (Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe", "chrome"),
        (Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe", "chrome"),
        (Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe", "chrome"),
        (Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe", "edge"),
        (Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe", "edge"),
    ]
    for candidate, name in candidates:
        if candidate.is_file():
            return candidate, name
    for executable, name in (("chrome", "chrome"), ("msedge", "edge")):
        resolved = shutil.which(executable)
        if resolved:
            return Path(resolved), name
    return None, ""


class DesktopApi:
    EXPORT_TYPES = {
        "markdown": ".md",
        "bundle": ".zip",
        "sanitized-bundle": ".zip",
        "support-package": ".zip",
        "notion": ".json",
        "docx": ".docx",
        "pdf": ".pdf",
        "manifest": ".json",
        "diagnostics": ".md",
        "visual-windows": ".json",
        "subtitles": ".srt",
        "media": ".mp4",
        "audit": ".md",
        "qa": ".json",
        "resource-inventory": ".json",
        "page-preflight-report": ".json",
    }

    def __init__(self, data_dir: Path, backend_url: str = "", app_root: Path | None = None):
        self.data_dir = data_dir
        self.app_root = (app_root or data_dir.parent).resolve()
        self.backend_url = backend_url.rstrip("/") or os.getenv("LEARNNOTE_BACKEND_ORIGIN", "http://127.0.0.1:8765").rstrip("/")
        self._window = None
        self._update_lock = threading.RLock()
        self._update_cancel = threading.Event()
        self._update_thread = None
        self._update_result = None
        self._update_state = {"phase": "idle", "version": "", "downloaded_bytes": 0, "total_bytes": 0, "progress": 0, "error": ""}
        self._extension_update_cancel = threading.Event()
        self._extension_update_thread = None
        self._extension_update_state = {"phase": "idle", "version": "", "downloaded_bytes": 0, "total_bytes": 0, "progress": 0, "error": ""}

    def _bind_window(self, window) -> None:
        self._window = window

    def save_model_key(self, provider: str, api_key: str) -> dict:
        write_secret(provider, api_key)
        return {"ok": True, "provider": provider}

    def load_model_key(self, provider: str) -> dict:
        value = read_secret(provider)
        return {"ok": True, "provider": provider, "api_key": value, "configured": bool(value)}

    def delete_model_key(self, provider: str) -> dict:
        return {"ok": True, "provider": provider, "deleted": delete_secret(provider)}

    def open_model_provider(self, provider: str) -> dict:
        normalized = str(provider or "").strip().lower()
        url = MODEL_PROVIDER_KEY_URLS.get(normalized, "")
        if not url:
            raise ValueError("Unsupported model provider")
        webbrowser.open(url)
        return {"ok": True, "provider": normalized, "url": url}

    def open_data_folder(self) -> dict:
        open_local_path(self.data_dir)
        return {"ok": True}

    def setup_browser_extension(self, loaded_version: str = "") -> dict:
        extension_dir = (self.app_root / "extension").resolve()
        manifest_path = extension_dir / "manifest.json"
        if not manifest_path.is_file():
            return {
                "ok": False,
                "code": "extension_files_missing",
                "message": "客户端缺少浏览器扩展文件，请先更新或重新安装 LearnNote。",
            }
        browser_path, browser_name = supported_browser()
        if browser_path is None:
            return {
                "ok": False,
                "code": "browser_not_found",
                "path": str(extension_dir),
                "message": "没有找到 Chrome 或 Edge。请打开浏览器扩展管理页后加载此目录。",
            }
        management_url = "edge://extensions" if browser_name == "edge" else "chrome://extensions"
        subprocess.Popen(
            [str(browser_path), management_url],
            cwd=str(self.app_root),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        open_local_path(extension_dir)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        installed_version = str(manifest.get("version") or "").strip()
        loaded_version = str(loaded_version or "").strip()
        requires_reload = bool(loaded_version and installed_version and loaded_version != installed_version)
        message = (
            f"扩展管理页已打开。LearnNote 扩展文件已更新到 v{installed_version}，"
            "请在扩展卡片上点击“重新加载”，然后刷新视频页面。"
            if requires_reload
            else "扩展页和安装目录已打开。首次使用请开启开发者模式，点击“加载已解压的扩展程序”，选择 extension 文件夹；已加载过则点击“重新加载”。"
        )
        return {
            "ok": True,
            "browser": browser_name,
            "path": str(extension_dir),
            "version": installed_version,
            "installed_version": installed_version,
            "loaded_version": loaded_version,
            "requires_reload": requires_reload,
            "message": message,
        }

    def choose_data_directory(self, migrate: bool = True) -> dict:
        if self._window is None:
            return {"ok": False, "code": "desktop_window_unavailable", "message": "客户端窗口尚未就绪。"}
        import webview

        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(self.data_dir.parent))
        if not selected:
            return {"ok": False, "cancelled": True}
        raw_path = selected[0] if isinstance(selected, (list, tuple)) else selected
        target = Path(str(raw_path)).expanduser().resolve()
        if target.drive.upper() == "C:":
            return {"ok": False, "code": "system_drive_not_allowed", "message": "请选择 D 盘或其他非系统盘。"}
        if target == self.data_dir.resolve():
            return {"ok": True, "unchanged": True, "path": str(target)}
        if self.data_dir.resolve() in target.parents:
            return {"ok": False, "code": "nested_data_directory", "message": "新位置不能放在当前数据目录里面。"}
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".learnnote-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError:
            return {"ok": False, "code": "directory_not_writable", "message": "所选文件夹无法写入，请换一个位置。"}

        if migrate:
            try:
                response = requests.get(f"{self.backend_url}/api/tasks", timeout=3.0)
                payload = response.json() if response.ok else []
                task_items = payload.get("tasks", []) if isinstance(payload, dict) else payload
                if not isinstance(task_items, list):
                    task_items = []
                running = [
                    task for task in task_items
                    if isinstance(task, dict) and task.get("status") in {"queued", "running", "cancelling"}
                ]
            except (requests.RequestException, TypeError, ValueError):
                running = []
            if running:
                return {"ok": False, "code": "tasks_running", "message": "还有任务正在处理，请完成或停止任务后再迁移。"}
            try:
                shutil.copytree(
                    self.data_dir,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("webview-profile", "temp", "*.lock", ".desktop-session.*"),
                )
            except OSError as exc:
                return {"ok": False, "code": "migration_failed", "message": f"迁移没有完成：{exc}"}

        config_path = self.app_root / "learnnote-config.json"
        temp_path = config_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps({"data_dir": str(target)}, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(config_path)
        return {
            "ok": True,
            "path": str(target),
            "migrated": bool(migrate),
            "restart_required": True,
            "message": "现有数据已迁移，重启客户端后使用新位置。" if migrate else "新位置已保存，重启客户端后生效。",
        }

    def restart_application(self) -> dict:
        command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
        command.extend(["--wait-for-parent", str(os.getpid()), "--port", str(urlparse(self.backend_url).port or 8765)])
        subprocess.Popen(command, cwd=str(self.app_root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if self._window is not None:
            threading.Timer(0.35, self._window.destroy).start()
        return {"ok": True}

    def export_task(self, task_id: str, export_type: str) -> dict:
        task_id = str(task_id or "").strip()
        export_type = str(export_type or "").strip().lower()
        clip_match = re.fullmatch(r"clips/(W\d{3})", export_type)
        if not re.fullmatch(r"[a-f0-9]{12}", task_id) or (export_type not in self.EXPORT_TYPES and not clip_match):
            raise ValueError("Unsupported task export")
        fallback_suffix = ".mp4" if clip_match else self.EXPORT_TYPES[export_type]

        response = requests.get(
            f"{self.backend_url}/api/tasks/{task_id}/exports/{export_type}",
            stream=True,
            timeout=(5.0, 180.0),
        )
        response.raise_for_status()
        disposition = response.headers.get("Content-Disposition", "")
        filename_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.I)
        if not filename_match:
            filename_match = re.search(r'filename="?([^";]+)', disposition, flags=re.I)
        filename = unquote(filename_match.group(1)) if filename_match else f"{task_id}-{export_type.replace('/', '-')}{fallback_suffix}"
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", Path(filename).name).strip(" .")
        if not filename:
            filename = f"{task_id}-{export_type.replace('/', '-')}{fallback_suffix}"

        export_dir = (self.data_dir / "exports").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        target = (export_dir / filename).resolve()
        if target.parent != export_dir:
            raise ValueError("Unsafe export filename")
        stem, suffix = target.stem, target.suffix
        index = 2
        while target.exists():
            target = export_dir / f"{stem} ({index}){suffix}"
            index += 1
        with target.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
        return {"ok": True, "path": str(target), "filename": target.name, "bytes": target.stat().st_size}

    def open_export_folder(self) -> dict:
        export_dir = self.data_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        open_local_path(export_dir)
        return {"ok": True, "path": str(export_dir)}

    def get_release_notes(self, version: str = "") -> dict:
        notes_path = bundled_root() / "web" / "release-notes.json"
        if not notes_path.is_file():
            notes_path = self.app_root / "web" / "release-notes.json"
        try:
            payload = json.loads(notes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"ok": False, "message": f"无法读取版本更新说明：{exc}"}

        requested = str(version or payload.get("current") or "").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", requested):
            return {"ok": False, "message": "版本号无效"}
        note = next(
            (item for item in payload.get("releases") or [] if str(item.get("version") or "") == requested),
            None,
        )
        if not isinstance(note, dict):
            return {"ok": False, "message": f"没有找到 v{requested} 的更新说明"}

        state_path = self.data_dir / "config" / "release-notes.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        except (OSError, ValueError):
            state = {}
        return {
            "ok": True,
            "note": note,
            "seen": str(state.get("seen_version") or "") == requested,
        }

    def mark_release_notes_seen(self, version: str) -> dict:
        version = str(version or "").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid release-notes version")
        state_path = self.data_dir / "config" / "release-notes.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"seen_version": version, "seen_at": int(time.time())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(state_path)
        return {"ok": True, "seen_version": version}

    def check_update(self) -> dict:
        try:
            response = requests.get(
                GITHUB_LATEST_RELEASE_API,
                timeout=4.0,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
            tag = str(payload.get("tag_name") or "").lstrip("v")
            url = str(payload.get("html_url") or "")
            installer = next(
                (asset for asset in payload.get("assets") or [] if asset.get("name") == WINDOWS_INSTALLER_NAME),
                {},
            )
            digest = str(installer.get("digest") or "")
            sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
            installer_url = str(installer.get("browser_download_url") or "")
            installable = bool(
                re.fullmatch(r"\d+\.\d+\.\d+", tag)
                and re.fullmatch(r"[a-fA-F0-9]{64}", sha256)
                and self._valid_installer_url(tag, installer_url)
            )
            result = {
                "ok": True,
                "latest_version": tag,
                "release_url": url,
                "installer_url": installer_url if installable else "",
                "installer_sha256": sha256.lower() if installable else "",
                "installable": installable,
            }
            return result if installable else self._check_update_without_api()
        except (requests.RequestException, ValueError):
            try:
                return self._check_update_without_api()
            except (requests.RequestException, ValueError) as exc:
                return {"ok": False, "message": str(exc)}

    def _check_update_without_api(self) -> dict:
        release = requests.get(
            GITHUB_LATEST_RELEASE_PAGE,
            timeout=8.0,
            allow_redirects=True,
            headers={"User-Agent": "LearnNote-Desktop-Updater"},
        )
        release.raise_for_status()
        match = re.fullmatch(
            r"https://github\.com/hurry060215-tech/learnnote-assistant/releases/tag/v(\d+\.\d+\.\d+)/?",
            str(release.url or ""),
        )
        if not match:
            raise ValueError("GitHub latest release redirect is invalid")
        version = match.group(1)
        asset_base = f"{GITHUB_RELEASE_BASE}/download/v{version}"
        checksums = requests.get(
            f"{asset_base}/SHA256SUMS.txt",
            timeout=8.0,
            headers={"User-Agent": "LearnNote-Desktop-Updater"},
        )
        checksums.raise_for_status()
        checksum_match = re.search(
            rf"(?mi)^([a-f0-9]{{64}})\s+\*?{re.escape(WINDOWS_INSTALLER_NAME)}\s*$",
            checksums.text,
        )
        if not checksum_match:
            raise ValueError("Release checksum file does not contain the Windows installer")
        installer_url = f"{asset_base}/{WINDOWS_INSTALLER_NAME}"
        return {
            "ok": True,
            "latest_version": version,
            "release_url": f"{GITHUB_RELEASE_BASE}/tag/v{version}",
            "installer_url": installer_url,
            "installer_sha256": checksum_match.group(1).lower(),
            "installable": True,
        }

    @staticmethod
    def _valid_installer_url(version: str, url: str) -> bool:
        parsed = urlparse(str(url or ""))
        expected_path = f"/hurry060215-tech/learnnote-assistant/releases/download/v{version}/{WINDOWS_INSTALLER_NAME}"
        return parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path == expected_path and not parsed.query

    @staticmethod
    def _valid_extension_url(version: str, url: str) -> bool:
        parsed = urlparse(str(url or ""))
        expected_path = f"/hurry060215-tech/learnnote-assistant/releases/download/v{version}/{EXTENSION_ASSET_PREFIX}{version}{EXTENSION_ASSET_SUFFIX}"
        return parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path == expected_path and not parsed.query and not parsed.fragment

    def download_update(self, version: str, url: str, sha256: str) -> dict:
        return self._download_update(version, url, sha256)

    def _download_update(self, version: str, url: str, sha256: str, progress=None, cancel_event=None) -> dict:
        version = str(version or "").strip()
        sha256 = str(sha256 or "").strip().lower()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not self._valid_installer_url(version, url):
            raise ValueError("Unsupported update installer URL")
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("Invalid update checksum")

        update_dir = (self.data_dir / "installers" / f"v{version}").resolve()
        update_dir.mkdir(parents=True, exist_ok=True)
        target = (update_dir / WINDOWS_INSTALLER_NAME).resolve()
        partial = target.with_suffix(".download")
        if target.parent != update_dir or partial.parent != update_dir:
            raise ValueError("Unsafe update path")

        if target.is_file() and target.stat().st_size <= MAX_UPDATE_BYTES:
            cached_digest = hashlib.sha256()
            with target.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    cached_digest.update(chunk)
            if cached_digest.hexdigest() == sha256:
                if progress:
                    progress(target.stat().st_size, target.stat().st_size)
                return {
                    "ok": True,
                    "path": str(target),
                    "version": version,
                    "bytes": target.stat().st_size,
                    "sha256": sha256,
                    "cached": True,
                }
            target.unlink()

        response = requests.get(
            url,
            stream=True,
            timeout=(5.0, 300.0),
            headers={"Accept": "application/octet-stream", "User-Agent": "LearnNote-Desktop-Updater"},
        )
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length > MAX_UPDATE_BYTES:
            raise ValueError("Update installer is unexpectedly large")

        digest = hashlib.sha256()
        written = 0
        try:
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if cancel_event is not None and cancel_event.is_set():
                        raise _UpdateCancelled()
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_UPDATE_BYTES:
                        raise ValueError("Update installer is unexpectedly large")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(written, content_length)
            if digest.hexdigest() != sha256:
                raise ValueError("Update installer checksum mismatch")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return {"ok": True, "path": str(target), "version": version, "bytes": written, "sha256": sha256}

    def _current_update_versions(self) -> tuple[str, str]:
        extension_version = ""
        manifest_path = self.app_root / "extension" / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            extension_version = str(manifest.get("version") or "").strip()
        except (OSError, ValueError):
            pass
        client_version = extension_version
        notes_path = self.app_root / "web" / "release-notes.json"
        try:
            notes = json.loads(notes_path.read_text(encoding="utf-8"))
            client_version = str(notes.get("current") or client_version).strip()
        except (OSError, ValueError):
            pass
        return client_version, extension_version

    def update_status(self, force: bool = False) -> dict:
        try:
            response = requests.get(
                f"{self.backend_url}/api/update/status",
                params={"force": "true" if force else "false"},
                timeout=4.0,
            )
            response.raise_for_status()
            result = response.json()
            client_version, extension_version = self._current_update_versions()
            result.setdefault("current", {}).setdefault("client_version", client_version)
            if not result.get("current", {}).get("extension_version"):
                result.setdefault("current", {})["extension_version"] = extension_version
            with self._update_lock:
                result["download"] = dict(self._update_state)
                result["extension_download"] = dict(self._extension_update_state)
                self._update_result = {
                    "ok": bool(result.get("ok")),
                    "latest_version": str((result.get("latest") or {}).get("version") or ""),
                    "release_url": str((result.get("latest") or {}).get("release_url") or ""),
                    "installer_url": str(((result.get("latest") or {}).get("client") or {}).get("url") or ""),
                    "installer_sha256": str(((result.get("latest") or {}).get("client") or {}).get("sha256") or ""),
                    "installable": bool(((result.get("latest") or {}).get("client") or {}).get("installable")),
                }
            return result
        except (requests.RequestException, ValueError, TypeError):
            pass
        with self._update_lock:
            if force or self._update_result is None:
                self._update_result = self.check_update()
            result = dict(self._update_result)
            state = dict(self._update_state)
            extension_state = dict(self._extension_update_state)
        client_version, extension_version = self._current_update_versions()
        latest = str(result.get("latest_version") or "")
        return {
            "ok": bool(result.get("ok")),
            "current": {"client_version": client_version, "extension_version": extension_version},
            "latest": {
                "version": latest,
                "release_url": result.get("release_url", ""),
                "client": {
                    "url": result.get("installer_url", ""),
                    "sha256": result.get("installer_sha256", ""),
                    "installable": bool(result.get("installable")),
                },
            } if latest else None,
            "client_update_available": bool(latest and latest != client_version and self._version_is_newer(latest, client_version)),
            "extension": {
                "current_version": extension_version,
                "compatibility": "compatible" if extension_version == client_version else "version_check_pending",
                "channel": "browser_store_or_managed_unpack",
                "store_update": "browser_managed",
            },
            "download": state,
            "extension_download": extension_state,
        }

    @staticmethod
    def _version_is_newer(candidate: str, current: str) -> bool:
        try:
            left = tuple(int(part) for part in candidate.split("."))
            right = tuple(int(part) for part in current.split("."))
        except (AttributeError, ValueError):
            return False
        return len(left) == len(right) == 3 and left > right

    def start_update_download(self, version: str, url: str, sha256: str) -> dict:
        with self._update_lock:
            if self._update_thread and self._update_thread.is_alive():
                return {"ok": True, **self._update_state}
            self._update_cancel.clear()
            self._update_state = {"phase": "downloading", "version": str(version), "downloaded_bytes": 0, "total_bytes": 0, "progress": 0, "error": ""}

            def progress(downloaded: int, total: int | None) -> None:
                with self._update_lock:
                    self._update_state.update({
                        "downloaded_bytes": downloaded,
                        "total_bytes": int(total or 0),
                        "progress": round(downloaded / total * 100, 2) if total else 0,
                    })

            def worker() -> None:
                try:
                    result = self._download_update(version, url, sha256, progress, self._update_cancel)
                    with self._update_lock:
                        self._update_state.update({"phase": "ready", "progress": 100, "path": result["path"], "sha256": result["sha256"]})
                except _UpdateCancelled:
                    with self._update_lock:
                        self._update_state.update({"phase": "cancelled", "error": ""})
                except Exception as exc:
                    with self._update_lock:
                        self._update_state.update({"phase": "failed", "error": str(exc)})

            self._update_thread = threading.Thread(target=worker, name="learnnote-update-download", daemon=True)
            self._update_thread.start()
            return {"ok": True, **self._update_state}

    def cancel_update_download(self) -> dict:
        with self._update_lock:
            if self._update_thread and self._update_thread.is_alive():
                self._update_cancel.set()
                self._update_state["phase"] = "cancelling"
            return {"ok": True, **self._update_state}

    def download_extension_update(self, version: str, url: str, sha256: str, cancel_event=None, progress=None) -> dict:
        version = str(version or "").strip()
        sha256 = str(sha256 or "").strip().lower()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not self._valid_extension_url(version, url):
            raise ValueError("Unsupported extension update URL")
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("Invalid extension checksum")
        update_dir = (self.data_dir / "extension-updates" / f"v{version}").resolve()
        update_dir.mkdir(parents=True, exist_ok=True)
        target = (update_dir / f"{EXTENSION_ASSET_PREFIX}{version}{EXTENSION_ASSET_SUFFIX}").resolve()
        partial = target.with_suffix(".download")
        if target.parent != update_dir or partial.parent != update_dir:
            raise ValueError("Unsafe extension update path")
        if target.is_file():
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest == sha256:
                if progress:
                    progress(target.stat().st_size, target.stat().st_size)
                return {"ok": True, "path": str(target), "version": version, "bytes": target.stat().st_size, "sha256": sha256, "cached": True}
            target.unlink()
        response = requests.get(
            url,
            stream=True,
            timeout=(5.0, 180.0),
            headers={"Accept": "application/zip", "User-Agent": "LearnNote-Desktop-Updater"},
        )
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length > MAX_UPDATE_BYTES:
            raise ValueError("Extension update package is unexpectedly large")
        digest = hashlib.sha256()
        written = 0
        try:
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if cancel_event is not None and cancel_event.is_set():
                        raise _UpdateCancelled()
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_UPDATE_BYTES:
                        raise ValueError("Extension update package is unexpectedly large")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(written, content_length)
            if digest.hexdigest() != sha256:
                raise ValueError("Extension update checksum mismatch")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return {"ok": True, "path": str(target), "version": version, "bytes": written, "sha256": sha256}

    def start_extension_update_download(self, version: str, url: str, sha256: str) -> dict:
        with self._update_lock:
            if self._extension_update_thread and self._extension_update_thread.is_alive():
                return {"ok": True, **self._extension_update_state}
            self._extension_update_cancel.clear()
            self._extension_update_state = {"phase": "downloading", "version": str(version), "downloaded_bytes": 0, "total_bytes": 0, "progress": 0, "error": ""}

            def progress(downloaded: int, total: int | None) -> None:
                with self._update_lock:
                    self._extension_update_state.update({
                        "downloaded_bytes": downloaded,
                        "total_bytes": int(total or 0),
                        "progress": round(downloaded / total * 100, 2) if total else 0,
                    })

            def worker() -> None:
                try:
                    result = self.download_extension_update(version, url, sha256, self._extension_update_cancel, progress)
                    with self._update_lock:
                        self._extension_update_state.update({"phase": "ready", "progress": 100, "path": result["path"], "sha256": result["sha256"], "downloaded_bytes": result["bytes"], "total_bytes": result["bytes"]})
                except _UpdateCancelled:
                    with self._update_lock:
                        self._extension_update_state.update({"phase": "cancelled", "error": ""})
                except Exception as exc:
                    with self._update_lock:
                        self._extension_update_state.update({"phase": "failed", "error": str(exc)})

            self._extension_update_thread = threading.Thread(target=worker, name="learnnote-extension-update-download", daemon=True)
            self._extension_update_thread.start()
            return {"ok": True, **self._extension_update_state}

    def cancel_extension_update_download(self) -> dict:
        with self._update_lock:
            if self._extension_update_thread and self._extension_update_thread.is_alive():
                self._extension_update_cancel.set()
                self._extension_update_state["phase"] = "cancelling"
            return {"ok": True, **self._extension_update_state}

    def install_extension_update(self, version: str, archive_path: str, sha256: str = "") -> dict:
        version = str(version or "").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid extension update version")
        if not getattr(sys, "frozen", False):
            raise RuntimeError("源码开发环境不会自动覆盖 extension 目录，请手动测试或使用候选安装包。")
        update_dir = (self.data_dir / "extension-updates" / f"v{version}").resolve()
        archive = Path(str(archive_path or "")).resolve()
        expected_path = update_dir / f"{EXTENSION_ASSET_PREFIX}{version}{EXTENSION_ASSET_SUFFIX}"
        if archive != expected_path or not archive.is_file():
            raise ValueError("Extension update package is not ready")
        expected = str(sha256 or "").strip().lower()
        if expected:
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if not re.fullmatch(r"[a-f0-9]{64}", expected) or digest != expected:
                raise RuntimeError("扩展更新包已变化或校验失败，原扩展未改变。")
        stage = (self.data_dir / "extension-staging" / f"v{version}").resolve()
        if stage.parent != (self.data_dir / "extension-staging").resolve():
            raise ValueError("Unsafe extension staging path")
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        allowed = {"manifest.json", "background.js", "content.js", "page_hook.js", "sidepanel.html", "sidepanel.css", "sidepanel.js", "INSTALL.txt", "icons"}
        with ZipFile(archive) as package:
            for info in package.infolist():
                name = Path(info.filename.replace("/", os.sep))
                if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] not in allowed:
                    raise ValueError("Extension update contains an unsafe path")
                destination = (stage.joinpath(*name.parts)).resolve()
                if stage not in destination.parents and destination != stage:
                    raise ValueError("Extension update escapes staging directory")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(package.read(info))
        manifest_path = stage / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Extension update manifest is invalid") from exc
        if str(manifest.get("version") or "") != version or not (stage / "background.js").is_file():
            raise ValueError("Extension update manifest does not match the package version")
        target = (self.app_root / "extension").resolve()
        if not target.is_dir():
            raise RuntimeError("当前客户端没有可更新的受管理扩展目录。")
        current_manifest = target / "manifest.json"
        current_version = "unknown"
        try:
            current_version = str(json.loads(current_manifest.read_text(encoding="utf-8")).get("version") or "unknown")
        except (OSError, ValueError):
            pass
        backup = (self.data_dir / "extension-backup" / f"v{current_version}").resolve()
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(target, backup)
        try:
            for child in target.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            shutil.copytree(stage, target, dirs_exist_ok=True)
        except Exception:
            for child in target.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            shutil.copytree(backup, target, dirs_exist_ok=True)
            raise
        return {"ok": True, "version": version, "path": str(target), "backup": str(backup), "requires_reload": True, "message": "受管理扩展已更新到固定目录，请在 Chrome/Edge 扩展管理页重新加载；正在交接的任务未被重载。"}

    def apply_extension_update(self, version: str, archive_path: str, sha256: str = "") -> dict:
        try:
            response = requests.get(f"{self.backend_url}/api/tasks", timeout=2.0)
            response.raise_for_status()
            payload = response.json()
            tasks = payload.get("tasks", []) if isinstance(payload, dict) else payload
            active = [item for item in tasks if isinstance(item, dict) and item.get("status") in {"queued", "running", "cancelling"}]
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise RuntimeError("无法确认当前任务是否已保存，请完成任务或稍后重试。") from exc
        if active:
            raise RuntimeError(f"还有 {len(active)} 个任务正在处理，完成或停止后再更新。")
        return self.install_extension_update(version, archive_path, sha256)

    def apply_update(self, version: str, installer_path: str, sha256: str = "") -> dict:
        try:
            response = requests.get(f"{self.backend_url}/api/tasks", timeout=2.0)
            response.raise_for_status()
            payload = response.json()
            tasks = payload.get("tasks", []) if isinstance(payload, dict) else payload
            active = [item for item in tasks if isinstance(item, dict) and item.get("status") in {"queued", "running", "cancelling"}]
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise RuntimeError("无法确认当前任务是否已保存，请完成任务或稍后重试。") from exc
        if active:
            raise RuntimeError(f"还有 {len(active)} 个任务正在处理，完成或停止后再更新。")
        installer = Path(str(installer_path or "")).resolve()
        expected = str(sha256 or "").strip().lower()
        if expected:
            if not re.fullmatch(r"[a-f0-9]{64}", expected) or not installer.is_file():
                raise RuntimeError("更新包校验信息无效，原程序未改变。")
            digest = hashlib.sha256()
            with installer.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError("更新包已变化或校验失败，原程序未改变。")
        return self.install_update(version, installer_path)

    def set_update_preferences(self, auto_check: bool = True, auto_download: bool = True) -> dict:
        response = requests.put(
            f"{self.backend_url}/api/update/preferences",
            json={"auto_check": bool(auto_check), "auto_download": bool(auto_download)},
            timeout=3.0,
        )
        response.raise_for_status()
        return response.json()

    def install_update(self, version: str, installer_path: str) -> dict:
        version = str(version or "").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid update version")
        update_dir = (self.data_dir / "installers" / f"v{version}").resolve()
        installer = Path(str(installer_path or "")).resolve()
        if installer != update_dir / WINDOWS_INSTALLER_NAME or not installer.is_file():
            raise ValueError("Update installer is not ready")
        root = application_root().resolve()
        app_path = (root / "LearnNote.exe").resolve()
        if root.drive.upper() == "C:" or not app_path.is_file() or self._window is None:
            raise RuntimeError("Automatic update is only available in the installed desktop client")

        def ps_literal(value: Path | str) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        script_path = update_dir / "install-update.ps1"
        log_path = update_dir / "install.log"
        script = "\n".join([
            "$ErrorActionPreference = 'Stop'",
            f"$parentPid = {os.getpid()}",
            "$parent = Get-Process -Id $parentPid -ErrorAction SilentlyContinue",
            "if ($parent) { Wait-Process -Id $parentPid }",
            f"$installer = {ps_literal(installer)}",
            f"$app = {ps_literal(app_path)}",
            f"$installDir = {ps_literal(root)}",
            f"$log = {ps_literal(log_path)}",
            "$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR=\"' + $installDir + '\"'), ('/LOG=\"' + $log + '\"'))",
            "$result = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru",
            "Add-Content -LiteralPath $log -Value ('LearnNote updater exit code: ' + $result.ExitCode)",
            "if ($result.ExitCode -ne 0) { Start-Process -FilePath $app -WorkingDirectory $installDir; exit $result.ExitCode }",
            "Start-Process -FilePath $app -WorkingDirectory $installDir",
        ]) + "\n"
        script_path.write_text(script, encoding="utf-8-sig")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            cwd=str(update_dir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Timer(0.4, self._window.destroy).start()
        return {"ok": True, "installing": True, "version": version}

    def open_release(self, url: str) -> dict:
        if not str(url).startswith("https://github.com/hurry060215-tech/learnnote-assistant/releases/"):
            raise ValueError("Unsupported release URL")
        webbrowser.open(url)
        return {"ok": True}


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            contents = Path(sys.executable).resolve().parent.parent
            resources = contents / "Resources" / "LearnNote"
            if resources.is_dir():
                return resources
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def open_local_path(path: Path) -> None:
    resolved = str(Path(path).resolve())
    if os.name == "nt":
        os.startfile(Path(resolved))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", resolved])
    else:
        subprocess.Popen(["xdg-open", resolved])


def default_data_directory(root: Path) -> Path:
    configured = str(os.getenv("LEARNNOTE_DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "LearnNote").resolve()
    if os.name != "nt":
        return (Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "LearnNote").resolve()
    return (root / "data").resolve()


def bundled_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", application_root())).resolve()


def available_port(preferred: int) -> int:
    if not 1 <= preferred <= 65535:
        raise ValueError("LearnNote 端口必须在 1 到 65535 之间。")
    for port in range(preferred, min(preferred + 20, 65536)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available LearnNote desktop port was found.")


def wait_for_backend(url: str, timeout: float = 25.0, worker: threading.Thread | None = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if worker is not None and not worker.is_alive():
            raise RuntimeError("LearnNote 本地服务启动中断，请重新打开应用。")
        if backend_ready(url):
            return
        time.sleep(0.15)
    raise RuntimeError("LearnNote 本地服务启动超时，请稍后重新打开应用。")


def configured_data_directory(root: Path) -> Path:
    data_dir = default_data_directory(root)
    config_path = root / "learnnote-config.json"
    try:
        configured = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        configured_path = str(configured.get("data_dir") or "").strip()
        if configured_path:
            candidate = Path(configured_path).expanduser().resolve()
            if os.name != "nt" or (candidate.drive and candidate.drive.upper() != "C:"):
                data_dir = candidate
    except (OSError, ValueError, json.JSONDecodeError):
        data_dir = default_data_directory(root)
    return data_dir


def configure_runtime(root: Path, port: int) -> Path:
    data_dir = configured_data_directory(root)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LEARNNOTE_DATA_DIR"] = str(data_dir)
    os.environ["LEARNNOTE_BACKEND_ORIGIN"] = f"http://127.0.0.1:{port}"
    os.environ["LEARNNOTE_DEPLOYMENT_MODE"] = "desktop"

    backend_dir = bundled_root() / "backend"
    if not backend_dir.exists():
        backend_dir = root / "backend"
    sys.path.insert(0, str(backend_dir))
    return data_dir


def configure_model_runtime() -> bool:
    # Selected connections are resolved by the local backend for this DATA_DIR.
    # Never replace an explicit environment/provider with an old Kimi credential.
    return False

def webview_browser_arguments(remote_debug_port: int = 0) -> str:
    arguments = [
        "--disable-features=ElasticOverscroll",
        "--allow-file-access-from-files",
    ]
    if remote_debug_port:
        arguments.append(f"--remote-debugging-port={remote_debug_port}")
    return " ".join(arguments)


def configure_webview_runtime(webview_module, remote_debug_port: int = 0) -> None:
    from webview.platforms import edgechromium as edge

    if getattr(edge.EdgeChrome, "_learnnote_runtime", False):
        return

    class LearnNoteEdgeChrome(edge.EdgeChrome):
        _learnnote_runtime = True

        def __init__(self, form, window, cache_dir: str):
            self.pywebview_window = window
            self.webview = edge.WebView2()
            props = edge.CoreWebView2CreationProperties()

            runtime_path = webview_module.settings["WEBVIEW2_RUNTIME_PATH"]
            if runtime_path:
                if not os.path.isabs(runtime_path):
                    runtime_path = os.path.join(edge.get_app_root(), runtime_path)
                if os.path.exists(runtime_path):
                    props.BrowserExecutableFolder = runtime_path

            props.UserDataFolder = cache_dir
            self.user_data_folder = props.UserDataFolder
            props.set_IsInPrivateModeEnabled(edge._state["private_mode"])
            props.AdditionalBrowserArguments = webview_browser_arguments(remote_debug_port)
            self.webview.CreationProperties = props

            self.form = form
            form.Controls.Add(self.webview)
            self.js_results = {}
            self.js_result_semaphore = edge.Semaphore(0)
            self.webview.Dock = edge.WinForms.DockStyle.Fill
            self.webview.BringToFront()
            self.webview.CoreWebView2InitializationCompleted += self.on_webview_ready
            self.webview.NavigationStarting += self.on_navigation_start
            self.webview.NavigationCompleted += self.on_navigation_completed
            self.webview.WebMessageReceived += self.on_script_notify
            self.syncContextTaskScheduler = edge.TaskScheduler.FromCurrentSynchronizationContext()
            self.webview.DefaultBackgroundColor = edge.Color.FromArgb(
                255,
                int(window.background_color.lstrip("#")[0:2], 16),
                int(window.background_color.lstrip("#")[2:4], 16),
                int(window.background_color.lstrip("#")[4:6], 16),
            )
            if window.transparent:
                self.webview.DefaultBackgroundColor = edge.Color.Transparent

            self.url = None
            self.ishtml = False
            self.html = edge.DEFAULT_HTML
            self.webview.EnsureCoreWebView2Async(None)

    edge.EdgeChrome = LearnNoteEdgeChrome


def webview_storage_path(data_dir: Path) -> Path:
    path = (data_dir / "webview-profile").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def desktop_focus_target(backend_url: str, task_id: str, tab: str, view: str = "workspace") -> str:
    safe_view = view if view in {"settings", "diagnostics"} else "workspace"
    if not re.fullmatch(r"[a-f0-9]{12}", task_id):
        return f"{backend_url}/?view={safe_view}" if safe_view != "workspace" else ""
    safe_tab = tab if tab in {"note", "slices", "qa", "diagnostics", "transcript", "frames"} else "note"
    return f"{backend_url}/?task={quote(task_id)}&tab={quote(safe_tab)}" + (f"&view={safe_view}" if safe_view != "workspace" else "")


def desktop_route_matches(current_url: str, target_url: str) -> bool:
    if not current_url or not target_url:
        return False
    current = urlparse(current_url)
    target = urlparse(target_url)
    if (current.scheme, current.netloc, current.path) != (target.scheme, target.netloc, target.path):
        return False
    current_query = parse_qs(current.query)
    target_query = parse_qs(target.query)
    selected_hash = re.fullmatch(r"task/([a-f0-9]{12})", current.fragment)
    current_task = [selected_hash.group(1)] if selected_hash else current_query.get("task")
    return current_task == target_query.get("task") and current_query.get("tab", ["note"]) == target_query.get("tab", ["note"]) and current_query.get("view", ["workspace"]) == target_query.get("view", ["workspace"])


def _run() -> int:
    parser = argparse.ArgumentParser(description="Launch the LearnNote Windows desktop client.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--webview-debug-port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--protocol", default="", help=argparse.SUPPRESS)
    parser.add_argument("--wait-for-parent", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.port = protocol_port(args.protocol) or args.port
    wait_for_process_exit(args.wait_for_parent)
    root = application_root()
    if os.name == "nt" and root.drive.upper() == "C:":
        raise RuntimeError("LearnNote 请安装在 D: 或其他非系统盘，再从快捷方式启动。")
    session = DesktopSession(configured_data_directory(root))
    try:
        if not session.acquire():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                existing_url = session.running_url()
                if existing_url:
                    open_workspace(existing_url)
                    return 0
                time.sleep(0.2)
            raise RuntimeError("LearnNote 正在启动或关闭，请稍后重新打开。已有笔记和任务不会被修改。")
        return run_session(args, root, session)
    finally:
        session.close()


def open_workspace(url: str) -> None:
    if not webbrowser.open(url):
        raise RuntimeError(f"LearnNote 已启动。默认浏览器未能打开，请在浏览器访问 {url}。")


def run_session(args, root: Path, session: DesktopSession) -> int:
    preferred_url = f"http://127.0.0.1:{args.port}"
    existing_url = preferred_url if backend_ready(preferred_url) else ""
    if existing_url:
        open_workspace(existing_url)
        return 0
    port = available_port(args.port)
    data_dir = configure_runtime(root, port)
    configure_model_runtime()

    from app.main import app
    import webview

    if os.name == "nt":
        configure_webview_runtime(webview, args.webview_debug_port)
    webview.settings["ALLOW_DOWNLOADS"] = True

    backend_url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info" if args.debug else "warning",
        proxy_headers=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="learnnote-backend", daemon=True)
    thread.start()

    try:
        wait_for_backend(backend_url, worker=thread)
        session.publish(backend_url)
        desktop_api = DesktopApi(data_dir, backend_url, root)
        window = webview.create_window(
            "LearnNote",
            backend_url,
            width=1440,
            height=900,
            min_size=(1024, 700),
            background_color="#f6f8fa",
            text_select=True,
            confirm_close=False,
            js_api=desktop_api,
        )
        desktop_api._bind_window(window)
        def focus_desktop(payload: dict | None = None) -> None:
            body = payload or {}
            task_id = str(body.get("task_id") or "")
            tab = str(body.get("tab") or "note")
            target_url = desktop_focus_target(backend_url, task_id, tab, str(body.get("view") or "workspace"))
            if target_url:
                try:
                    current_url = str(window.get_current_url() or "")
                except Exception:
                    current_url = ""
                if not desktop_route_matches(current_url, target_url):
                    window.load_url(target_url)
            window.restore()
            window.show()

        app.state.desktop_focus = focus_desktop
        window.events.loaded += lambda: window.set_title("LearnNote - Video Learning Notes")
        webview.start(
            debug=args.debug,
            private_mode=False,
            storage_path=str(webview_storage_path(data_dir)),
        )
    finally:
        server.should_exit = True
        thread.join(timeout=8)

    print(f"LearnNote Desktop closed. Data kept at {data_dir}")
    return 0


def report_startup_error(error: Exception) -> None:
    """Windowless packaged apps must explain failures instead of silently exiting."""
    log_path = application_root() / "startup-error.log"
    try:
        # Stack locations suffice for diagnosis; do not write locals or credentials.
        log_path.write_text(type(error).__name__ + "\n" + "".join(traceback.format_tb(error.__traceback__)), encoding="utf-8")
    except OSError:
        log_path = None
    message = str(error) if str(error).startswith("LearnNote ") else "LearnNote 启动未完成。请重新打开；若仍失败，请重新解压或更新完整客户端。"
    if isinstance(error, PermissionError):
        message = "LearnNote 无法写入应用或数据目录。请检查目录权限，或把完整应用解压到可写入的非系统盘文件夹。"
    if log_path:
        message += f"\n\n诊断文件：{log_path}"
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "LearnNote · 启动提示", 0x10)
            return
        except Exception:
            pass
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def run() -> int:
    try:
        return _run()
    except Exception as error:
        report_startup_error(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
