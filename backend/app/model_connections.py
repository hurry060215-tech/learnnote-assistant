"""Optional provider sessions. Keys stay in the local service or OS key store."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from urllib.parse import urlsplit

from .config import DATA_DIR, PUBLIC_DEPLOYMENT

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_lock = threading.RLock()
_session_key = ""
_selected_sessions: dict[str, str] = {}


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
    base = str(getattr(options, "llm_base_url", "") or "").strip().rstrip("/")
    with _lock:
        selected = _read_selected()
        if selected and base == selected["base_url"]:
            return _selected_key(selected)
        if base and not PUBLIC_DEPLOYMENT:
            # A queued task snapshots its endpoint. Selecting another provider
            # must not redirect it or make it use the newly selected key.
            name = _selected_credential_name(base)
            if name in _selected_sessions:
                return _selected_sessions[name]
            if connection_storage() == "system":
                try:
                    from desktop.credentials import read_secret
                    key = read_secret(name)
                    if key:
                        return key
                except Exception:
                    pass
    return read_connection() if base == OPENROUTER_BASE else ""


def validate_connection_base(value: str) -> str:
    """Persist an explicit endpoint, never credentials embedded in a URL."""
    base = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("模型地址格式不正确。") from exc
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in ({"http", "https"} if local else {"https"})):
        raise ValueError("模型地址需使用 HTTPS 或本机 HTTP，且不能包含账号、查询参数或片段。")
    return base


def _selected_credential_name(base: str) -> str:
    scope = hashlib.sha256(str(DATA_DIR.resolve()).encode()).hexdigest()[:20]
    endpoint = hashlib.sha256(base.encode()).hexdigest()[:20]
    return f"connection-model-{scope}-{endpoint}"


def _read_selected() -> dict | None:
    if PUBLIC_DEPLOYMENT:
        return None
    try:
        value = json.loads((DATA_DIR / "model-connection.json").read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schema") != 1
                or value.get("storage") not in {"system", "session", "none"}
                or value.get("credential_source") not in {"key", "openrouter", "none"}
                or not isinstance(value.get("provider"), str)
                or not isinstance(value.get("model"), str)):
            return None
        value["base_url"] = validate_connection_base(value.get("base_url", ""))
        return value
    except (OSError, ValueError, TypeError):
        return None


def _selected_key(selected: dict) -> str:
    if PUBLIC_DEPLOYMENT or selected["credential_source"] == "none":
        return ""
    if selected["credential_source"] == "openrouter":
        try:
            return read_connection() if selected["base_url"] == OPENROUTER_BASE else ""
        except Exception:
            return ""
    name = _selected_credential_name(selected["base_url"])
    if name in _selected_sessions:
        return _selected_sessions[name]
    if selected["storage"] == "system" and connection_storage() == "system":
        try:
            from desktop.credentials import read_secret
            return read_secret(name)
        except Exception:
            return ""
    return ""


def selected_connection_status() -> dict:
    """Public metadata only. A missing selected key never falls back to another provider."""
    with _lock:
        selected = _read_selected()
        if not selected:
            return {"model": None, "configured": False, "storage": "none", "message": "尚未保存模型连接。"}
        local = urlsplit(selected["base_url"]).hostname in {"localhost", "127.0.0.1", "::1"}
        configured = bool(_selected_key(selected)) or (local and selected["credential_source"] == "none")
        storage = selected["storage"]
        message = ("模型连接已保存，Key 保存在系统凭据库。" if storage == "system" else
                   "模型连接仅在本机服务运行期间有效；系统凭据库不可用，重启服务后需重新填写 Key。" if storage == "session" else
                   "本机模型设置已保存，无需 Key。" if local else "模型地址已保存，请填写 Key 后使用。")
        if not configured and selected["credential_source"] != "none":
            message = "模型设置已保留，但保存的 Key 当前不可用，请重新填写或连接。"
        return {"model": {"provider": selected["provider"], "base_url": selected["base_url"],
                          "model": selected["model"], "use_saved_connection": not (local and selected["credential_source"] == "none")},
                "configured": configured, "storage": storage, "message": message}


def save_selected_connection(provider: str, base_url: str, model: str, api_key: str = "", *, use_saved_connection: bool = False) -> dict:
    if PUBLIC_DEPLOYMENT:
        raise ValueError("模型连接仅在本机工作台保存。")
    base = validate_connection_base(base_url)
    if not model.strip():
        raise ValueError("请填写模型名称。")
    key = api_key.strip()
    if len(key) > 8192:
        raise ValueError("API Key 长度超出限制。")
    with _lock:
        storage, source = "none", "none"
        previous = _read_selected()
        name = _selected_credential_name(base)
        old_session = _selected_sessions.get(name)
        system_storage = connection_storage() == "system"
        old_stored = ""
        store_changed = False
        if key or not use_saved_connection:
            if system_storage:
                from desktop.credentials import delete_secret, read_secret, write_secret
                # An inaccessible existing key cannot safely be replaced: retain
                # its metadata and let the caller retry after unlocking the vault.
                old_stored = read_secret(name)
        if not key and use_saved_connection:
            if previous and previous["base_url"] == base:
                source, storage = previous["credential_source"], previous["storage"]
            elif base == OPENROUTER_BASE and read_connection():
                source, storage = "openrouter", connection_storage()
            else:
                raise ValueError("该地址没有已保存的连接，请填写 API Key。")
        try:
            if key:
                source, storage = "key", connection_storage()
                if system_storage:
                    try:
                        write_secret(name, key)
                        store_changed = True
                    except Exception:
                        # No plaintext fallback, and never revive an older key
                        # after a session-only replacement or provider switch.
                        if old_stored:
                            delete_secret(name)
                            store_changed = True
                        storage = "session"
                _selected_sessions[name] = key
            elif not use_saved_connection:
                if system_storage and old_stored:
                    delete_secret(name)
                    store_changed = True
                _selected_sessions.pop(name, None)
            value = {"schema": 1, "provider": provider, "base_url": base, "model": model.strip(),
                     "credential_source": source, "storage": storage}
            from .storage import atomic_write_text
            atomic_write_text(DATA_DIR / "model-connection.json", json.dumps(value, ensure_ascii=False, indent=2))
        except Exception:
            # A failed settings save must not change the running model's key.
            if old_session is None:
                _selected_sessions.pop(name, None)
            else:
                _selected_sessions[name] = old_session
            if store_changed:
                if old_stored:
                    write_secret(name, old_stored)
                else:
                    delete_secret(name)
            raise
        return selected_connection_status()


def clear_selected_connection() -> dict:
    if PUBLIC_DEPLOYMENT:
        raise ValueError("模型连接仅在本机工作台保存。")
    with _lock:
        selected = _read_selected()
        if selected and selected["credential_source"] == "openrouter":
            clear_connection()
        if selected:
            name = _selected_credential_name(selected["base_url"])
            if connection_storage() == "system":
                from desktop.credentials import delete_secret
                delete_secret(name)
            _selected_sessions.pop(name, None)
        (DATA_DIR / "model-connection.json").unlink(missing_ok=True)
        return selected_connection_status()


def resolve_model_options(options):
    """Snapshot nonsecret selected defaults only when the request names no endpoint/key."""
    if getattr(options, "llm_base_url", None) or getattr(options, "llm_api_key", None):
        return options
    selected = selected_connection_status()["model"]
    if not selected:
        return options
    return options.model_copy(update={"llm_base_url": selected["base_url"],
                                      "llm_model": getattr(options, "llm_model", None) or selected["model"],
                                      "use_saved_connection": selected["use_saved_connection"]})
