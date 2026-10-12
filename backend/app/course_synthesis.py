"""Ephemeral review consent for a single course answer; never edits source data."""
import asyncio
import secrets
import threading
import time

from . import courses
from .course_synthesis_sources import capture, MAX_ANCHORS, MAX_SOURCE_CHARACTERS, MAX_SCAN_ROWS
from .course_synthesis_model import connection, complete, redact, MAX_OUTPUT_TOKENS, MODEL_TIMEOUT_SECONDS
from .graph_snapshot import digest

_lock = threading.Lock()
_previews = {}
_inflight = set()
PREVIEW_SECONDS = 600


def _scope_key(course_id):
    return (str(courses.DATA_DIR.resolve()), course_id)


def _capture(request, course_id, selected):
    value = capture(course_id, request["revision"], request["question"], request["mode"])
    for item in value["evidence"]:
        item["text"] = redact(item["text"], selected["key"])
        item["title"] = redact(item["title"], selected["key"])
        item["locator"] = redact(item["locator"], selected["key"])
    for member in value["members"]:
        member["title"] = redact(member["title"], selected["key"])
    value["scope"]["title"] = redact(value["scope"]["title"], selected["key"])
    return value


def preview(course_id, request):
    selected = connection(request["base_url"], request["model"])
    snapshot = _capture(request, course_id, selected)
    question = redact(request["question"], selected["key"])
    chosen_characters = sum(len(item["text"]) for item in snapshot["evidence"])
    original_characters = sum(item["characters"] for item in snapshot["evidence"])
    blocked = ("course_scan_overflow" if not snapshot["scan"]["complete"]
        else "course_summary_overflow" if request["mode"] == "summary" and (
        snapshot["eligible_anchors"] > MAX_ANCHORS or snapshot["eligible_characters"] > MAX_SOURCE_CHARACTERS)
        else "course_evidence_overflow" if snapshot["oversized_anchors"] or max(original_characters, chosen_characters) > MAX_SOURCE_CHARACTERS or len(question) > 1000
        else "course_evidence_insufficient" if not snapshot["evidence"] else None)
    fingerprint = digest({"request": request, "source": snapshot["fingerprint"], "connection": selected["fingerprint"]})
    result = {"scope": snapshot["scope"], "mode": request["mode"], "question": question,
              "connection": {"base_url": selected["base_url"], "model": selected["model"]},
              "fingerprint": fingerprint, "preview_id": None, "can_submit": blocked is None, "blocking_reason": blocked,
              "evidence": [{key: value for key, value in item.items() if key != "source_fingerprint"} for item in snapshot["evidence"]],
              "members": [{key: value for key, value in member.items() if key not in {"owner_revision", "owner"}} for member in snapshot["members"]],
              "scan": snapshot["scan"],
              "coverage": {"eligible_anchors": snapshot["eligible_anchors"], "eligible_characters": snapshot["eligible_characters"],
                           "selected_anchors": len(snapshot["evidence"]), "selected_characters": chosen_characters,
                           "all_eligible_included": len(snapshot["evidence"]) == snapshot["eligible_anchors"]},
              "limits": {"requests": 1, "source_anchors": MAX_ANCHORS, "source_characters": MAX_SOURCE_CHARACTERS,
                         "output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": MODEL_TIMEOUT_SECONDS,
                         "scan_rows": MAX_SCAN_ROWS, "course_members": 200},
              "monetary_cost": None, "data_leaving_service": ["redacted_question", "source_aliases", "redacted_evidence_text"],
              "warning": "确认后会把上方问题和原文片段发送到所选模型地址；本机网关也可能转发。最多一次请求，可能产生费用，金额未知。AI 综合需核对，出处有效不代表结论正确。"}
    if blocked:
        return result
    now = time.monotonic()
    with _lock:
        for key in list(_previews):
            if _previews[key]["expires"] <= now:
                del _previews[key]
        if len(_previews) >= 256:
            raise ValueError("course_preview_busy")
        token = secrets.token_urlsafe(32)
        _previews[token] = {"scope": _scope_key(course_id), "request": dict(request), "fingerprint": fingerprint,
                            "source": snapshot["fingerprint"], "connection": selected["fingerprint"],
                            "expires": now + PREVIEW_SECONDS, "used": False}
        result["preview_id"] = token
    return result


async def answer(course_id, preview_id, fingerprint, share_source):
    if share_source is not True:
        raise ValueError("course_consent_required")
    scope = _scope_key(course_id)
    with _lock:
        approved = _previews.get(preview_id)
        if (not approved or approved["scope"] != scope or approved["fingerprint"] != fingerprint
                or approved["used"] or approved["expires"] <= time.monotonic()):
            raise ValueError("course_preview_expired")
        if scope in _inflight:
            raise ValueError("course_synthesis_running")
        approved["used"] = True
        _inflight.add(scope)
    try:
        request = approved["request"]
        selected = connection(request["base_url"], request["model"])
        snapshot = _capture(request, course_id, selected)
        if snapshot["fingerprint"] != approved["source"] or selected["fingerprint"] != approved["connection"]:
            raise ValueError("course_preview_stale")
        # Source validation may scan many local rows. Respect a connection
        # change or revocation during that work before dispatching any data.
        selected = connection(request["base_url"], request["model"])
        if selected["fingerprint"] != approved["connection"]:
            raise ValueError("course_preview_stale")
        # No course, storage, settings or consent lock is held during network.
        try:
            result = await complete(selected, redact(request["question"], selected["key"]), request["mode"], snapshot["evidence"])
        except asyncio.TimeoutError:
            raise ValueError("course_model_timeout") from None
        except Exception:
            raise ValueError("course_model_result_rejected") from None
        current_connection = connection(request["base_url"], request["model"])
        current_source = _capture(request, course_id, current_connection)
        if current_source["fingerprint"] != approved["source"] or current_connection["fingerprint"] != approved["connection"]:
            raise ValueError("course_preview_stale")
        return {**result, "scope": snapshot["scope"], "mode": request["mode"], "fingerprint": fingerprint,
                "request_count": 1, "warning": "AI 综合待核对。已核验引用来自本次原文；这不验证模型推论的真假。"}
    finally:
        with _lock:
            _inflight.discard(scope)
