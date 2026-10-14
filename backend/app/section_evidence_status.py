"""Compact chapter progress using the existing claim map, never semantic proof."""
from __future__ import annotations

from .claims import build_claim_evidence_map


def section_claim_map(task_id, section, markdown, transcript, blocks):
    """Limit matching to the chapter's original request inputs, retaining IDs."""
    windows = section.get("source_windows", [])
    included = {window["index"] for window in windows
                if type(window.get("index")) is int and 0 <= window["index"] < len(transcript.segments)
                and window.get("start") == transcript.segments[window["index"]].start
                and window.get("end") == transcript.segments[window["index"]].end}
    scoped = transcript.model_copy(update={"segments": [segment if index in included else
        segment.model_copy(update={"text": ""}) for index, segment in enumerate(transcript.segments)]})
    documents = []
    if not transcript.segments:
        indexes = section.get("source_blocks", [section.get("block_index")])
        documents = [{"evidence_id": f"task-{task_id}-source-block-{index:05d}", "text": blocks[index]["text"],
                      "locator": f"source block {index + 1}", "source_type": "text"}
                     for index in indexes if type(index) is int and 0 <= index < len(blocks)]
    return build_claim_evidence_map(task_id, "", markdown, scoped, document_evidence=documents)


def evidence_status(claims, transcript):
    values = claims["claims"]
    # OCR text remains unreviewed, even when copied exactly.
    direct = sum(claim["verification"] == "direct" for claim in values) if transcript.source != "screen-ocr" else 0
    return {"schema_version": 1, "method": "literal_prose", "claim_count": len(values), "matching_count": direct,
            "review_count": len(values) - direct}


def project_evidence_status(section, task_id, transcript, blocks):
    if "evidence_status" not in section:
        return {}  # Older drafts retain their existing, unverified rendering.
    result = evidence_status(section_claim_map(task_id, section, section["markdown"], transcript, blocks), transcript)
    if section["evidence_status"] != result:
        raise ValueError("Partial evidence progress changed")
    return {"evidence_status": result}


def evidence_status_label(section):
    value = section.get("evidence_status", {})
    total, matched = value.get("claim_count", 0), value.get("matching_count", 0)
    if total and matched:
        return f"草稿 · {matched}/{total} 条正文结论与原文字面匹配 · 未完成最终校验"
    return "草稿 · 证据补充中 · 未完成最终校验 · 待最终来源检查"
