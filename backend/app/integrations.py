from __future__ import annotations

import json

from . import API_VERSION, APP_VERSION, TASK_SCHEMA_VERSION, UX_PROTOCOL_VERSION
from .adapters import MEDIA_ADAPTER_CONTRACT_VERSION, media_adapter_descriptors
from .document_exports import _blocks, sanitize_export_text
from .note_document import strip_note_frontmatter


INTEGRATION_MANIFEST_VERSION = 2
_NOTION_TEXT_UTF16_LIMIT = 2000
_NOTION_RICH_TEXT_PER_BLOCK = 8
_NOTION_ARRAY_LIMIT = 100
_NOTION_REQUEST_BYTES = 450_000


def integration_manifest() -> dict:
    return {
        "schema_version": INTEGRATION_MANIFEST_VERSION,
        "product": "learnnote-assistant",
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "protocol_version": UX_PROTOCOL_VERSION,
        "task_schema_version": TASK_SCHEMA_VERSION,
        "media_adapter_contract_version": MEDIA_ADAPTER_CONTRACT_VERSION,
        "media_adapters": media_adapter_descriptors(),
        "exports": {
            "markdown": "/api/tasks/{task_id}/exports/markdown",
            "bundle": "/api/tasks/{task_id}/exports/bundle",
            "sanitized_bundle": "/api/tasks/{task_id}/exports/sanitized-bundle",
            "support_package": "/api/tasks/{task_id}/exports/support-package",
            "events": "/api/tasks/{task_id}/events",
            "events_stream": "/api/tasks/{task_id}/events/stream",
            "note_document": "/api/tasks/{task_id}/note-document",
            "notion_export": "/api/tasks/{task_id}/exports/notion",
            "word": "/api/tasks/{task_id}/exports/docx",
            "pdf": "/api/tasks/{task_id}/exports/pdf",
        },
        "local_services": {
            "library_materials": "/api/library/materials",
            "library_material_import": "/api/library/materials/import",
            "library_material_delete": "/api/library/materials/{material_id}?confirm=delete_material",
            "library_local_video_registration": "/api/library/materials/register-task/{task_id}",
            "study_dashboard": "/api/study/dashboard",
            "study_data_delete": "/api/study/data?confirm=delete_all_study_data",
            "community_settings": "/api/study/community/settings",
            "community_data_delete": "/api/study/community/data?confirm=delete_all_community_context",
            "community_context": "/api/tasks/{task_id}/community-context",
        },
        "privacy": {
            "official_cloud": False,
            "accounts_required": False,
            "telemetry": False,
            "source_media_in_sanitized_bundle": False,
            "cookies_in_sanitized_bundle": False,
            "signed_urls_in_sanitized_bundle": False,
            "community_context_in_primary_evidence": False,
        },
    }


def _notion_rich_text(value: str) -> list[dict]:
    """Split already sanitized text without cutting an astral character."""
    text = value
    pieces: list[dict] = []
    start = units = 0
    for index, character in enumerate(text):
        width = 2 if ord(character) > 0xFFFF else 1
        if units + width > _NOTION_TEXT_UTF16_LIMIT:
            pieces.append({"type": "text", "text": {"content": text[start:index]}})
            start, units = index, 0
        units += width
    pieces.append({"type": "text", "text": {"content": text[start:]}})
    return pieces


def _notion_request_size(request: dict) -> int:
    # Reserve headroom below Notion's 500KB request cap, even for consumers
    # that escape Unicode and pretty-print JSON rather than emitting UTF-8.
    return len(json.dumps(request, ensure_ascii=True, indent=2).encode("utf-8"))


def _notion_child_batches(blocks: list[dict], create_fields: dict) -> list[list[dict]]:
    batches: list[list[dict]] = [[]]
    if _notion_request_size({**create_fields, "children": []}) >= _NOTION_REQUEST_BYTES:
        raise ValueError("notion_title_exceeds_request_limit")
    for block in blocks:
        current = batches[-1]
        fields = create_fields if len(batches) == 1 else {}
        candidate = {**fields, "children": [*current, block]}
        if len(current) >= _NOTION_ARRAY_LIMIT or _notion_request_size(candidate) >= _NOTION_REQUEST_BYTES:
            batches.append([])
        batches[-1].append(block)
    return batches


def notion_export_payload(task, note: str, transcript: dict | None = None) -> dict:
    """Build a lossless, local-only plan for Notion create and append requests.

    Send only parent/properties/children when creating a page, then append each
    append_batches entry to that new page in order. This function sends nothing.
    Content is sanitized before chunking; metadata counts describe that content.
    Limits: https://developers.notion.com/reference/request-limits
    """
    blocks: list[dict] = []
    kinds = {"bullet": "bulleted_list_item", "ordered": "numbered_list_item",
             "quote": "quote", "code": "code"}
    # Redact before paragraph folding so a secret on one source line cannot
    # consume the safe text on the next line when the parser joins them.
    safe_note = sanitize_export_text(strip_note_frontmatter(str(note or "")))
    for block in _blocks(safe_note):
        block_type = f"heading_{min(block.level, 3)}" if block.kind == "heading" else kinds.get(block.kind, "paragraph")
        rich_text = _notion_rich_text(block.text)
        for start in range(0, len(rich_text), _NOTION_RICH_TEXT_PER_BLOCK):
            content = {"rich_text": rich_text[start:start + _NOTION_RICH_TEXT_PER_BLOCK]}
            if block_type == "code":
                content["language"] = "plain text"
            blocks.append({"object": "block", "type": block_type, block_type: content})
    title = _notion_rich_text(sanitize_export_text(str(getattr(task, "title", "LearnNote"))))
    if len(title) > _NOTION_ARRAY_LIMIT:
        # A title cannot be continued with append-block requests. Reject this
        # exceptional input explicitly rather than silently discarding it.
        raise ValueError("notion_title_exceeds_rich_text_limit")
    create_fields = {
        "parent": {"type": "page_id", "page_id": "<configure-in-Notion>"},
        "properties": {"title": {"title": title}},
    }
    batches = _notion_child_batches(blocks, create_fields)
    payload = {
        "schema_version": 2,
        "integration": "notion",
        "mode": "user_initiated_export_payload",
        "privacy": {"network_request_performed": False, "original_media": False, "cookies": False, "signed_urls": False},
        **create_fields,
        "children": batches[0],
        "append_batches": [{"children": children} for children in batches[1:]],
        "metadata": {"block_count": len(blocks), "batch_count": len(batches), "content_truncated": False},
    }
    if transcript and transcript.get("segments"):
        payload["metadata"].update({"transcript_segment_count": len(transcript["segments"]), "source": "LearnNote local transcript"})
    return payload
