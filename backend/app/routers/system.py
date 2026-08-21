from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import ValidationError

from ..config import DATA_DIR
from ..integrations import integration_manifest
from ..models import TaskOptions
from ..storage import atomic_write_text, get_task


system_router = APIRouter(tags=["system"])


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
