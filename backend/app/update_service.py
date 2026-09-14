"""Trusted release metadata and local update preferences.

This module deliberately stops at release metadata.  A normal server can tell
the browser which official versions exist, but it must never accept an
arbitrary executable path or perform a local installation.  The desktop
bridge owns the download/apply half of the contract after the same metadata
has been checked again locally.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

import requests
from .storage import atomic_write_text

from . import APP_VERSION, UX_PROTOCOL_VERSION
from .config import DATA_DIR, DEPLOYMENT_MODE, PROJECT_ROOT


OFFICIAL_REPOSITORY = "hurry060215-tech/learnnote-assistant"
RELEASE_API = f"https://api.github.com/repos/{OFFICIAL_REPOSITORY}/releases/latest"
RELEASE_PAGE = f"https://github.com/{OFFICIAL_REPOSITORY}/releases/latest"
RELEASE_BASE = f"https://github.com/{OFFICIAL_REPOSITORY}/releases"
INSTALLER_NAME = "LearnNote-Setup-x64.exe"
EXTENSION_ASSET_TEMPLATE = "LearnNote-Browser-Extension-v{version}.zip"
MAX_UPDATE_BYTES = 500 * 1024 * 1024
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_cache_lock = RLock()
_release_cache: dict | None = None
_release_cache_at = 0.0


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer_version(candidate: str, current: str) -> bool:
    left, right = _version_tuple(candidate), _version_tuple(current)
    return bool(left and right and left > right)


def _official_release_url(version: str, url: str) -> bool:
    return _official_asset_url(version, url, INSTALLER_NAME)


def _official_asset_url(version: str, url: str, name: str) -> bool:
    parsed = urlparse(str(url or ""))
    return (
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and parsed.path == f"/{OFFICIAL_REPOSITORY}/releases/download/v{version}/{name}"
        and not parsed.query
        and not parsed.fragment
    )


def _asset(asset: dict, *, version: str, name: str) -> dict:
    url = str(asset.get("browser_download_url") or "")
    digest = str(asset.get("digest") or "")
    checksum = digest.removeprefix("sha256:").lower() if digest.startswith("sha256:") else ""
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        checksum = ""
    return {
        "name": name,
        "url": url if _official_release_url(version, url) or name != INSTALLER_NAME else "",
        "sha256": checksum,
        "bytes": int(asset.get("size") or 0) if str(asset.get("size") or "0").isdigit() else 0,
        "installable": bool(
            name == INSTALLER_NAME
            and _official_release_url(version, url)
            and checksum
            and 0 < int(asset.get("size") or 1) <= MAX_UPDATE_BYTES
        ),
    }


def _release_payload(payload: dict) -> dict:
    version = str(payload.get("tag_name") or "").removeprefix("v")
    page = str(payload.get("html_url") or "")
    if not _version_tuple(version) or not page.startswith(f"https://github.com/{OFFICIAL_REPOSITORY}/releases/"):
        raise ValueError("Official release metadata is invalid")
    assets = {
        str(item.get("name") or ""): item
        for item in payload.get("assets") or []
        if isinstance(item, dict)
    }
    installer = _asset(assets.get(INSTALLER_NAME, {}), version=version, name=INSTALLER_NAME)
    extension_name = EXTENSION_ASSET_TEMPLATE.format(version=version)
    extension = assets.get(extension_name, {})
    extension_url = str(extension.get("browser_download_url") or "")
    extension_digest = str(extension.get("digest") or "")
    extension_checksum = extension_digest.removeprefix("sha256:").lower() if extension_digest.startswith("sha256:") else ""
    extension_size = int(extension.get("size") or 0) if str(extension.get("size") or "0").isdigit() else 0
    extension_trusted = bool(
        extension
        and _official_asset_url(version, extension_url, extension_name)
        and re.fullmatch(r"[a-f0-9]{64}", extension_checksum)
        and 0 < extension_size <= MAX_UPDATE_BYTES
    )
    extension_meta = {
        "name": extension_name,
        "url": extension_url if extension_trusted else "",
        "sha256": extension_checksum if extension_trusted else "",
        "bytes": extension_size,
        "available": extension_trusted,
    }
    return {
        "version": version,
        "page_url": page,
        "published_at": str(payload.get("published_at") or ""),
        "prerelease": bool(payload.get("prerelease")),
        "client": installer,
        "extension": extension_meta,
    }


def _release_from_web() -> dict:
    """Read the same official release and checksums when the API is throttled."""
    page = requests.get(RELEASE_PAGE, timeout=8.0, allow_redirects=True)
    page.raise_for_status()
    match = re.fullmatch(re.escape(RELEASE_BASE) + r"/tag/v(\d+\.\d+\.\d+)/?", str(page.url))
    if not match:
        raise ValueError("Invalid official release redirect")
    version = match[1]
    base = f"{RELEASE_BASE}/download/v{version}"
    checksums = requests.get(f"{base}/SHA256SUMS.txt", timeout=8.0)
    checksums.raise_for_status()
    if len(checksums.text) > 65536:
        raise ValueError("Invalid release checksum manifest")
    assets = []
    for digest, name in re.findall(r"(?m)^([a-fA-F0-9]{64})\s{2}([A-Za-z0-9_.-]+)\s*$", checksums.text):
        if name == INSTALLER_NAME or name == EXTENSION_ASSET_TEMPLATE.format(version=version):
            assets.append({"name":name,"browser_download_url":f"{base}/{name}","digest":"sha256:"+digest.lower(),"size":0})
    if not any(item["name"] == INSTALLER_NAME for item in assets):
        raise ValueError("Release checksum missing installer")
    return {"tag_name":"v"+version,"html_url":f"{RELEASE_BASE}/tag/v{version}","assets":assets,"prerelease":False}


def fetch_latest_release(*, force: bool = False) -> dict:
    global _release_cache, _release_cache_at
    now = time.time()
    with _cache_lock:
        if _release_cache is not None and not force and now - _release_cache_at < CHECK_INTERVAL_SECONDS:
            return {**_release_cache, "cached": True, "checked_at": _release_cache_at}
    response = requests.get(
        RELEASE_API,
        timeout=8.0,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "LearnNote-Updater"},
    )
    if getattr(response, "status_code", 200) in {403, 429}:
        raw = _release_from_web()
    else:
        response.raise_for_status()
        raw = response.json()
    result = _release_payload(raw)
    with _cache_lock:
        _release_cache = result
        _release_cache_at = time.time()
        atomic_write_text(DATA_DIR / "config" / "release-cache.json", json.dumps({"release": raw, "checked_at": _release_cache_at}))
        return {**result, "cached": False, "checked_at": _release_cache_at}


def _saved_release() -> dict | None:
    try:
        saved = json.loads((DATA_DIR / "config" / "release-cache.json").read_text(encoding="utf-8"))
        result = _release_payload(saved["release"])
        return {**result, "checked_at": float(saved["checked_at"]), "cached": True}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _extension_version() -> str:
    candidates = [
        PROJECT_ROOT / "extension" / "manifest.json",
        Path(__file__).resolve().parents[2] / "extension" / "manifest.json",
    ]
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = str(payload.get("version") or "")
            if _version_tuple(value):
                return value
        except (OSError, ValueError):
            continue
    return ""


def get_preferences() -> dict:
    path = DATA_DIR / "config" / "update-preferences.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        payload = {}
    return {
        "auto_check": bool(payload.get("auto_check", True)),
        "auto_download": bool(payload.get("auto_download", True)),
        "last_checked_at": float(payload.get("last_checked_at") or 0),
    }


def save_preferences(payload: dict) -> dict:
    current = get_preferences()
    result = {
        "auto_check": bool(payload.get("auto_check", current["auto_check"])),
        "auto_download": bool(payload.get("auto_download", current["auto_download"])),
        "last_checked_at": float(payload.get("last_checked_at", current["last_checked_at"]) or 0),
    }
    path = DATA_DIR / "config" / "update-preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return result


def status(*, force: bool = False) -> dict:
    preferences = get_preferences()
    latest = _saved_release()
    error = ""
    due = force or (preferences["auto_check"] and (latest is None or time.time() - latest["checked_at"] >= CHECK_INTERVAL_SECONDS))
    if due:
        try:
            latest = fetch_latest_release(force=True)
            preferences = save_preferences({**preferences, "last_checked_at": latest["checked_at"]})
        except (requests.RequestException, ValueError) as exc:
            error = "暂时无法连接官方更新服务，请稍后重试。已下载并校验的更新仍然保留。"
    if latest is not None and DEPLOYMENT_MODE != "desktop":
        latest = {
            **latest,
            "client": {**latest["client"], "url": "", "sha256": "", "installable": False},
            "extension": {**latest["extension"], "url": "", "sha256": ""},
        }
    current = {
        "client_version": APP_VERSION,
        "extension_version": _extension_version(),
        "protocol_version": UX_PROTOCOL_VERSION,
    }
    return {
        "ok": not error,
        "current": current,
        "latest": latest,
        "client_update_available": bool(latest and is_newer_version(latest["version"], APP_VERSION)),
        "extension_update_available": bool(latest and latest["extension"]["available"] and is_newer_version(latest["version"], current["extension_version"])),
        "capabilities": {
            "release_info": True,
            "download": DEPLOYMENT_MODE == "desktop",
            "apply": DEPLOYMENT_MODE == "desktop",
            "reason": "desktop_bridge" if DEPLOYMENT_MODE == "desktop" else "server_only",
        },
        "preferences": preferences,
        "check_due": due,
        "error": error,
    }
