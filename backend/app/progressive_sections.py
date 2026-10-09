"""Readable completed source batches; these are drafts, never final notes.

The additive JSON projection and Markdown can be rebuilt from the existing
vision cache or completed text requests. Source artifacts and published notes stay intact.
"""
from __future__ import annotations

import math
from pathlib import Path

from .claims import build_claim_evidence_map, mark_claims_for_review
from .note_document import normalize_note_markdown
from .observability import read_task_events_after, record_task_event
from .processor_state import check_cancel
from .reading_notes import source_block_entries, stamp
from .storage import atomic_write_text, get_task, read_json, task_dir, update_task, write_json
from .summary_outcome import safe_summary_text
from .text_cleanup import TextDecodingError, canonicalize_unicode_text, redact_sensitive_url_values
from .text_chunk_sections import text_chunk_source
from .partial_note_projection import partial_revision as _revision, valid_partial_section as _valid_section, prepare_legacy_partial, preserve_previous_partial


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
    if payload.get("kind") not in (None, "vision_batch", "text_chunk"):
        return
    source_revision = _revision([task.source_identity.media_sha256, transcript.model_dump(mode="json")])
    text_blocks = []
    if payload.get("kind") == "text_chunk":
        text_blocks = source_block_entries(transcript)
        source = text_chunk_source(payload, text_blocks, source_revision)
        if source is None:
            return
        heading = f"文字分段 {source['block_index'] + 1}"
    else:
        windows = payload["source_windows"]
        if not windows or any(not math.isfinite(float(w[key])) for w in windows for key in ("start", "end")):
            return
        if any(w["start"] < 0 or w["end"] < w["start"] for w in windows):
            return
        start, end = min(w["start"] for w in windows), max(w["end"] for w in windows)
        section_id = "vision-" + _revision([source_revision, [[w["start"], w["end"]] for w in windows]])[:24]
        source = {"id": section_id, "kind": "vision_batch", "start": start, "end": end, "source_windows": windows}
        heading = f"图文章节 {stamp(start)}–{stamp(end)}"
    section_id = source["id"]
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
    section = {**source, "status": "evidence_pending", "verified": False,
               "summary_generated": True, "markdown": markdown, "revision": _revision(markdown)}
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
    saved = previous.get("sections")
    try:
        valid_saved = [item for item in saved if _valid_section(item, source_revision, text_blocks)] if isinstance(saved, list) else []
        intact = (bool(valid_saved) and len(valid_saved) == len(saved) and len({item["id"] for item in valid_saved}) == len(saved)
                  and previous.get("status") == "draft" and previous.get("verified") is False
                  and previous.get("revision") == _revision({key: value for key, value in previous.items() if key != "revision"}))
    except (ValueError, TypeError, OverflowError, RuntimeError):
        valid_saved, intact = [], False
    compatible = (intact and previous.get("source_revision") == source_revision
                  and previous.get("generation_revision") == payload["generation_revision"]
                  and previous.get("attempt_id") == attempt_id)
    try:
        if not previous.get("attempt_id"):
            compatible = prepare_legacy_partial(root, previous, attempt_id, source_revision, payload["generation_revision"], text_blocks)
        elif not compatible:
            preserve_previous_partial(root)
    except (OSError, ValueError, TypeError, RuntimeError):
        return  # Never replace previous chapters when preservation failed.
    sections = {item["id"]: item for item in valid_saved} if compatible else {}
    sections[section_id] = section
    document = {"schema_version": 1, "status": "draft", "verified": False, "attempt_id": attempt_id,
                "source_revision": source_revision, "generation_revision": payload["generation_revision"],
                "sections": sorted(sections.values(), key=lambda item: (item.get("block_index", item.get("start", 0)), item.get("end", 0), item["id"]))}
    document["revision"] = _revision(document)
    check_cancel(task_id)
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return
    write_json(task_id, "partial_note.json", document)
    source_draft = root / "draft.md"
    prefix = source_draft.read_text(encoding="utf-8") if source_draft.is_file() else "# 分段草稿\n"
    lines = [prefix.rstrip(), "", "## 已生成的分段草稿", "",
             "> 证据补充中：以下批次已生成，后续批次、合并与最终检查尚未全部完成。未验证的内容已标记，请回源核对。", ""]
    for item in document["sections"]:
        first, _, body = item["markdown"].partition("\n")
        lines.extend(["#" + first, "", "> 草稿 · 证据补充中 · 未完成最终校验 · 待最终来源检查", "", body.strip(), ""])
    target = root / "draft.partial.md"
    rendered = "\n".join(lines)
    try:
        # Compare text with universal newlines: Windows text-mode writes use
        # CRLF, but an unchanged replay must preserve stored bytes and revision.
        projection_changed = target.read_text(encoding="utf-8") != rendered
    except (FileNotFoundError, UnicodeDecodeError):
        projection_changed = True
    if projection_changed:
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
            message="已生成分段草稿，待最终来源检查",
            details={"schema_version": 1, "section_id": section_id, "revision": document["revision"],
                     "section_count": len(sections), "kind": source["kind"], "artifact": target.name, "verified": False})
