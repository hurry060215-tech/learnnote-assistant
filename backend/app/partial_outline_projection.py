"""Validate saved temporal excerpts against the current transcript, without AI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .draft_sections import draft_sections_document
from .models import TranscriptResult


def partial_outline(document: object, transcript: TranscriptResult, events: Path, attempt: str) -> dict:
    expected = draft_sections_document(transcript)
    if json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False) != json.dumps(expected, ensure_ascii=False, sort_keys=True, allow_nan=False):
        return {"sections": [], "revision": "", "reason": "invalid_artifact"}
    if not expected["sections"]:
        return {"sections": [], "revision": "", "reason": "not_ready"}
    active, ready = False, False
    with events.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if not isinstance(event, dict) or type(event.get("schema_version")) is not int or event["schema_version"] != 1:
                return {"sections": [], "revision": "", "reason": "invalid_artifact"}
            details = event.get("details")
            if not isinstance(details, dict):
                return {"sections": [], "revision": "", "reason": "invalid_artifact"}
            if event.get("event") == "pipeline_attempt_started":
                active, ready = details.get("attempt_id") == attempt, False
            elif active and event.get("event") == "draft_ready":
                ready = (details.get("attempt_id") == attempt and details.get("artifact") == "draft.md"
                         and details.get("sections_artifact") == "draft_sections.json" and details.get("summary_generated") is False)
    if not active or not ready:
        return {"sections": [], "revision": "", "reason": "publication_pending"}
    sections = []
    for item in document["sections"]:
        section = {key: item[key] for key in ("id", "kind", "status", "verified", "summary_generated",
                   "start", "end", "source_cue_count", "heading_excerpt")}
        section["excerpts"] = [{key: excerpt[key] for key in ("source_cue_index", "start", "end", "text")} for excerpt in item["excerpts"]]
        section["revision"] = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        sections.append(section)
    return {"sections": sections, "revision": document["revision"], "reason": "ready"}
