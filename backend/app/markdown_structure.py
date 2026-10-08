"""Small, lossless Markdown structural scanner shared by local projections.

Only prose participates in heading/citation checks. Fenced and indented code
remains byte-for-byte content rather than being interpreted as note metadata.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator


def structural_lines(lines: Iterable[str]) -> Iterator[tuple[str, bool]]:
    fence_character = ""
    fence_length = 0
    in_list = False
    for line in lines:
        stripped = line.lstrip(" \t")
        indent = len(line) - len(stripped)
        list_item = bool(re.match(r"(?:[-*+]|\d+[.)])\s+",stripped))
        if list_item and (indent < 4 or in_list): in_list = True
        elif stripped.strip() and indent == 0 and not fence_character: in_list = False
        fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$",line) if (indent <= 3 or in_list or fence_character) else None
        if fence_character:
            yield line, False
            if (fence and fence.group(1)[0] == fence_character
                    and len(fence.group(1)) >= fence_length and not fence.group(2).strip()):
                fence_character = ""
            continue
        if fence:
            fence_character, fence_length = fence.group(1)[0], len(fence.group(1))
            yield line, False
        else:
            yield line, bool(list_item and in_list) or not (line.startswith("    ") or line.startswith("\t"))


def prose_text(markdown: str) -> str:
    return "\n".join(line for line, prose in structural_lines(markdown.splitlines()) if prose)
