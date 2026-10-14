"""Prepare draft content without holding the task-storage publication lock."""
from __future__ import annotations

import math
import re

from .section_evidence_status import section_claim_map, evidence_status
from .note_document import normalize_note_markdown
from .processor_state import check_cancel
from .reading_notes import source_block_entries, stamp
from .storage import get_task, read_json, task_dir
from .summary_outcome import safe_summary_text
from .text_cleanup import TextDecodingError, canonicalize_unicode_text, redact_sensitive_url_values
from .text_chunk_sections import text_chunk_source
from .full_response_sections import full_response_source
from .chapter_sections import chapter_markdown_complete, chapter_provenance, prepare_topic_source
from .partial_note_projection import partial_revision as _revision


def prepare_partial_section(task_id, transcript, payload, *, attempt_id, expected_source_revision):
    check_cancel(task_id)
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return  # A late completion from an older run cannot replace current drafts.
    task = get_task(task_id)
    root = task_dir(task_id)
    if payload.get("kind") not in (None, "vision_batch", "text_chunk", "topic_chapter", "full_response"):
        return
    source_revision = _revision([task.source_identity.media_sha256, transcript.model_dump(mode="json")])
    text_blocks = []
    if payload.get("kind") == "topic_chapter":
        source, text_blocks = prepare_topic_source(task_id, transcript, payload, source_revision, expected_source_revision)
        if source is None:
            return
        heading = source["title"]
    elif payload.get("kind") == "full_response":
        if (not re.fullmatch(r"[a-f0-9]{64}", str(payload.get("generation_revision", "")))
                or expected_source_revision is not None and source_revision != expected_source_revision
                or read_json(task_id, "transcript.json", None) != transcript.model_dump(mode="json")):
            return
        text_blocks = source_block_entries(transcript)
        source = full_response_source(payload, text_blocks, source_revision)
        if source is None:
            return
        heading = "完整响应草稿"
    elif payload.get("kind") == "text_chunk":
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
    try:
        text = safe_summary_text(redact_sensitive_url_values(canonicalize_unicode_text(payload["markdown"])))
        if payload.get("kind") in {"topic_chapter", "full_response"}:
            text = chapter_provenance(source, text_blocks) + "\n\n" + text
        normalized = normalize_note_markdown(heading, text, generate_questions=task.options.generate_questions)
        if normalized.report["blocking"] or (payload.get("kind") in {"topic_chapter", "full_response"} and not chapter_markdown_complete(normalized.markdown)):
            return
        # Keep draft prose readable. The chapter-level status reports the same
        # conservative claim map; no claim is promoted to factual verification.
        # Final publication still runs its existing independent evidence gate.
        claims = section_claim_map(task_id, source, normalized.markdown, transcript, text_blocks)
        markdown = normalized.markdown
    except TextDecodingError:
        return
    section = {**source, "status": "evidence_pending", "verified": False,
               "summary_generated": True, "markdown": markdown, "revision": _revision(markdown),
               "evidence_status": evidence_status(claims, transcript)}
    return root, source_revision, text_blocks, section

