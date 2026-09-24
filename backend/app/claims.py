"""Conservative claim-to-evidence projection for generated notes."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .models import TranscriptResult, VisualWindow
from .text_cleanup import canonicalize_unicode_text, redact_sensitive_url_values
from .markdown_structure import structural_lines


CLAIM_SCHEMA_VERSION = 5
_TIMESTAMP = r"\d{1,3}:\d{2}(?::\d{2})?"
_RANGE_RE = re.compile(rf"(?P<start>{_TIMESTAMP})\s*(?:-|–|—|~|～)\s*(?P<end>{_TIMESTAMP})")
_POINT_RE = re.compile(rf"(?<![\d:])(?P<point>{_TIMESTAMP})(?![\d:])")
_SENTENCE_RE = re.compile(r"(?:[^。！？.!?\n]|(?<=\w)\.(?=\w))+(?:[。！？.!?]|$)")
_INFERENCE_RE = re.compile(r"可能|推测|推断|意味着|提示|似乎|倾向于|may\b|might\b|suggest(?:s|ed)?\b|likely\b|inference\b", re.I)
_VISUAL_RE = re.compile(r"画面|截图|图表|表格|代码|公式|演示|界面|板书|frame|visual|screen|chart|table|code|formula", re.I)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")


def _seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    return float(parts[0] * 3600 + parts[1] * 60 + parts[2])


def _ranges(text: str) -> list[tuple[float, float]]:
    found = [(_seconds(match.group("start")), _seconds(match.group("end"))) for match in _RANGE_RE.finditer(text)]
    for match in _POINT_RE.finditer(text):
        point = _seconds(match.group("point"))
        if not any(start <= point <= end for start, end in found):
            found.append((point, point))
    return found


def _tokens(text: str) -> set[str]:
    words = {value.casefold() for value in re.findall(r'[A-Za-z0-9_]{2,}', text)}
    for span in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(span[index:index + 2] for index in range(len(span) - 1))
    return words - {"本节", "内容", "视频", "课程", "这个", "我们", "他们", "一个", "可以", "然后", "the", "and", "that", "this", "with"}


def _overlap(left_start: float, left_end: float, right_start: float, right_end: float) -> bool:
    return max(left_start, right_start) <= min(left_end, right_end)


def _quotation_text(text: str) -> str:
    # Only bracketed citation syntax is removable. A ratio such as 1:20 or
    # a time in the actual sentence is evidence content, not a free citation.
    text = re.sub(rf"\[{_TIMESTAMP}(?:\s*[-–—~～]\s*{_TIMESTAMP})?\]", "", text)
    return re.sub(r"[\s\[\]*_`\"“”]+", "", text).strip("。.!！?？").casefold()


def _supports_quotation(claim: str, evidence: str) -> bool:
    """Only literal source quotations can skip review. Timestamps just locate."""
    value, source = _quotation_text(claim), _quotation_text(evidence)
    clauses = {_quotation_text(part) for part in re.split(r"[。！？!?；;，,]|\.(?!\d)", evidence)}
    # A substring of a negated statement ("not ...") is not a quotation that
    # supports its positive form. Only whole sentences/clauses skip review.
    return len(value) >= 8 and (value == source or value in clauses)


def _claim_id(task_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{index}|{text}".encode("utf-8")).hexdigest()[:20]
    return f"claim-{digest}"


def _claim_texts(markdown: str) -> list[str]:
    text = canonicalize_unicode_text(markdown, reject_mojibake=True)
    result = []
    prose = "\n".join(line for line, is_prose in structural_lines(text.splitlines()) if is_prose)
    for match in _SENTENCE_RE.finditer(prose):
        value = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", match.group(0)).strip()
        if len(value) >= 8 and not value.startswith(("#", ">", "|", "\x60\x60\x60", "http://", "https://")):
            result.append(value)
    return result


def build_claim_evidence_map(
    task_id: str,
    title: str,
    markdown: str,
    transcript: TranscriptResult,
    visual_windows: list[VisualWindow] | list[dict[str, Any]] | None = None,
    document_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    transcript_items = [
        {
            "evidence_id": f"task-{task_id}-transcript-{index:05d}",
            "kind": "transcript",
            "source_type": "video",
            "locator": f"{float(segment.start):.1f}-{float(segment.end):.1f}s",
            "start": float(segment.start),
            "end": float(segment.end),
            "text": str(segment.text or "").strip(),
        }
        for index, segment in enumerate(transcript.segments)
        if str(segment.text or "").strip()
    ]
    visual_items = []
    for index, item in enumerate(visual_windows or []):
        value = item.model_dump(mode="json") if isinstance(item, VisualWindow) else dict(item)
        start, end = float(value.get("start") or 0), float(value.get("end") or value.get("start") or 0)
        visual_items.append({
            "evidence_id": f"task-{task_id}-visual-{str(value.get('id') or index)[:40]}",
            "kind": "visual",
            "source_type": "video",
            "locator": f"{start:.1f}-{end:.1f}s",
            "start": start,
            "end": end,
            "text": str(value.get("summary") or value.get("visual_summary") or value.get("transcript_excerpt") or "").strip(),
            "window_id": str(value.get("id") or ""),
            "grid_url": str(value.get("grid_url") or ""),
        })
    document_items = []
    seen_document_ids: set[str] = set()
    for index, item in enumerate(document_evidence or []):
        value = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        evidence_id = str(value.get("evidence_id") or f"task-{task_id}-document-{index:05d}")[:128]
        text_value = canonicalize_unicode_text(str(value.get("text") or ""), reject_mojibake=True).strip()
        if not text_value or evidence_id in seen_document_ids:
            continue
        seen_document_ids.add(evidence_id)
        metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
        document_items.append({
            "evidence_id": evidence_id,
            "kind": "document",
            "source_type": str(value.get("source_type") or "document")[:40],
            "locator": str(value.get("locator") or value.get("label") or f"document section {index + 1}")[:300],
            "start": -1.0,
            "end": -1.0,
            "text": text_value,
            "source_uri": redact_sensitive_url_values(str(value.get("source_uri") or ""))[:1000],
            "material_id": str(value.get("material_id") or metadata.get("material_id") or "")[:128],
        })
    evidence = transcript_items + visual_items + document_items
    claims = []
    for index, text in enumerate(_claim_texts(markdown)):
        ranges = _ranges(text)
        words = _tokens(text)
        matched = []
        candidates = []
        for item in evidence:
            range_match = item["kind"] != "document" and any(
                _overlap(start, end, item["start"], item["end"]) for start, end in ranges
            )
            shared = len(words & _tokens(item["text"]))
            overlap = shared / max(1, len(words))
            lexical_match = shared >= 2 and overlap >= .18
            if range_match or lexical_match and len(item["text"]) >= 8:
                candidates.append((2 * int(range_match) + overlap, item))
            if _supports_quotation(text, item["text"]):
                matched.append(item)
        inference = bool(_INFERENCE_RE.search(text))
        visual_intent = bool(_VISUAL_RE.search(text))
        if inference and not matched:
            claim_type = "inference"
        elif visual_intent and any(item["kind"] == "visual" for item in matched):
            claim_type = "visual"
        elif any(item["kind"] == "transcript" for item in matched):
            claim_type = "transcript"
        elif any(item["kind"] == "document" for item in matched):
            claim_type = "document"
        else:
            claim_type = "unsupported"
        if inference and not matched:
            verification = "inference"
        elif matched:
            verification = "direct"
        elif candidates:
            verification = "located_only"
        else:
            verification = "pending_review"
        claims.append({
            "claim_id": _claim_id(task_id, index, text),
            "index": index,
            "text": text,
            "claim_type": claim_type,
            "evidence_ids": [item["evidence_id"] for item in matched[:8]],
            "candidate_evidence_ids": [item["evidence_id"] for _, item in sorted(candidates, key=lambda pair: pair[0], reverse=True)[:8]],
            "source_ranges": ranges,
            "verification": verification,
            "review_required": claim_type in {"inference", "unsupported"},
        })
    counts = {
        kind: sum(claim["claim_type"] == kind for claim in claims)
        for kind in ("transcript", "visual", "document", "inference", "unsupported")
    }
    evidence_revision = hashlib.sha256("\n".join(
        f"{item['evidence_id']}|{item['kind']}|{item['source_type']}|{item['locator']}|{item.get('source_uri', '')}|{item['text']}"
        for item in evidence
    ).encode("utf-8")).hexdigest()
    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "task_id": str(task_id),
        "title": str(title or "学习笔记"),
        "source_revision": hashlib.sha256(canonicalize_unicode_text(markdown).encode("utf-8")).hexdigest(),
        "source_revision_kind": "normalized_note_utf8_sha256",
        "evidence_revision": evidence_revision,
        "claims": claims,
        "evidence": evidence,
        "counts": counts,
        "quality": {
            "claim_count": len(claims),
            "supported_count": counts["transcript"] + counts["visual"] + counts["document"],
            "unsupported_count": counts["unsupported"],
            "inference_count": counts["inference"],
            "coverage_ratio": (counts["transcript"] + counts["visual"] + counts["document"]) / len(claims) if claims else 0.0,
            "direct_count": sum(item.get("verification") == "direct" for item in claims),
            "located_only_count": sum(item.get("verification") == "located_only" for item in claims),
            "pending_review_count": sum(item.get("verification") == "pending_review" for item in claims),
            "contract": "links are navigable evidence, not factual truth verification",
        },
    }


def safe_claim_projection(value: dict) -> dict:
    """Old time-only/substring matches stay navigable and require revalidation."""
    if not isinstance(value, dict) or not value:
        return value
    try:
        schema_version = int(value.get("schema_version", 1) or 1)
    except (TypeError, ValueError):
        schema_version = 1
    if schema_version >= CLAIM_SCHEMA_VERSION:
        return value
    if schema_version == 4:
        # Version 5 only adds document-source mappings; older video mappings
        # already used exact-clause verification and remain safe to project.
        return {**value, "schema_version": CLAIM_SCHEMA_VERSION}
    claims = [{**c, "candidate_evidence_ids": c.get("evidence_ids", []), "evidence_ids": [],
               "claim_type": "inference" if c.get("claim_type") == "inference" else "unsupported",
               "verification": "pending_review", "review_required": True} for c in value.get("claims", [])]
    return {**value, "claims": claims, "requires_rebuild": True,
            "quality": {**value.get("quality", {}), "supported_count": 0, "unsupported_count": len(claims), "coverage_ratio": 0.0}}


__all__ = ["CLAIM_SCHEMA_VERSION", "build_claim_evidence_map", "safe_claim_projection"]
