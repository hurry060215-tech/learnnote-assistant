"""Bounded ephemeral consent; selected opinions never enter ordinary QA history."""
from __future__ import annotations

from copy import deepcopy
import secrets
import threading
import time

from . import assistant_stream, community, model_connections, storage
from .community_capture import MAX_PENDING_PREVIEWS, MAX_PENDING_PREVIEWS_PER_DIRECTORY, PREVIEW_TTL_SECONDS
from .config import LLM_MAX_RETRIES, LLM_REQUEST_TIMEOUT_SECONDS
from .course_synthesis_model import connection, redact
from .graph_snapshot import digest
from .selected_opinion_sources import capture, messages
from .summarizer import chat_completion_provider_kwargs, llm_provider_name

_lock = threading.RLock()
_previews = {}
_inflight = set()
WARNING = ("整个回答均为未经核实的观点辅助输出。仅发送下方问题、原始字幕摘录和所选观点到所示模型；"
           "本机网关也可能转发。一次逻辑回答可能有一次兼容性重试，可能收费且金额未知。"
           "关闭或停止不能撤回已发送内容，远端仍可能处理或计费。结果仅保留在当前窗口。")


def _scope():
    return (str(storage.TASK_DIR.resolve()), str(community.DATA_DIR.resolve()), str(model_connections.DATA_DIR.resolve()))


def _selected(request):
    try:
        value = connection(request["base_url"], request["model"])
        # Never hide a different recipient behind a redacted display substitute.
        if (redact(value["model"], value["key"]) != value["model"]
                or value["key"] != "local-no-key" and value["key"] in value["base_url"]):
            raise ValueError("opinion_model_changed")
        return value
    except (ValueError, OSError):
        raise ValueError("opinion_model_changed") from None


def _prune():
    for token, entry in list(_previews.items()):
        if entry["expires"] <= time.monotonic() or entry["generation"] != community.community_preview_generation():
            del _previews[token]


def _fingerprint(token, request, inputs, selected, scope, generation):
    return digest([token, request, inputs, selected["fingerprint"], scope, generation,
                   chat_completion_provider_kwargs(selected["base_url"])])


def preview(task_id, request):
    with storage._lock, community._lock, _lock:
        _prune()
        selected = _selected(request)
        request = {**request, "question": redact(request["question"], selected["key"])}
        inputs = capture(task_id, request, selected)
        scope, generation = _scope(), community.community_preview_generation()
        for token, entry in list(_previews.items()):
            if entry["scope"] == scope and entry["task_id"] == task_id:
                del _previews[token]  # A new preview supersedes this task's prior review.
        if (len(_previews) >= MAX_PENDING_PREVIEWS
                or sum(entry["scope"] == scope for entry in _previews.values()) >= MAX_PENDING_PREVIEWS_PER_DIRECTORY):
            raise ValueError("opinion_preview_busy")
        token = secrets.token_hex(32)
        fingerprint = _fingerprint(token, request, inputs, selected, scope, generation)
        result = {"preview_id": token if not inputs["blocking_reason"] else None, "fingerprint": fingerprint,
                  "task_id": task_id, "question": request["question"], "selected_item_ids": request["selected_item_ids"],
                  "connection": {"base_url": selected["base_url"], "model": selected["model"]},
                  **{key: value for key, value in inputs.items() if key != "binding"},
                  "messages": messages(request["question"], inputs), "can_submit": inputs["blocking_reason"] is None,
                  "expires_in_seconds": PREVIEW_TTL_SECONDS, "persisted": False, "fact_verified": False,
                  "evidence_eligible": False, "model_request_performed": False, "warning": WARNING,
                  "limits": {"opinion_items": 20, "opinion_characters": 20000, "original_source_items": 24,
                             "original_source_characters": 12000, "stream_timeout_seconds": 180,
                             "stream_client_timeout_seconds": 30, "stream_sdk_retries": 0,
                             "stream_compatibility_retries": 1, "execution": "stream_only"}, "monetary_cost": None}
        if result["can_submit"]:
            _previews[token] = {"task_id": task_id, "scope": scope, "generation": generation, "request": request,
                                "fingerprint": fingerprint, "result": deepcopy(result), "used": False,
                                "expires": time.monotonic() + PREVIEW_TTL_SECONDS}
        return result


def answer(task_id, request, *, emit=None, control=None):
    if emit is None:
        raise ValueError("opinion_stream_required")
    consent = request.selected_opinions
    if (consent is None or consent.confirm_send is not True or request.skill_id != "note.qa"
            or request.options is not None):
        raise ValueError("opinion_consent_required")
    token = consent.preview_id
    with storage._lock, community._lock, _lock:
        _prune()
        entry = _previews.get(token)
        if not entry or entry["task_id"] != task_id or entry["scope"] != _scope() or entry["used"]:
            raise ValueError("opinion_preview_expired")
        entry["used"] = True  # Every attempted task-bound use consumes approval.
        submitted = {"question": request.question, "selected_item_ids": consent.selected_item_ids,
                     "base_url": consent.base_url, "model": consent.model}
        if submitted != entry["request"] or consent.fingerprint != entry["fingerprint"]:
            del _previews[token]
            raise ValueError("opinion_preview_changed")
        flight = (entry["scope"], task_id)
        if flight in _inflight:
            del _previews[token]
            raise ValueError("opinion_preview_busy")
        _inflight.add(flight)

    def validate():
        if control is not None:
            control.check()
        with storage._lock, community._lock, _lock:
            _prune()
            if _previews.get(token) is not entry or _scope() != entry["scope"]:
                raise ValueError("opinion_preview_expired")
            current = _selected(entry["request"])
            inputs = capture(task_id, entry["request"], current)
            if _fingerprint(token, entry["request"], inputs, current, _scope(), community.community_preview_generation()) != entry["fingerprint"]:
                raise ValueError("opinion_source_changed")
            return current

    try:
        selected = validate()
        # Reuse genuine streaming/cancellation internally, but release no deltas
        # before final scope validation. completion_text retains its own bound.
        text = assistant_stream.qa_completion(api_key=selected["key"], base_url=selected["base_url"],
            timeout=30 if emit is not None else LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=0 if emit is not None else LLM_MAX_RETRIES,
            emit=(lambda _event, _data: None) if emit is not None else None,
            control=control, before_dispatch=validate, model=selected["model"],
            messages=deepcopy(entry["result"]["messages"]), **chat_completion_provider_kwargs(selected["base_url"]))
        validate()
        if not isinstance(text, str) or not text.strip():
            raise ValueError("opinion_model_failed")
        return {"answer": redact(text.strip(), selected["key"]), "source": "selected-opinions-unverified",
                "warning": WARNING, "provider": llm_provider_name(selected["base_url"]), "model": selected["model"],
                "citations": [], "original_sources": entry["result"]["original_sources"],
                "opinions": entry["result"]["opinions"], "fact_verified": False, "evidence_eligible": False,
                "persisted": False}
    except assistant_stream.StreamFailure as exc:
        if exc.code == "answer_incomplete":
            raise assistant_stream.StreamFailure(exc.code, "模型未完成回答，未展示或保存不完整回答。请重新预览；远端仍可能计费。") from None
        raise
    finally:
        with _lock:
            _previews.pop(token, None)
            _inflight.discard(flight)
