"""OpenRouter's documented PKCE flow, scoped to a loopback LearnNote instance."""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import PUBLIC_DEPLOYMENT
from ..model_connections import OPENROUTER_BASE, clear_connection, connection_storage, read_connection, save_connection

connection_router = APIRouter(tags=["model connections"])
_pending = {}
_lock = threading.Lock()
_ttl = 600
_cookie = "learnnote_openrouter_oauth"


def _local_origin(request: Request, *, write=False) -> str:
    url = urlsplit(str(request.base_url))
    if PUBLIC_DEPLOYMENT or url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "账号连接仅在本机工作台使用。")
    origin = str(request.base_url).rstrip("/")
    if write and request.headers.get("origin", "").rstrip("/") != origin:
        raise HTTPException(403, "请从本机工作台发起连接。")
    return origin


@connection_router.get("/api/connections")
def connection_status(request: Request):
    _local_origin(request)
    try:
        connected = bool(read_connection())
    except Exception:
        connected = False
    return {"openrouter": {"connected": connected, "storage": connection_storage(), "base_url": OPENROUTER_BASE}}


@connection_router.post("/api/connections/openrouter/start")
def start_connection(request: Request):
    origin = _local_origin(request, write=True)
    state, verifier, browser_token = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    with _lock:
        now = time.monotonic()
        for key in list(_pending):
            if now - _pending[key]["created"] > _ttl:
                _pending.pop(key)
        if len(_pending) >= 16:
            raise HTTPException(429, "连接请求过多，请稍后重试。")
        _pending[state] = {"verifier": verifier, "browser": browser_token, "origin": origin, "created": now}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    callback = origin + "/api/connections/openrouter/callback?" + urlencode({"state": state})
    url = "https://openrouter.ai/auth?" + urlencode({"callback_url": callback, "code_challenge": challenge, "code_challenge_method": "S256"})
    response = JSONResponse({"authorization_url": url, "expires_in": _ttl})
    response.set_cookie(_cookie, browser_token, httponly=True, samesite="lax", max_age=_ttl, path="/api/connections/openrouter")
    return response


@connection_router.get("/api/connections/openrouter/callback")
def complete_connection(request: Request):
    origin = _local_origin(request)
    query = request.query_params
    state, code = query.get("state", ""), query.get("code", "")
    # Do not leave single-use authorization codes in Uvicorn access logs.
    request.scope["query_string"] = b""
    with _lock:
        pending = _pending.get(state)
        valid = (pending and time.monotonic() - pending["created"] <= _ttl and pending["origin"] == origin
                 and secrets.compare_digest(pending["browser"], request.cookies.get(_cookie, "")))
        if valid:
            _pending.pop(state)
    result = "failed"
    if valid and code and len(code) <= 2048:
        try:
            response = requests.post("https://openrouter.ai/api/v1/auth/keys", json={"code": code,
                "code_verifier": pending["verifier"], "code_challenge_method": "S256"}, timeout=20, allow_redirects=False)
            response.raise_for_status()
            save_connection(response.json()["key"])
            result = "connected"
        except Exception:
            # Provider responses can contain credentials. Only surface a stable
            # status to the local UI; never echo raw exceptions or token payloads.
            pass
    redirect = RedirectResponse(origin + "/#settings?connection=" + result, status_code=303)
    redirect.delete_cookie(_cookie, path="/api/connections/openrouter")
    return redirect


@connection_router.delete("/api/connections/openrouter")
def disconnect_connection(request: Request):
    _local_origin(request, write=True)
    clear_connection()
    return {"connected": False}
