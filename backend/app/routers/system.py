from __future__ import annotations

import json
import re
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import DATA_DIR
from ..integrations import integration_manifest
from ..models import TaskOptions
from ..storage import atomic_write_text, get_task
from ..summarizer import chat_completion_provider_kwargs, llm_model_supports_vision, llm_provider_name


system_router = APIRouter(tags=["system"])

TRUSTED_MODEL_API_HOSTS = frozenset({
    "api.openai.com",
    "api.groq.com",
    "generativelanguage.googleapis.com",
    "dashscope.aliyuncs.com",
    "api.deepseek.com",
    "api.moonshot.cn",
    "api.kimi.com",
    "api.xiaomimimo.com",
    "open.bigmodel.cn",
    "ark.cn-beijing.volces.com",
    "api.minimaxi.com",
    "qianfan.baidubce.com",
})
LOCAL_MODEL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ModelSetupCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="custom", min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(default="", max_length=8192)
    mode: Literal["chat", "models"] = "chat"


def _validated_model_endpoint(base_url: str) -> tuple[str, str, bool]:
    try:
        parsed = urlsplit(base_url.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_model_endpoint", "message": "模型地址格式不正确。"}) from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    local = host in LOCAL_MODEL_HOSTS
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail={"code": "invalid_model_endpoint", "message": "模型地址不能包含账号、查询参数或片段。"})
    if local:
        if parsed.scheme != "http":
            raise HTTPException(status_code=422, detail={"code": "invalid_local_model_endpoint", "message": "本地模型地址必须使用 http。"})
    elif parsed.scheme != "https" or host not in TRUSTED_MODEL_API_HOSTS:
        raise HTTPException(status_code=422, detail={"code": "untrusted_model_endpoint", "message": "测试连接仅允许内置供应商或本机模型地址。"})
    return base_url.strip().rstrip("/"), host, local


def _model_check_failure(exc: Exception) -> tuple[str, str]:
    status = int(getattr(exc, "status_code", 0) or 0)
    if status in {401, 403}:
        return "invalid_api_key", "Key 无效或没有访问这个模型的权限。"
    if status == 404:
        return "model_not_found", "没有找到这个模型，请更换模型名称后重试。"
    if status == 429:
        return "quota_or_rate_limit", "供应商暂时限流或额度不足，请检查账户额度后重试。"
    error_name = type(exc).__name__.lower()
    if "timeout" in error_name:
        return "model_timeout", "连接供应商超时，请检查网络或 Base URL。"
    if "connection" in error_name:
        return "model_connection_failed", "无法连接供应商，请检查网络或 Base URL。"
    return "model_check_failed", "供应商返回了无法完成测试的响应，请检查模型名称和账户权限。"


@system_router.post("/api/model/setup/check")
def check_model_setup(payload: ModelSetupCheckRequest) -> dict:
    base_url, host, local = _validated_model_endpoint(payload.base_url)
    if not payload.api_key.strip() and not local:
        return {"ok": False, "code": "missing_api_key", "message": "请先填写 API Key。", "provider": payload.provider, "model": payload.model}
    started = time.monotonic()
    try:
        from openai import OpenAI

        client = OpenAI(api_key=payload.api_key.strip() or "local-no-key", base_url=base_url, timeout=18.0, max_retries=0)
        if payload.mode == "models":
            response = client.models.list()
            model_ids = sorted({
                str(item.id).strip()
                for item in response.data
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", str(getattr(item, "id", "")).strip())
            })[:80]
            return {
                "ok": True,
                "mode": "models",
                "provider": payload.provider,
                "provider_name": llm_provider_name(base_url),
                "model": payload.model,
                "models": model_ids,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "message": f"已发现 {len(model_ids)} 个模型。",
            }
        provider_kwargs = chat_completion_provider_kwargs(base_url)
        provider_kwargs["temperature"] = 0
        response = client.chat.completions.create(
            model=payload.model,
            messages=[{"role": "user", "content": "Reply with OK only."}],
            max_tokens=4,
            **provider_kwargs,
        )
        content = str(response.choices[0].message.content or "").strip()
        if not content:
            return {"ok": False, "code": "empty_model_response", "message": "模型已连接，但没有返回文本。", "provider": payload.provider, "model": payload.model}
        return {
            "ok": True,
            "mode": "chat",
            "provider": payload.provider,
            "provider_name": llm_provider_name(base_url),
            "model": payload.model,
            "supports_vision": llm_model_supports_vision(base_url, payload.model),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "message": "短对话验证通过，可以用于 LearnNote。",
        }
    except Exception as exc:
        code, message = _model_check_failure(exc)
        return {"ok": False, "code": code, "message": message, "provider": payload.provider, "model": payload.model, "host": host}


@system_router.get("/api/integrations/manifest")
def api_integrations_manifest() -> dict:
    return integration_manifest()


@system_router.post("/api/desktop/focus")
def desktop_focus(request: Request, payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    task_id = str(body.get("task_id") or "").strip()
    if task_id:
        if len(task_id) != 12 or any(char not in "0123456789abcdef" for char in task_id):
            raise HTTPException(status_code=422, detail={"code": "invalid_task_id", "message": "Invalid task id"})
        try:
            get_task(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "Task not found"}) from exc
    callback = getattr(request.app.state, "desktop_focus", None)
    if not callable(callback):
        return {"ok": False, "available": False, "task_id": task_id}
    try:
        callback(body)
    except Exception:
        return {"ok": False, "available": True, "task_id": task_id, "code": "focus_failed"}
    return {"ok": True, "available": True, "focused": True, "task_id": task_id}


@system_router.get("/api/preferences")
def get_preferences() -> dict:
    path = DATA_DIR / "preferences.json"
    if not path.is_file():
        return {"task_options": TaskOptions().model_dump(exclude={"llm_api_key", "llm_base_url", "llm_model"})}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        options = TaskOptions.model_validate(payload.get("task_options") or {})
    except (OSError, ValueError, ValidationError):
        options = TaskOptions()
    return {"task_options": options.model_dump(exclude={"llm_api_key", "llm_base_url", "llm_model"})}


@system_router.put("/api/preferences")
def put_preferences(payload: dict = Body(...)) -> dict:
    try:
        options = TaskOptions.model_validate(payload.get("task_options") or {})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid task preferences") from exc
    public_options = options.model_dump(exclude={"llm_api_key", "llm_base_url", "llm_model"})
    atomic_write_text(DATA_DIR / "preferences.json", json.dumps({"task_options": public_options}, ensure_ascii=False, indent=2))
    return {"ok": True, "task_options": public_options}
