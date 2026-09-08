"""Optional provider sessions. Keys stay in the local service or OS key store."""
from __future__ import annotations

import hashlib
import os
import sys
import threading

from .config import DATA_DIR, PUBLIC_DEPLOYMENT

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_lock = threading.RLock()
_session_key = ""


def _credential_name() -> str:
    scope = hashlib.sha256(str(DATA_DIR).encode()).hexdigest()[:20]
    return f"connection-openrouter-{scope}"


def connection_storage() -> str:
    return "system" if not PUBLIC_DEPLOYMENT and (os.name == "nt" or sys.platform == "darwin") else "session"


def save_connection(key: str) -> str:
    global _session_key
    if PUBLIC_DEPLOYMENT:
        raise ValueError("Provider connection is only available in local mode")
    if not isinstance(key, str) or not key or len(key) > 8192:
        raise ValueError("Invalid provider key")
    with _lock:
        storage = connection_storage()
        if storage == "system":
            from desktop.credentials import write_secret
            write_secret(_credential_name(), key)
        _session_key = key
        return storage


def read_connection() -> str:
    global _session_key
    if PUBLIC_DEPLOYMENT:
        return ""
    with _lock:
        if not _session_key and connection_storage() == "system":
            from desktop.credentials import read_secret
            _session_key = read_secret(_credential_name())
        return _session_key


def clear_connection() -> None:
    global _session_key
    with _lock:
        if connection_storage() == "system":
            from desktop.credentials import delete_secret
            delete_secret(_credential_name())
        _session_key = ""


def connected_api_key(options) -> str:
    if not getattr(options, "use_saved_connection", False):
        return ""
    # Exact origin AND API path binding prevents session credentials from being
    # sent to a user-supplied endpoint or another provider.
    if str(getattr(options, "llm_base_url", "") or "").rstrip("/") != OPENROUTER_BASE:
        return ""
    return read_connection()
