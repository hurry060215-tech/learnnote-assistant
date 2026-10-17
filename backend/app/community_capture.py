"""Bounded, local, transient review of explicitly supplied visible community text.

No browser access, remote fetch, model calls, raw cache, or task writes belong
here. Only an explicit selection from a live preview can enter community storage.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import community, storage
from .models import TaskRecord


MAX_PREVIEW_ITEMS = 20
MAX_PREVIEW_ITEM_CHARS = 2000
MAX_PREVIEW_CHARS = 20_000
PREVIEW_TTL_SECONDS = 300
MAX_PENDING_PREVIEWS = 64
MAX_PENDING_PREVIEWS_PER_DIRECTORY = 16
NOTICE = "仅为当前可见的少量观众观点；本地规则过滤并非完整隐私检查，不代表课程事实、完整评论或统计共识。"


class VisibleCommunityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["comment", "danmaku"]
    text: str = Field(min_length=1, max_length=MAX_PREVIEW_ITEM_CHARS)
    timestamp_seconds: float | None = Field(default=None, ge=0, le=604800, allow_inf_nan=False)


class CommunityPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page_url: str = Field(min_length=1, max_length=2000)
    items: list[VisibleCommunityItem] = Field(min_length=1, max_length=MAX_PREVIEW_ITEMS)

    @model_validator(mode="after")
    def check_total_chars(self):
        if sum(len(item.text) for item in self.items) > MAX_PREVIEW_CHARS:
            raise ValueError("community_content_too_large")
        return self


class CommunitySaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preview_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_item_ids: list[str] = Field(min_length=1, max_length=MAX_PREVIEW_ITEMS)

    @model_validator(mode="after")
    def check_selection(self):
        if (len(set(self.selected_item_ids)) != len(self.selected_item_ids)
                or any(not re.fullmatch(r"[a-f0-9]{32}", item_id) for item_id in self.selected_item_ids)):
            raise ValueError("community_selection_invalid")
        return self


@dataclass(frozen=True)
class _Preview:
    scope: tuple[str, str]
    task_id: str
    generation: int
    task_revision: str
    source_uri: str
    fingerprint: str
    expires_monotonic: float
    items: tuple[dict, ...]


_preview_lock = threading.RLock()
_previews: OrderedDict[str, _Preview] = OrderedDict()


def _scope() -> tuple[str, str]:
    # Both roots matter when task/community stores are switched independently.
    return (str(storage.TASK_DIR.resolve()), str(community.DATA_DIR.resolve()))


def _prune_previews() -> None:
    now = time.monotonic()
    generation = community.community_preview_generation()
    for preview_id, preview in list(_previews.items()):
        if preview.expires_monotonic <= now or preview.generation != generation:
            del _previews[preview_id]


def invalidate_community_previews(task_id: str | None = None) -> None:
    """Discard an in-memory review without touching persistent data."""
    with _preview_lock:
        scope = _scope()
        for preview_id, preview in list(_previews.items()):
            if preview.scope == scope and (task_id is None or preview.task_id == task_id):
                del _previews[preview_id]


def _task_source(task_id: str, page_url: str) -> tuple[TaskRecord, str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise ValueError("task_not_found")
    try:
        task = storage.get_task(task_id)
    except FileNotFoundError as exc:
        raise ValueError("task_not_found") from exc
    if task.id != task_id or task.source_type != "current_page" or task.mode not in {"video", "subtitle_only"}:
        raise ValueError("community_source_mismatch")
    source = community.canonical_bilibili_source(page_url)
    task_source = community.canonical_bilibili_source(task.page_url)
    identity = task.source_identity
    # Caption completion changes mode, not source. Require the complete
    # current-page admission identity for this path; imported captions lack it.
    if task.mode == "subtitle_only" and (not identity.page_url or identity.platform != "bilibili"
            or not identity.platform_id or not re.fullmatch(r"[a-f0-9]{64}", identity.resource_fingerprint)):
        raise ValueError("community_source_mismatch")
    if (source != task_source
            or (identity.page_url and community.canonical_bilibili_source(identity.page_url) != source)
            or (identity.platform and identity.platform != "bilibili")
            or (identity.platform_id and identity.platform_id != source.split("/video/", 1)[1].split("?", 1)[0])):
        raise ValueError("community_source_mismatch")
    # Progress updates do not change a source. A replaced, retried or re-bound
    # task does. Retain only this digest, never a raw task/identity snapshot.
    binding = {
        "id": task.id, "created_at": task.created_at,
        "source_type": task.source_type, "mode": task.mode,
        "page_url": task.page_url, "source_identity": identity.model_dump(mode="json"),
        "retry_count": task.retry_count, "control_generation": task.control_generation,
    }
    revision = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return task, source, revision


def preview_visible_community(task_id: str, request: CommunityPreviewRequest) -> dict:
    # The task lock prevents a local delete/source switch during validation;
    # unlike the state transaction, it does not create a lease file at preview.
    # Lock order throughout: task -> community -> previews.
    with storage._lock, community._lock, _preview_lock:
        _prune_previews()
        if not community.community_settings()["enabled"]:
            raise ValueError("community_context_disabled")
        _task, source, revision = _task_source(task_id, request.page_url)
        normalized = [community.normalize_community_item({**item.model_dump(), "source_uri": source}) for item in request.items]
        filtered = sum(item is None for item in normalized)
        valid = [item for item in normalized if item is not None]
        seen = community.existing_community_fingerprints(task_id, [item["fingerprint"] for item in valid])
        deduplicated = 0
        items = []
        for item in valid:
            if item["fingerprint"] in seen:
                deduplicated += 1
                continue
            seen.add(item["fingerprint"])
            items.append({"item_id": secrets.token_hex(16), **{key: value for key, value in item.items() if key != "fingerprint"}})
        invalidate_community_previews(task_id)  # A new review supersedes the previous one.
        scope = _scope()
        if len(_previews) >= MAX_PENDING_PREVIEWS or sum(preview.scope == scope for preview in _previews.values()) >= MAX_PENDING_PREVIEWS_PER_DIRECTORY:
            raise ValueError("community_preview_capacity_exceeded")
        preview_id = secrets.token_hex(32)
        fingerprint = hashlib.sha256(json.dumps({"nonce": preview_id, "revision": revision, "items": items}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        _previews[preview_id] = _Preview(scope, task_id, community.community_preview_generation(), revision, source, fingerprint, time.monotonic() + PREVIEW_TTL_SECONDS, tuple(deepcopy(items)))
        return {
            "schema_version": 1, "preview_id": preview_id, "fingerprint": fingerprint,
            "task_id": task_id, "source_uri": source, "items": items,
            "filtered_count": filtered, "deduplicated_count": deduplicated,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
            "expires_in_seconds": PREVIEW_TTL_SECONDS,
            "persisted": False, "storage": "memory-only", "author_identity_exposed": False,
            "network_fetch_performed": False, "model_request_performed": False,
            "evidence_eligible": False, "epistemic_role": "community_perspective_not_source_evidence",
            "notice": NOTICE,
        }


def save_visible_community(task_id: str, request: CommunitySaveRequest) -> dict:
    # Serialize task deletion/source replacement with the last validation and
    # community insert. This transaction is only entered by explicit Save.
    with storage.task_state_transaction(), community._lock, _preview_lock:
        _prune_previews()
        preview = _previews.get(request.preview_id)
        if preview is None or preview.scope != _scope() or preview.task_id != task_id:
            raise ValueError("community_preview_unavailable")
        # Every attempted save of this task-bound token consumes it, including
        # rejected fingerprints/selections. Retries must review a fresh preview.
        del _previews[request.preview_id]
        if not community.community_settings()["enabled"]:
            raise ValueError("community_context_disabled")
        if not hmac.compare_digest(preview.fingerprint, request.fingerprint):
            raise ValueError("community_preview_changed")
        _task, source, revision = _task_source(task_id, preview.source_uri)
        if source != preview.source_uri or revision != preview.task_revision:
            raise ValueError("community_preview_changed")
        selected = set(request.selected_item_ids)
        available = {item["item_id"] for item in preview.items}
        if not selected or len(selected) != len(request.selected_item_ids) or not selected.issubset(available):
            raise ValueError("community_selection_invalid")
        items = [{key: value for key, value in item.items() if key != "item_id"} for item in preview.items if item["item_id"] in selected]
        result = community.add_community_context(task_id, items)
        return {**result, "preview_id": request.preview_id, "model_request_performed": False, "network_fetch_performed": False}
