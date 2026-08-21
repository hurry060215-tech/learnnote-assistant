from __future__ import annotations

from . import API_VERSION, APP_VERSION, TASK_SCHEMA_VERSION, UX_PROTOCOL_VERSION
from .adapters import MEDIA_ADAPTER_CONTRACT_VERSION, media_adapter_descriptors


INTEGRATION_MANIFEST_VERSION = 1


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
            "notion_export": "/api/tasks/{task_id}/exports/notion",
        },
        "privacy": {
            "official_cloud": False,
            "accounts_required": False,
            "source_media_in_sanitized_bundle": False,
            "cookies_in_sanitized_bundle": False,
            "signed_urls_in_sanitized_bundle": False,
        },
    }


def notion_export_payload(task, note: str, transcript: dict | None = None) -> dict:
    """Build a local Notion API-compatible block payload without contacting Notion."""
    blocks: list[dict] = []
    for raw_line in str(note or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            block_type, text = "heading_3", line[4:].strip()
        elif line.startswith("## "):
            block_type, text = "heading_2", line[3:].strip()
        elif line.startswith("# "):
            block_type, text = "heading_1", line[2:].strip()
        elif line.startswith("- ") or line.startswith("* "):
            block_type, text = "bulleted_list_item", line[2:].strip()
        else:
            block_type, text = "paragraph", line
        blocks.append({"object": "block", "type": block_type, block_type: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}})
    payload = {
        "schema_version": 1,
        "integration": "notion",
        "mode": "user_initiated_export_payload",
        "privacy": {"network_request_performed": False, "original_media": False, "cookies": False, "signed_urls": False},
        "parent": {"type": "page_id", "page_id": "<configure-in-Notion>"},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": str(getattr(task, "title", "LearnNote"))[:200]}}]}},
        "children": blocks[:1000],
    }
    if transcript and transcript.get("segments"):
        payload["metadata"] = {"transcript_segment_count": len(transcript["segments"]), "source": "LearnNote local transcript"}
    return payload
