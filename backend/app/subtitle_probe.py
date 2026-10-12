"""Bounded diagnostic metadata; never keep browser payloads or error text."""
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STATUSES = {"unknown", "ready", "not_found", "auth_required", "unavailable", "untrusted_subtitle_host", "source_changed"}


class SubtitleProbe(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: Literal["unknown", "ready", "not_found", "auth_required", "unavailable", "untrusted_subtitle_host", "source_changed"] = "unknown"
    language: str = Field(default="", max_length=32, pattern=r"^[A-Za-z0-9_-]*$")
    cue_count: int = Field(default=0, ge=0, le=10000)
    elapsed_ms: int = Field(default=0, ge=0, le=3600000)
    cache_hit: bool = False

    @model_validator(mode="before")
    @classmethod
    def safe_metadata(cls, value):
        if not isinstance(value, dict):
            return {}

        def bounded(name, maximum):
            number = value.get(name, 0)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                return 0
            if isinstance(number, float) and not math.isfinite(number):
                return 0
            return int(min(maximum, max(0, number)))

        language = value.get("language", "")
        status = value.get("status")
        return {
            "status": status if isinstance(status, str) and status in STATUSES else "unknown",
            "language": language if isinstance(language, str) and re.fullmatch(r"[A-Za-z0-9_-]{0,32}", language) else "",
            "cue_count": bounded("cue_count", 10000),
            "elapsed_ms": bounded("elapsed_ms", 3600000),
            "cache_hit": value.get("cache_hit") is True,
        }
