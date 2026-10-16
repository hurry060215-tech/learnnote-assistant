"""Readable completed source batches; these are drafts, never final notes.

The additive JSON projection and Markdown can be rebuilt from the existing
vision cache or completed text requests. Source artifacts and published notes stay intact.
"""
from __future__ import annotations
from .task_artifacts import saved_note_missing
from .task_paths import artifact_name

from contextlib import nullcontext
from pathlib import Path

from .observability import read_task_events_after, record_task_event
from .processor_state import check_cancel
from .storage import atomic_write_text, get_task, read_json, update_task, write_json
from .storage import _lock as _task_data_lock
from .partial_section_content import prepare_partial_section
from .section_evidence_status import evidence_status_label
from .partial_note_projection import partial_revision as _revision, valid_partial_section as _valid_section, prepare_legacy_partial, preserve_previous_partial


def partial_section_callback(task_id: str, transcript):
    attempt_id = read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "")
    source_revision = _revision([get_task(task_id).source_identity.media_sha256, transcript.model_dump(mode="json")])
    return lambda payload: write_partial_section(task_id, transcript, payload, attempt_id=attempt_id,
        expected_source_revision=source_revision)


def _already_notified(task_id: str, revision: str) -> bool:
    cursor = 0
    while events := read_task_events_after(task_id, after=cursor, limit=2000):
        if any(event.get("event") == "partial_section_ready"
               and (event.get("details") or {}).get("revision") == revision for _, event in events):
            return True
        cursor = events[-1][0]
    return False


def write_partial_section(task_id: str, transcript, payload: dict, *, attempt_id: str,
                          expected_source_revision: str | None = None) -> None:
    # Expensive claim matching must not stall unrelated task reads or cancellation.
    prepared = prepare_partial_section(task_id, transcript, payload, attempt_id=attempt_id,
        expected_source_revision=expected_source_revision)
    if prepared is None:
        return
    # Serialize the final validation/read/merge/write/event with attempt changes.
    with _task_data_lock if payload.get("kind") in {"topic_chapter", "full_response"} else nullcontext():
        _write_partial_section(task_id, transcript, payload, prepared, attempt_id=attempt_id)


def _write_partial_section(task_id: str, transcript, payload: dict, prepared, *, attempt_id: str) -> None:
    """Called by the coordinator after a batch, before dispatching more work."""
    root, source_revision, text_blocks, section = prepared
    section_id = section["id"]
    check_cancel(task_id)
    saved_note_missing(get_task(task_id))  # Reject an uncertain prior pointer before any draft writes.
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return
    if (payload.get("kind") in {"topic_chapter", "full_response"}
            and (read_json(task_id, "transcript.json", None) != transcript.model_dump(mode="json")
                 or _revision([get_task(task_id).source_identity.media_sha256, transcript.model_dump(mode="json")]) != source_revision)):
        return
    try:
        previous = read_json(task_id, "partial_note.json", {})
    except (OSError, ValueError):
        # An interrupted projection is recoverable from the valid batch cache.
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    if (payload.get("kind") in {"topic_chapter", "full_response"} and previous.get("attempt_id") == attempt_id
            and (previous.get("source_revision") != source_revision
                 or previous.get("generation_revision") != payload["generation_revision"])):
        return  # A different generation requires a fresh pipeline attempt.
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
                "sections": sorted(sections.values(), key=lambda item: (item.get("chapter_index", item.get("block_index", item.get("start", 0))), item.get("end", 0), item["id"]))}
    document["revision"] = _revision(document)
    check_cancel(task_id)
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return
    if (payload.get("kind") in {"topic_chapter", "full_response"}
            and (read_json(task_id, "transcript.json", None) != transcript.model_dump(mode="json")
                 or _revision([get_task(task_id).source_identity.media_sha256, transcript.model_dump(mode="json")]) != source_revision)):
        return
    write_json(task_id, "partial_note.json", document)
    source_draft = root / "draft.md"
    prefix = source_draft.read_text(encoding="utf-8") if source_draft.is_file() else "# 分段草稿\n"
    lines = [prefix.rstrip(), "", "## 已生成的分段草稿", "",
             "> 草稿：以下批次已生成，后续批次、合并与最终检查尚未全部完成。章节状态只说明原文匹配进度，不代表事实核验，请回源核对。", ""]
    for item in document["sections"]:
        first, _, body = item["markdown"].partition("\n")
        lines.extend(["#" + first, "", "> " + evidence_status_label(item), "", body.strip(), ""])
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
    can_display = not current.note_path or artifact_name(current.note_path) in {"draft.md", target.name}
    if can_display and (projection_changed or current.note_path != str(target) or current.summary_source != "partial-draft"):
        update_task(task_id, note_path=str(target), summary_source="partial-draft")
    # Persist before notification. A replay after a crash repairs Markdown first,
    # but does not create duplicate ready events for an unchanged document.
    if not _already_notified(task_id, document["revision"]):
        record_task_event(task_id, "partial_section_ready", phase="summary", status="draft",
            message="已生成分段草稿，待最终来源检查",
            details={"schema_version": 1, "section_id": section_id, "revision": document["revision"],
                     "section_count": len(sections), "kind": section["kind"], "artifact": target.name, "verified": False})
