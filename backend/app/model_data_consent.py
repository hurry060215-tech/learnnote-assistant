"""Per-task captured-page scopes; no network calls or persistent approval."""
from __future__ import annotations

import re
import hashlib
import json

from .models import CurrentPageTaskRequest
from .document_exports import sanitize_export_text
from .summary_outcome import safe_summary_text

PAGE_CONTEXT_LIMIT = 4000
PAGE_TEXT_LIMIT = 50000
PAGE_SUBTITLE_LIMIT = 10000


def model_source_text(value: str) -> str:
    """Reuse established export/token redaction; this is not exhaustive DLP."""
    return safe_summary_text(sanitize_export_text(value))


def page_context_excerpt(value: str, limit: int = PAGE_CONTEXT_LIMIT) -> str:
    text = re.sub(r"\s+", " ", model_source_text(value)).strip()
    return text if len(text) <= limit else text[:max(0, limit - 3)].rstrip() + "..."


def approved_page_context(request: CurrentPageTaskRequest) -> str:
    return request.page_text if request.allow_model_page_context else ""


def page_data_fingerprint(request: CurrentPageTaskRequest) -> str:
    data = request.model_dump(mode="json", include={"mode", "title", "page_url", "page_text", "browser_subtitles", "learning_range", "active_video"})
    data["options"] = request.options.model_dump(mode="json", exclude={"llm_api_key"})
    return hashlib.sha256(json.dumps(["model-data-v1", data], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def page_data_preview(request: CurrentPageTaskRequest | None) -> dict | None:
    if request is None:
        return None
    model_used = request.mode != "download_only" and request.options.content_mode != "subtitles"
    supplemental = model_used and request.mode == "video" and bool(request.page_text.strip())
    fallback = model_used and request.mode == "video" and bool(request.page_text.strip() or request.browser_subtitles)
    return {
        "fingerprint": page_data_fingerprint(request),
        "title": model_source_text(request.title), "source_url": model_source_text(request.page_url), "mode": request.mode,
        "context_available": supplemental,
        "context_excerpt": page_context_excerpt(request.page_text) if supplemental else "",
        "context_limit": PAGE_CONTEXT_LIMIT,
        "fallback_available": fallback,
        "page_text_limit": PAGE_TEXT_LIMIT, "subtitle_text_limit": PAGE_SUBTITLE_LIMIT,
        # Local review of the captured source, not a new model request. The
        # existing page-text prompt cleans player UI and applies these limits.
        "captured_page_text": model_source_text(request.page_text) if fallback or request.mode == "page_text" else "",
        "captured_subtitles": model_source_text("\n".join(cue.text for cue in request.browser_subtitles)) if fallback or request.mode == "page_text" else "",
    }
