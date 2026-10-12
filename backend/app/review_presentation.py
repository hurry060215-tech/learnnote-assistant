"""Move repetitive location-only notices into a portable, linked appendix.

This is a read/export projection. It never changes stored Markdown, the claim
map, stronger warnings, or the verification status of any statement.
"""
from __future__ import annotations

import re
from collections import Counter

from .export_inline import export_protected_spans
from .markdown_structure import structural_lines
from .note_document import section_anchor_id

LOCATION_MARKER = "**【待核对：仅定位到来源】**"
REVIEW_EXPLANATION = "以下表述只找到了候选来源位置，尚未验证来源是否支持结论。请打开对应出处核对；这些提示未被判定为已验证。"


def project_source_reviews(markdown: str) -> dict:
    lines = str(markdown or "").splitlines(keepends=True)
    structural = list(structural_lines(lines))
    headings = Counter(section_anchor_id(match.group(2))
                       for line, prose in structural if prose
                       if (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line)))
    frontmatter_end = -1
    if lines and lines[0].strip() == "---":
        frontmatter_end = next((i for i in range(1, min(len(lines), 80)) if lines[i].strip() == "---"), -1)
    output, entries = [], []
    for line_number, (line, prose) in enumerate(structural):
        if not prose or line_number <= frontmatter_end or line.lstrip().startswith(("#", ">")) or LOCATION_MARKER not in line:
            output.append(line)
            continue
        protected = export_protected_spans(line)
        positions = []
        start = 0
        while (start := line.find(LOCATION_MARKER, start)) >= 0:
            backslashes = len(line[:start]) - len(line[:start].rstrip("\\"))
            if not backslashes % 2 and not any(a <= start < b for a, b in protected):
                positions.append(start)
            start += len(LOCATION_MARKER)
        cursor = 0
        for index, position in enumerate(positions):
            number = len(entries) + 1
            heading = f"来源核对 {number}"
            base = section_anchor_id(heading)
            headings[base] += 1
            anchor = section_anchor_id(heading, headings[base])
            end = positions[index + 1] if index + 1 < len(positions) else len(line)
            text = line[position + len(LOCATION_MARKER):end].strip()
            entries.append({"number": number, "heading": heading, "anchor": anchor, "text": text})
            output.extend((line[cursor:position], f"[来源 {number}](#{anchor})"))
            cursor = position + len(LOCATION_MARKER)
        output.append(line[cursor:])
    body = "".join(output)
    if not entries:
        return {"markdown": body, "body": body, "entries": [], "heading": "", "anchor": ""}
    heading = f"来源核对 · {len(entries)} 条定位提示"
    base = section_anchor_id(heading)
    anchor = section_anchor_id(heading, headings[base] + 1)
    appendix = [f"## {heading}", "", REVIEW_EXPLANATION, ""]
    for entry in entries:
        appendix.extend([f"### {entry['heading']}", "", "仅定位到来源，尚未验证支持。", "",
                         entry["text"] or "该提示后没有正文，请回到原笔记核对。", ""])
    return {"markdown": body.rstrip("\n") + "\n\n" + "\n".join(appendix), "body": body,
            "entries": entries, "heading": heading, "anchor": anchor}
