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
    for line in lines:
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
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
            yield line, not (line.startswith("    ") or line.startswith("\t"))


def prose_text(markdown: str) -> str:
    return "\n".join(line for line, prose in structural_lines(markdown.splitlines()) if prose)
