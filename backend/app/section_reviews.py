"""Ephemeral, single-use consent for chapter text review; no note mutations."""
from __future__ import annotations

import asyncio
import secrets
import threading
import time

from .course_synthesis_model import connection, redact
from .graph_snapshot import digest
from .section_review_sources import capture, select_inputs, MAX_CLAIMS, MAX_SOURCE_CHARACTERS, MAX_CLAIM_CHARACTERS
from .section_review_model import complete, MAX_OUTPUT_TOKENS, MODEL_TIMEOUT_SECONDS
from .storage import task_file

_lock = threading.Lock()
_previews = {}
_inflight = set()
PREVIEW_SECONDS = 600


def _selected(request):
    try:
        return connection(request["base_url"], request["model"])
    except ValueError:
        raise ValueError("review_model_changed") from None


def _scope(task_id):
    return str(task_file(task_id).parent.resolve())


def _snapshot(task_id, request, selected):
    snapshot = capture(task_id, request["revision"])
    inputs = select_inputs(snapshot, request["section_id"], request["offset"],
                           lambda text: redact(text, selected["key"]))
    # Mapping can take time. Do not send a snapshot that changed while its
    # chapter candidates were being selected; no lock crosses a model call.
    if capture(task_id, request["revision"])["fingerprint"] != snapshot["fingerprint"]:
        raise ValueError("review_source_changed")
    return snapshot, inputs


def preview(task_id, request):
    selected = _selected(request)
    snapshot, inputs = _snapshot(task_id, request, selected)
    fingerprint = digest([snapshot["fingerprint"], request, inputs, selected["fingerprint"]])
    result = {**inputs, "task_id": task_id, "revision": request["revision"], "fingerprint": fingerprint,
              "preview_id": None, "connection": {"base_url": selected["base_url"], "model": selected["model"]},
              "can_submit": inputs["blocking_reason"] is None,
              "limits": {"requests": 1, "claims": MAX_CLAIMS, "source_characters": MAX_SOURCE_CHARACTERS,
                         "claim_characters": MAX_CLAIM_CHARACTERS, "output_tokens": MAX_OUTPUT_TOKENS,
                         "timeout_seconds": MODEL_TIMEOUT_SECONDS}, "monetary_cost": None,
              "warning": "确认后仅发送下方结论和原文到所选模型；本机网关也可能转发。最多一次请求，可能收费，金额未知。模型判断不是事实证明，不修改笔记。"}
    if not result["can_submit"]:
        return result
    now = time.monotonic()
    with _lock:
        for key in list(_previews):
            if _previews[key]["expires"] <= now:
                del _previews[key]
        if len(_previews) >= 256:
            raise ValueError("review_busy")
        token = secrets.token_urlsafe(32)
        _previews[token] = {"scope": _scope(task_id), "request": dict(request), "fingerprint": fingerprint,
                            "expires": now + PREVIEW_SECONDS}
        result["preview_id"] = token
    return result


async def review(task_id, preview_id, fingerprint, share_source):
    if share_source is not True:
        raise ValueError("review_consent_required")
    scope = _scope(task_id)
    with _lock:
        approved = _previews.get(preview_id)
        if (not approved or approved["scope"] != scope or approved["fingerprint"] != fingerprint
                or approved["expires"] <= time.monotonic()):
            raise ValueError("review_preview_expired")
        if scope in _inflight:
            raise ValueError("review_busy")
        del _previews[preview_id]
        _inflight.add(scope)
    try:
        request = approved["request"]
        selected = _selected(request)
        snapshot, inputs = _snapshot(task_id, request, selected)
        if digest([snapshot["fingerprint"], request, inputs, selected["fingerprint"]]) != fingerprint:
            raise ValueError("review_source_changed")
        if _selected(request)["fingerprint"] != selected["fingerprint"]:
            raise ValueError("review_model_changed")
        try:
            result = await complete(selected, inputs)
        except asyncio.TimeoutError:
            raise ValueError("review_model_timeout") from None
        except Exception:
            raise ValueError("review_model_rejected") from None
        current = _selected(request)
        latest, current_inputs = _snapshot(task_id, request, current)
        if digest([latest["fingerprint"], request, current_inputs, current["fingerprint"]]) != fingerprint:
            raise ValueError("review_source_changed")
        return {**result, "task_id": task_id, "revision": request["revision"], "section_id": request["section_id"],
                "fingerprint": fingerprint, "coverage": inputs["coverage"], "claims": inputs["claims"],
                "evidence": inputs["evidence"]}
    finally:
        with _lock:
            _inflight.discard(scope)
