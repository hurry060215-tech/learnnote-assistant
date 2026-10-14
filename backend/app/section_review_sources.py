"""Current, bounded chapter inputs for an explicitly requested model opinion."""
from __future__ import annotations

import hashlib
import re

from .claims import build_claim_evidence_map, _claim_spans
from .graph_snapshot import digest
from .models import TranscriptResult
from .note_document import build_note_document
from .partial_note_projection import read_partial_note
from .personal_anchors import read_anchor_artifact
from .reading_notes import source_block_entries
from .section_evidence_status import section_claim_map
from .storage import get_task
from .task_artifacts import decode_task_note

MAX_CLAIMS = 12
MAX_SOURCE_CHARACTERS = 12000
MAX_SOURCE_ITEMS = 24
MAX_CLAIM_CHARACTERS = 6000


def capture(task_id, revision):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise ValueError("review_source_unavailable")
    task = get_task(task_id)
    if task.id != task_id:
        raise ValueError("review_source_unavailable")
    note = read_anchor_artifact(task_id, task.note_path)
    if not note:
        raise ValueError("review_source_unavailable")
    note = decode_task_note(task, note.encode("utf-8"))
    current_revision = hashlib.sha256(note.encode()).hexdigest()
    if revision != current_revision:
        raise ValueError("review_source_changed")
    transcript = TranscriptResult.model_validate_json(read_anchor_artifact(task_id, task.transcript_path))
    if transcript.source == "screen-ocr":
        raise ValueError("review_ocr_unreviewed")
    partial = read_partial_note(task_id)
    if task.status == "success":
        sections = [{"id": item["section_id"], "title": item["heading"], "markdown": item["markdown"]}
                    for item in build_note_document(task.title, note)["sections"]]
    elif partial["status"] == "draft" and partial["reason"] == "ready":
        sections = [item for item in partial["sections"] if item["kind"] != "temporal_outline"]
    else:
        raise ValueError("review_source_unavailable")
    fingerprint = digest([task.id, task.created_at, task.control_generation, task.retry_count, task.status,
                          task.source_identity.model_dump(mode="json"), task.note_path, task.transcript_path,
                          task.summary_source, current_revision,
                          transcript.model_dump(mode="json"), partial.get("attempt_id", ""),
                          partial.get("source_revision", ""), partial.get("generation_revision", ""), partial.get("revision", "")])
    return {"task": task, "transcript": transcript, "sections": sections,
            "revision": current_revision, "fingerprint": fingerprint}


def mapped_section(snapshot, section, markdown):
    task, transcript = snapshot["task"], snapshot["transcript"]
    if "kind" in section:
        return section_claim_map(task.id, section, markdown, transcript, source_block_entries(transcript))
    documents = [] if transcript.segments else [{"evidence_id": f"task-{task.id}-source-block-{index:05d}",
        "text": block["text"], "locator": f"source block {index + 1}", "source_type": "text"}
        for index, block in enumerate(source_block_entries(transcript))]
    return build_claim_evidence_map(task.id, "", markdown, transcript, document_evidence=documents)


def chapter_list(task_id, revision):
    snapshot = capture(task_id, revision)
    return {"task_id": task_id, "revision": revision, "scope": "generated_note_text_only",
            "sections": [{"id": item["id"], "title": item.get("title") or item["markdown"].splitlines()[0].lstrip("# ")}
                         for item in snapshot["sections"] if item["markdown"].strip()]}


def select_inputs(snapshot, section_id, offset, redact):
    section = next((item for item in snapshot["sections"] if item["id"] == section_id), None)
    if section is None:
        raise ValueError("review_source_changed")
    if len(section["markdown"]) > 100000:
        raise ValueError("review_claims_oversized")
    spans = _claim_spans(section["markdown"])
    claims = [{"text": text} for text, _, _ in spans]
    if type(offset) is not int or offset < 0 or offset % MAX_CLAIMS or offset >= len(claims):
        raise ValueError("review_claims_unavailable")
    chosen = claims[offset:offset + MAX_CLAIMS]
    mapped = mapped_section(snapshot, section, "\n\n".join(item["text"] for item in chosen))
    if [item["text"] for item in mapped["claims"]] != [item["text"] for item in chosen]:
        raise ValueError("review_claims_unavailable")
    chosen = mapped["claims"]
    # Candidate retrieval is location only. Include adjacent original cues to
    # avoid dropping a nearby negation/qualification from the model's view.
    evidence = mapped["evidence"]
    wanted = {key for claim in chosen for key in claim["evidence_ids"] + claim["candidate_evidence_ids"]}
    positions = {i for i, item in enumerate(evidence) if item["evidence_id"] in wanted}
    positions |= {near for i in positions for near in (i - 1, i + 1) if 0 <= near < len(evidence)}
    if not positions:
        positions = set(range(len(evidence)))  # Explicitly disclosed bounded fallback.
    selected, characters = [], 0
    for index in sorted(positions):
        item = evidence[index]
        text = redact(item["text"])
        if len(selected) >= MAX_SOURCE_ITEMS or characters + len(text) > MAX_SOURCE_CHARACTERS:
            continue  # Never cut an original cue or hide that the view is partial.
        characters += len(text)
        selected.append({"source_alias": f"E{len(selected) + 1}", "text": text,
                         "locator": item["locator"], "evidence_id": item["evidence_id"]})
    projected_claims = [{"claim_alias": f"C{index + 1}", "text": redact(claim["text"])} for index, claim in enumerate(chosen)]
    blocked = "review_source_insufficient" if not selected else (
        "review_claims_oversized" if sum(len(item["text"]) for item in projected_claims) > MAX_CLAIM_CHARACTERS else None)
    return {"section_id": section_id, "offset": offset, "claims": projected_claims, "evidence": selected,
            "coverage": {"claim_count": len(claims), "selected_claims": len(chosen),
                         "literal_matches": sum(claim["verification"] == "direct" for claim in chosen),
                         "next_offset": offset + MAX_CLAIMS if offset + MAX_CLAIMS < len(claims) else None,
                         "candidate_sources": len(positions), "selected_sources": len(selected),
                         "source_characters": characters, "source_truncated": len(selected) < len(positions),
                         "source_scope": "selected_text_candidates_not_full_course"}, "blocking_reason": blocked}
