"""Source-backed temporal reading outline, never a generated/verified summary."""
import hashlib
import math
import re

from .text_cleanup import canonicalize_unicode_text, redact_sensitive_url_values


def clean_excerpt(value: str, limit: int = 280) -> str:
    return redact_sensitive_url_values(re.sub(r"\s+", " ", canonicalize_unicode_text(value))).strip()[:limit]


def temporal_sections(transcript, seconds: int = 300) -> list[dict]:
    """Stable five-minute source buckets; appending cues preserves prior IDs."""
    groups = {}
    for index, cue in enumerate(transcript.segments):
        start, end = float(cue.start), float(cue.end)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start or not cue.text.strip():
            continue
        bucket = int(start // seconds)
        groups.setdefault(bucket, []).append((index, cue))
    result = []
    for bucket, entries in sorted(groups.items()):
        picks = sorted({0, len(entries) // 2, len(entries) - 1})
        excerpts = [{"start": entries[pick][1].start, "end": entries[pick][1].end,
                     "text": clean_excerpt(entries[pick][1].text), "source_cue_index": entries[pick][0]} for pick in picks]
        result.append({"id": f"draft-time-{bucket * seconds}", "kind": "temporal_outline",
            "status": "draft", "verified": False, "summary_generated": False,
            "start": min(cue.start for _, cue in entries), "end": max(cue.end for _, cue in entries),
            "source_cue_count": len(entries), "heading_excerpt": clean_excerpt(entries[0][1].text, 80),
            "excerpts": excerpts})
    return result


def draft_sections_document(transcript) -> dict:
    sections = temporal_sections(transcript)
    return {"schema_version": 1, "status": "draft", "summary_generated": False,
            "basis": "time-bucketed source excerpts, not AI topic inference",
            "source": transcript.source, "sections": sections,
            "revision": hashlib.sha256(repr(sections).encode("utf-8")).hexdigest()}


def temporal_outline_markdown(document: dict, stamp) -> list[str]:
    if not document["sections"]:
        return []
    lines = ["## 按时间段的阅读提纲（字幕摘录草稿）", "",
             "> 以下按原始时间分段，标题摘自原句；不是 AI 主题总结，也未完成事实校验。", ""]
    for section in document["sections"]:
        # Heading is only a time range: source text cannot inject headings/HTML.
        lines.extend([f"### {stamp(section['start'])}–{stamp(section['end'])}", ""])
        for excerpt in section["excerpts"]:
            lines.append(f"- `{stamp(excerpt['start'])}` {excerpt['text']}")
        lines.append("")
    return lines
