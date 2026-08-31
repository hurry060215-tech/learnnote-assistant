"""Canonical note normalization and evidence-first document projection.

The persisted Markdown remains the portable source of truth.  This module adds
two deterministic, rebuildable projections next to it:

* a quality report that catches structural and encoding regressions; and
* a section document that lets the client render citations without scraping
  arbitrary HTML.

No remote model call or user data leaves the local process here.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable


DOCUMENT_SCHEMA_VERSION = 1

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"\A\s*```(?:markdown|md)?\s*\n(?P<body>.*)\n```\s*\Z", re.IGNORECASE | re.DOTALL)
_TIMESTAMP_RE = re.compile(
    r"(?<!\d)(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2})"
    r"(?:\s*(?:-|–|—|~|至)\s*(?P<end>(?:\d{1,2}:)?\d{1,2}:\d{2}))?(?!\d)"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MOJIBAKE_MARKERS = (
    "�",
    "锟斤拷",
    "浣犲ソ",
    "瀛︿",
    "閫",
    "â€™",
    "ï»¿",
)
_UTF8_MOJIBAKE_RE = re.compile(r"(?:Ã[\u0080-\u00bf]|Â(?:[\u0080-\u00bf]|\s)|â(?:€|™|œ|“|”|…)|ðŸ)")


@dataclass(frozen=True)
class NoteNormalizationResult:
    markdown: str
    report: dict[str, Any]


def _plain_heading(value: str) -> str:
    text = re.sub(r"[`*_~\[\]()]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strip_wrapping_fence(value: str) -> tuple[str, bool]:
    match = _FENCE_RE.match(value)
    if not match:
        return value, False
    return match.group("body"), True


def _split_frontmatter(lines: list[str]) -> tuple[list[str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return [], lines
    for index in range(1, min(len(lines), 80)):
        if lines[index].strip() == "---":
            return lines[: index + 1], lines[index + 1 :]
    return [], lines


def normalize_note_markdown(title: str, markdown: str) -> NoteNormalizationResult:
    """Return stable UTF-8-friendly Markdown and a non-destructive lint report."""

    raw = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = unicodedata.normalize("NFC", raw.lstrip("\ufeff"))
    raw = _CONTROL_RE.sub("", raw)
    raw, removed_wrapper = _strip_wrapping_fence(raw)
    lines = [line.rstrip() for line in raw.split("\n")]
    frontmatter, body = _split_frontmatter(lines)

    clean_title = re.sub(r"\s+", " ", str(title or "学习笔记")).strip() or "学习笔记"
    title_key = _plain_heading(clean_title)
    duplicate_h1 = 0
    body_without_duplicate_title: list[str] = []
    seen_content = False
    for line in body:
        heading = _HEADING_RE.match(line)
        is_matching_h1 = bool(
            heading
            and len(heading.group(1)) == 1
            and _plain_heading(heading.group(2)) == title_key
        )
        if is_matching_h1:
            duplicate_h1 += 1
            if not seen_content:
                continue
        if line.strip():
            seen_content = True
        body_without_duplicate_title.append(line)

    while body_without_duplicate_title and not body_without_duplicate_title[0].strip():
        body_without_duplicate_title.pop(0)
    while body_without_duplicate_title and not body_without_duplicate_title[-1].strip():
        body_without_duplicate_title.pop()

    # Consecutive rules are usually raw model scaffolding, not meaningful
    # document structure.  Keep one rule so author intent is preserved.
    compact: list[str] = []
    previous_rule = False
    collapsed_rules = 0
    for line in body_without_duplicate_title:
        is_rule = line.strip() in {"---", "***", "___"}
        if is_rule and previous_rule:
            collapsed_rules += 1
            continue
        compact.append(line)
        previous_rule = is_rule

    output = [*frontmatter]
    if output:
        output.append("")
    output.extend([f"# {clean_title}", ""])
    output.extend(compact)
    normalized = "\n".join(output).strip() + "\n"

    issues = lint_note_markdown(normalized)
    report = {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "changed": normalized != str(markdown or ""),
        "removed_markdown_wrapper": removed_wrapper,
        "duplicate_title_count": duplicate_h1,
        "collapsed_rule_count": collapsed_rules,
        "issues": issues,
        "blocking": any(item["severity"] == "error" for item in issues),
    }
    return NoteNormalizationResult(markdown=normalized, report=report)


def lint_note_markdown(markdown: str) -> list[dict[str, str]]:
    """Report structural risks without inventing or rewriting note content."""

    text = str(markdown or "")
    issues: list[dict[str, str]] = []
    mojibake_score = sum(
        text.count(marker) * (10 if marker == "�" else 4)
        for marker in _MOJIBAKE_MARKERS
    )
    mojibake_score += len(_UTF8_MOJIBAKE_RE.findall(text)) * 2
    if mojibake_score >= 4:
        issues.append({
            "code": "mojibake_detected",
            "severity": "error",
            "message": "检测到高置信度乱码模式，已阻止笔记发布。",
        })

    headings: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            headings.append((len(match.group(1)), match.group(2).strip()))
    h1_count = sum(1 for level, _ in headings if level == 1)
    if h1_count != 1:
        issues.append({
            "code": "invalid_title_count",
            "severity": "error",
            "message": f"笔记必须且只能包含一个一级标题，当前为 {h1_count} 个。",
        })
    for previous, current in zip(headings, headings[1:]):
        if current[0] > previous[0] + 1:
            issues.append({
                "code": "heading_level_jump",
                "severity": "warning",
                "message": f"标题层级从 H{previous[0]} 跳到 H{current[0]}：{current[1]}",
            })

    if len(text.strip()) < 80:
        issues.append({
            "code": "note_too_short",
            "severity": "warning",
            "message": "笔记内容过短，请检查字幕覆盖或总结阶段是否完整。",
        })
    if not _TIMESTAMP_RE.search(text) and "依据与覆盖" not in text and "证据来源" not in text:
        issues.append({
            "code": "missing_visible_evidence",
            "severity": "warning",
            "message": "笔记没有可见时间戳或证据说明。",
        })
    return issues


def _timestamp_seconds(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return 0.0


def _slug(value: str, index: int) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value).strip("-").lower()
    return f"section-{index:02d}-{slug[:48] or 'note'}"


def _citations(markdown: str) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    for match in _TIMESTAMP_RE.finditer(markdown):
        start = _timestamp_seconds(match.group("start"))
        end = _timestamp_seconds(match.group("end")) if match.group("end") else start
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        citations.append({
            "kind": "video",
            "label": match.group(0),
            "start": start,
            "end": max(start, end),
        })
    return citations


def build_note_document(
    title: str,
    markdown: str,
    evidence: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project canonical Markdown into stable sections and citation metadata."""

    evidence_items = [dict(item) for item in (evidence or []) if isinstance(item, dict)]
    sections: list[dict[str, Any]] = []
    current_heading = str(title or "学习笔记")
    current_level = 1
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        body = "\n".join(current_lines).strip()
        if not body:
            current_lines = []
            return
        citations = _citations(body)
        matched_ids: list[str] = []
        for item in evidence_items:
            locator = str(item.get("locator") or "")
            evidence_id = str(item.get("evidence_id") or "")
            if not evidence_id:
                continue
            if any(citation["label"] in locator or locator in citation["label"] for citation in citations if locator):
                matched_ids.append(evidence_id)
        sections.append({
            "section_id": _slug(current_heading, len(sections) + 1),
            "heading": current_heading,
            "level": current_level,
            "markdown": body,
            "citations": citations,
            "source_evidence_ids": matched_ids[:16],
            "verification": "verified" if citations or matched_ids else "unverified",
        })
        current_lines = []

    _, document_lines = _split_frontmatter(str(markdown or "").splitlines())
    for line in document_lines:
        match = _HEADING_RE.match(line)
        if match:
            if current_lines or sections:
                flush()
            current_level = len(match.group(1))
            current_heading = match.group(2).strip()
        else:
            current_lines.append(line)
    if current_lines:
        flush()

    if not sections:
        sections.append({
            "section_id": _slug(current_heading, 1),
            "heading": current_heading,
            "level": current_level,
            "markdown": "",
            "citations": [],
            "source_evidence_ids": [],
            "verification": "unverified",
        })

    citation_count = sum(len(section["citations"]) for section in sections)
    verified_count = sum(section["verification"] == "verified" for section in sections)
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "title": str(title or "学习笔记"),
        "sections": sections,
        "evidence": evidence_items,
        "quality": {
            "section_count": len(sections),
            "verified_section_count": verified_count,
            "citation_count": citation_count,
            "coverage_ratio": verified_count / len(sections) if sections else 0.0,
            "issues": lint_note_markdown(markdown),
        },
    }


__all__ = [
    "DOCUMENT_SCHEMA_VERSION",
    "NoteNormalizationResult",
    "build_note_document",
    "lint_note_markdown",
    "normalize_note_markdown",
]
