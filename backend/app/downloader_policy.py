"""Downloader error and retry policy primitives.

This module contains no network I/O.  Keeping classifications and exception
types separate lets the downloader and API layers consume the same stable
policy without importing each other.
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

import requests


YTDLP_FIRST_HOSTS = {
    "b23.tv",
    "bilibili.com",
    "m.bilibili.com",
    "www.bilibili.com",
    "youtube.com",
    "m.youtube.com",
    "www.youtube.com",
    "youtu.be",
}

DOWNLOAD_FAILURE_PRIORITY = {
    "drm_or_encrypted": 50,
    "media_mismatch": 45,
    "auth_required": 40,
    "yt_dlp_timeout": 35,
    "download_timeout": 35,
    "network_tls_error": 34,
    "download_forbidden": 30,
    "unsupported_manifest": 20,
    "no_media_found": 10,
}


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ManifestEndpointDetected(RuntimeError):
    def __init__(self, kind: str, mime: str):
        super().__init__(kind)
        self.kind = kind
        self.mime = mime


class UnsafeMediaTarget(requests.RequestException):
    pass


class QuietYtdlpLogger:
    def debug(self, message: str) -> None:
        return

    def warning(self, message: str) -> None:
        return

    def error(self, message: str) -> None:
        return


def should_run_ytdlp_cli(yt_dlp_module: object) -> bool:
    # A frozen desktop executable is not a Python interpreter. Running
    # ``LearnNote.exe -m yt_dlp`` feeds yt-dlp arguments to the desktop CLI.
    return not getattr(sys, "frozen", False) and bool(getattr(yt_dlp_module, "__file__", ""))


def truncate_process_output(value: object, limit: int = 500) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    return text.strip()[:limit]


def classify_ytdlp_error(message: str) -> str:
    lowered = (message or "").lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "yt_dlp_timeout"
    if any(marker in lowered for marker in (
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "tlsv1 alert",
        "ssl: eof",
        "ssl eof",
    )):
        return "network_tls_error"
    if any(marker in lowered for marker in ("login", "cookie", "sign in", "private video", "members-only")):
        return "auth_required"
    if any(marker in lowered for marker in ("drm", "encrypted", "eme")):
        return "drm_or_encrypted"
    if "unsupported url" in lowered or "no suitable extractor" in lowered:
        return "no_media_found"
    return "download_forbidden"


def prefer_ytdlp_before_page_scan(page_url: str) -> bool:
    try:
        host = (urlparse(page_url).hostname or "").lower()
    except Exception:
        return False
    return host in YTDLP_FIRST_HOSTS
