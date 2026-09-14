"""Conservative claim-to-evidence projection for generated notes."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .models import TranscriptResult, VisualWindow
from .text_cleanup import canonicalize_unicode_text


CLAIM_SCHEMA_VERSION = 2
_TIMESTAMP = r"\d{1,3}:\d{2}(?::\d{2})?"
_RANGE_RE = re.compile(rf"(?P<start>{_TIMESTAMP})\s*(?:-|–|—|~|～)\s*(?P<end>{_TIMESTAMP})")
_POINT_RE = re.compile(rf"(?<![\d:])(?P<point>{_TIMESTAMP})(?![\d:])")
_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+(?:[。！？.!?]|$)")
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
    return {value.casefold() for value in _TOKEN_RE.findall(text) if value not in {"本节", "内容", "视频", "课程"}}


def _overlap(left_start: float, left_end: float, right_start: float, right_end: float) -> bool:
    return max(left_start, right_start) <= min(left_end, right_end)


def _quotation_text(text: str) -> str:
    text = _RANGE_RE.sub("", text)
    text = _POINT_RE.sub("", text)
    return re.sub(r"[\s\[\]*_`\"“”]+", "", text).strip("。.!！?？").casefold()


def _supports_quotation(claim: str, evidence: str) -> bool:
    """Only literal source quotations can skip review. Timestamps just locate."""
    value, source = _quotation_text(claim), _quotation_text(evidence)
    return len(value) >= 8 and value in source


def _claim_id(task_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{index}|{text}".encode("utf-8")).hexdigest()[:20]
    return f"claim-{digest}"


def _claim_texts(markdown: str) -> list[str]:
    text = canonicalize_unicode_text(markdown, reject_mojibake=True)
    result = []
    for match in _SENTENCE_RE.finditer(text):
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
    evidence = transcript_items + visual_items
    claims = []
    for index, text in enumerate(_claim_texts(markdown)):
        ranges = _ranges(text)
        words = _tokens(text)
        matched = []
        candidates = []
        for item in evidence:
            range_match = any(_overlap(start, end, item["start"], item["end"]) for start, end in ranges)
            lexical_match = len(words & _tokens(item["text"])) >= (2 if len(words) >= 4 else 1)
            if range_match or lexical_match and len(item["text"]) >= 8:
                candidates.append(item)
            if _supports_quotation(text, item["text"]):
                matched.append(item)
        inference = bool(_INFERENCE_RE.search(text))
        visual_intent = bool(_VISUAL_RE.search(text))
        if inference:
            claim_type = "inference"
        elif visual_intent and any(item["kind"] == "visual" for item in matched):
            claim_type = "visual"
        elif any(item["kind"] == "transcript" for item in matched):
            claim_type = "transcript"
        else:
            claim_type = "unsupported"
        claims.append({
            "claim_id": _claim_id(task_id, index, text),
            "index": index,
            "text": text,
            "claim_type": claim_type,
            "evidence_ids": [item["evidence_id"] for item in matched[:8]],
            "candidate_evidence_ids": [item["evidence_id"] for item in candidates[:8]],
            "source_ranges": ranges,
            "review_required": claim_type in {"inference", "unsupported"},
        })
    counts = {kind: sum(claim["claim_type"] == kind for claim in claims) for kind in ("transcript", "visual", "inference", "unsupported")}
    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "task_id": str(task_id),
        "title": str(title or "学习笔记"),
        "source_revision": hashlib.sha256(canonicalize_unicode_text(markdown).encode("utf-8")).hexdigest(),
        "claims": claims,
        "evidence": evidence,
        "counts": counts,
        "quality": {
            "claim_count": len(claims),
            "supported_count": counts["transcript"] + counts["visual"],
            "unsupported_count": counts["unsupported"],
            "inference_count": counts["inference"],
            "coverage_ratio": (counts["transcript"] + counts["visual"]) / len(claims) if claims else 0.0,
            "contract": "links are navigable evidence, not factual truth verification",
        },
    }


def safe_claim_projection(value: dict) -> dict:
    """Old time-only matches remain navigable, but are never treated as verified."""
    if not isinstance(value, dict) or not value or value.get("schema_version", 1) >= CLAIM_SCHEMA_VERSION:
        return value
    claims = [{**c, "candidate_evidence_ids": c.get("evidence_ids", []), "evidence_ids": [],
               "claim_type": "inference" if c.get("claim_type") == "inference" else "unsupported", "review_required": True} for c in value.get("claims", [])]
    return {**value, "claims": claims, "requires_rebuild": True,
            "quality": {**value.get("quality", {}), "supported_count": 0, "unsupported_count": len(claims), "coverage_ratio": 0.0}}


__all__ = ["CLAIM_SCHEMA_VERSION", "build_claim_evidence_map", "safe_claim_projection"]
