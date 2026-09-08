"""Local desktop startup coordination, without retaining browser or account data."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


def local_origin(value: str) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlparse(value)
        if (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port and 1 <= parsed.port <= 65535
                and not parsed.username and not parsed.password
                and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment):
            return f"http://127.0.0.1:{parsed.port}"
    except (TypeError, ValueError):
        pass
    return ""


def backend_ready(url: str) -> bool:
    if not local_origin(url):
        return False
    try:
        response = requests.get(url + "/health", timeout=1, allow_redirects=False)
        if response.status_code != 200:
            return False
        health = response.json()
        return (isinstance(health, dict) and health.get("ok") is True
                and bool(health.get("app_version")) and bool(health.get("backend_version"))
                and health.get("protocol_version") == 1
                and (health.get("service") == "learnnote" or (
                    "service" not in health and health.get("api_version")
                    and health.get("task_schema_version")
                    and local_origin(health.get("backend_origin", "")) == local_origin(url))))
    except (requests.RequestException, ValueError):
        return False


def protocol_port(value: str) -> int | None:
    """Only navigation to the local app is supported; never execute URI content."""
    if not value:
        return
    parsed = urlparse(value)
    if (parsed.scheme != "learnnote" or parsed.netloc != "open"
            or parsed.path not in {"", "/"} or parsed.fragment):
        raise ValueError("LearnNote 启动链接无效，请从应用快捷方式重新打开。")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not query:
        return None
    if set(query) != {"port"} or len(query["port"]) != 1:
        raise ValueError("LearnNote 启动链接包含不支持的参数。")
    port = query["port"][0]
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("LearnNote 启动端口无效。")
    return int(port)


def wait_for_process_exit(pid: int, timeout: float = 30) -> None:
    if pid <= 0:
        return
    if pid == os.getpid():
        raise ValueError("LearnNote 重启进程无效。")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # Process has already exited.
                return
            raise RuntimeError("LearnNote 暂时无法确认旧进程已关闭，请稍后重新打开。")
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0:
                return
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
    raise RuntimeError("LearnNote 仍在关闭旧进程，请稍后重新打开。笔记数据会保留。")


class DesktopSession:
    """One owning desktop process per data folder, released automatically on crash."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.endpoint_path = data_dir / ".desktop-session.json"
        self.handle = None

    def acquire(self) -> bool:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle = (self.data_dir / ".desktop-session.lock").open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        # If a previous process crashed, its port may now belong to another library.
        # Only the process holding the lock may publish a reusable endpoint.
        self.endpoint_path.unlink(missing_ok=True)
        return True

    def running_url(self) -> str:
        try:
            record = json.loads(self.endpoint_path.read_text(encoding="utf-8"))
            url = local_origin(record.get("url", "")) if isinstance(record, dict) else ""
            return url if url and backend_ready(url) else ""
        except (OSError, ValueError):
            return ""

    def publish(self, url: str) -> None:
        if not self.handle or not local_origin(url):
            raise ValueError("A running desktop session must own its data folder.")
        temporary = self.endpoint_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"url": url}), encoding="utf-8")
        temporary.replace(self.endpoint_path)

    def close(self) -> None:
        if self.handle:
            try:
                self.endpoint_path.unlink(missing_ok=True)
            except OSError:
                pass
            finally:
                self.handle.close()
                self.handle = None
