"""Prepare draft content without holding the task-storage publication lock."""
from __future__ import annotations

import math

from .claims import build_claim_evidence_map, mark_claims_for_review
from .note_document import normalize_note_markdown
from .processor_state import check_cancel
from .reading_notes import source_block_entries, stamp
from .storage import get_task, read_json, task_dir
from .summary_outcome import safe_summary_text
from .text_cleanup import TextDecodingError, canonicalize_unicode_text, redact_sensitive_url_values
from .text_chunk_sections import text_chunk_source
from .chapter_sections import chapter_markdown_complete, chapter_provenance, prepare_topic_source
from .partial_note_projection import partial_revision as _revision


def prepare_partial_section(task_id, transcript, payload, *, attempt_id, expected_source_revision):
    check_cancel(task_id)
    if read_json(task_id, "pipeline_metrics.json", {}).get("current_attempt_id", "") != attempt_id:
        return  # A late completion from an older run cannot replace current drafts.
    task = get_task(task_id)
    root = task_dir(task_id)
    if payload.get("kind") not in (None, "vision_batch", "text_chunk", "topic_chapter"):
        return
    source_revision = _revision([task.source_identity.media_sha256, transcript.model_dump(mode="json")])
    text_blocks = []
    if payload.get("kind") == "topic_chapter":
        source, text_blocks = prepare_topic_source(task_id, transcript, payload, source_revision, expected_source_revision)
        if source is None:
            return
        heading = source["title"]
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
        if payload.get("kind") == "topic_chapter":
            text = chapter_provenance(source, text_blocks) + "\n\n" + text
        normalized = normalize_note_markdown(heading, text, generate_questions=task.options.generate_questions)
        if normalized.report["blocking"] or (payload.get("kind") == "topic_chapter" and not chapter_markdown_complete(normalized.markdown)):
            return
        # Apply the same conservative local claim markers as final publication.
        # Even literal quotations stay in an evidence-pending draft section.
        claims = build_claim_evidence_map(task_id, heading, normalized.markdown, transcript)
        markdown = mark_claims_for_review(normalized.markdown, claims)
    except TextDecodingError:
        return
    section = {**source, "status": "evidence_pending", "verified": False,
               "summary_generated": True, "markdown": markdown, "revision": _revision(markdown)}
    return root, source_revision, text_blocks, section

