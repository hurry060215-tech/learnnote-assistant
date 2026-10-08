"""Preview and download only; intentionally no support sender endpoint."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import activation
from ..config import DATA_DIR

router = APIRouter(prefix="/api/support", tags=["local-support"])


class SupportFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: list[str] = Field(default_factory=list, max_length=6)


class ActivationSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/activation")
def activation_state():
    return activation.snapshot(DATA_DIR)


@router.put("/activation")
def configure_activation(payload: ActivationSetting):
    return activation.set_enabled(DATA_DIR, payload.enabled)


@router.delete("/activation")
def clear_activation():
    return activation.clear(DATA_DIR)


@router.post("/preview")
def preview_support(payload: SupportFields):
    try:
        return activation.support_summary(DATA_DIR, payload.fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/export")
def export_support(payload: SupportFields):
    return JSONResponse(preview_support(payload), headers={
        "Content-Disposition": 'attachment; filename="learnnote-support-summary.json"',
        "Cache-Control": "no-store"})
