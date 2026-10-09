"""Readable completed vision batches; these are drafts, never final notes.

The additive JSON projection and Markdown can be rebuilt from the existing
vision cache. Source artifacts and previously published notes are not changed.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .claims import build_claim_evidence_map, mark_claims_for_review
from .note_document import normalize_note_markdown
from .observability import read_task_events_after, record_task_event
from .processor_state import check_cancel
from .reading_notes import stamp
from .storage import atomic_write_text, get_task, read_json, task_dir, update_task, write_json
from .summary_outcome import safe_summary_text
from .text_cleanup import TextDecodingError, canonicalize_unicode_text, redact_sensitive_url_values


def _revision(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _valid_section(item: object, source_revision: str) -> bool:
    if not isinstance(item, dict) or item.get("status") != "evidence_pending" or item.get("verified") is not False:
        return False
    if item.get("kind") != "vision_batch" or item.get("summary_generated") is not True or not isinstance(item.get("markdown"), str):
        return False
    if any(type(item.get(key)) not in (int, float) for key in ("start", "end")):
        return False
    windows = item.get("source_windows")
    if not isinstance(windows, list) or not windows or any(not isinstance(window, dict)
            or any(type(window.get(key)) not in (int, float) or not math.isfinite(window[key]) for key in ("start", "end"))
            or window["start"] < 0 or window["end"] < window["start"] for window in windows):
        return False
    expected_id = "vision-" + _revision([source_revision, [[w["start"], w["end"]] for w in windows]])[:24]
    return (item.get("id") == expected_id and item.get("revision") == _revision(item["markdown"])
            and item.get("start") == min(w["start"] for w in windows)
            and item.get("end") == max(w["end"] for w in windows))


def partial_section_callback(task_id: str, transcript):
    attempt_id = read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "")
    return lambda payload: write_partial_section(task_id, transcript, payload, attempt_id=attempt_id)


def _already_notified(task_id: str, revision: str) -> bool:
    cursor = 0
    while events := read_task_events_after(task_id, after=cursor, limit=2000):
        if any(event.get("event") == "partial_section_ready"
               and (event.get("details") or {}).get("revision") == revision for _, event in events):
            return True
        cursor = events[-1][0]
    return False


def write_partial_section(task_id: str, transcript, payload: dict, *, attempt_id: str) -> None:
    """Called by the coordinator after a batch, before dispatching more work."""
    check_cancel(task_id)
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return  # A late completion from an older run cannot replace current drafts.
    task = get_task(task_id)
    root = task_dir(task_id)
    windows = payload["source_windows"]
    if not windows or any(not math.isfinite(float(w[key])) for w in windows for key in ("start", "end")):
        return
    if any(w["start"] < 0 or w["end"] < w["start"] for w in windows):
        return
    start, end = min(w["start"] for w in windows), max(w["end"] for w in windows)
    source_revision = _revision([task.source_identity.media_sha256, transcript.model_dump(mode="json")])
    section_id = "vision-" + _revision([source_revision, [[w["start"], w["end"]] for w in windows]])[:24]
    heading = f"图文章节 {stamp(start)}–{stamp(end)}"
    try:
        text = safe_summary_text(redact_sensitive_url_values(canonicalize_unicode_text(payload["markdown"])))
        normalized = normalize_note_markdown(heading, text, generate_questions=task.options.generate_questions)
        if normalized.report["blocking"]:
            return
        # Apply the same conservative local claim markers as final publication.
        # Even literal quotations stay in an evidence-pending draft section.
        claims = build_claim_evidence_map(task_id, heading, normalized.markdown, transcript)
        markdown = mark_claims_for_review(normalized.markdown, claims)
    except TextDecodingError:
        return
    section = {"id": section_id, "kind": "vision_batch", "status": "evidence_pending",
               "verified": False, "summary_generated": True, "start": start, "end": end,
               "source_windows": windows, "markdown": markdown, "revision": _revision(markdown)}
    try:
        previous = read_json(task_id, "partial_note.json", {})
    except (OSError, ValueError):
        # An interrupted projection is recoverable from the valid batch cache.
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    version = previous.get("schema_version")
    if type(version) is int and version > 1:
        return  # Never overwrite an unknown future schema.
    if type(version) is not int or version != 1:
        previous = {}
    compatible = (previous.get("source_revision") == source_revision
                  and previous.get("generation_revision") == payload["generation_revision"])
    saved = previous.get("sections")
    saved = [item for item in saved if _valid_section(item, source_revision)] if isinstance(saved, list) else []
    sections = {item["id"]: item for item in saved} if compatible else {}
    sections[section_id] = section
    document = {"schema_version": 1, "status": "draft", "verified": False,
                "source_revision": source_revision, "generation_revision": payload["generation_revision"],
                "sections": sorted(sections.values(), key=lambda item: (item["start"], item["end"], item["id"]))}
    document["revision"] = _revision(document)
    check_cancel(task_id)
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return
    write_json(task_id, "partial_note.json", document)
    source_draft = root / "draft.md"
    prefix = source_draft.read_text(encoding="utf-8") if source_draft.is_file() else "# 图文章节草稿\n"
    lines = [prefix.rstrip(), "", "## 已生成的图文章节（草稿）", "",
             "> 证据补充中：以下批次已生成，后续批次、合并与最终检查尚未全部完成。未验证的内容已标记，请回源核对。", ""]
    for item in document["sections"]:
        first, _, body = item["markdown"].partition("\n")
        lines.extend(["#" + first, "", "> 草稿 · 证据补充中 · 未完成最终校验", "", body.strip(), ""])
    target = root / "draft.partial.md"
    rendered = "\n".join(lines)
    projection_changed = not target.is_file() or target.read_bytes() != rendered.encode("utf-8")
    atomic_write_text(target, rendered)
    check_cancel(task_id)
    current = get_task(task_id)
    note = Path(current.note_path) if current.note_path else None
    can_display = not note or (note.parent.resolve() == root.resolve() and note.name in {"draft.md", target.name})
    if can_display and (projection_changed or current.note_path != str(target) or current.summary_source != "partial-draft"):
        update_task(task_id, note_path=str(target), summary_source="partial-draft")
    # Persist before notification. A replay after a crash repairs Markdown first,
    # but does not create duplicate ready events for an unchanged document.
    if not _already_notified(task_id, document["revision"]):
        record_task_event(task_id, "partial_section_ready", phase="summary", status="draft",
            message="已生成图文章节草稿，证据仍待核对",
            details={"schema_version": 1, "section_id": section_id, "revision": document["revision"],
                     "section_count": len(sections), "artifact": target.name, "verified": False})
