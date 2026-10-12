"""Shared, non-rewriting Unicode corruption checks for publishable prose.

Exact multi-character artifacts are evidence; individual CJK or accented
letters are not. Explicit Markdown code is quoted data, not asserted prose.
"""
from __future__ import annotations

import re

from .markdown_structure import structural_lines


MOJIBAKE_BLOCK_THRESHOLD = 4
_CJK_ARTIFACTS = ("锟斤拷", "鏂囧", "浣犲ソ", "瀛︿", "璇轰")
_REVERSIBLE_UTF8_MARKERS = ("â€", "ðŸ", "ï»¿", "è¯", "ç¨", "æ€", "ç»", "涓\ue15f")
_UTF8_MOJIBAKE_RE = re.compile(r"(?:Ã[\u0080-\u00bf]|Â(?:[\u0080-\u00bf]|\s)|â(?:€|™|œ|“|”|…)|ðŸ)")


def corruption_prose(value: str) -> str:
    """Mask fenced/indented code and matched inline backtick spans in linear time."""
    text = "\n".join(line if prose else "" for line, prose in structural_lines(str(value or "").split("\n")))
    runs = list(re.finditer(r"`+", text))
    following: dict[int, int] = {}
    next_length: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        run = runs[index]
        length = run.end() - run.start()
        if length in next_length:
            following[index] = next_length[length]
        next_length[length] = index
    parts, offset, index = [], 0, 0
    while index < len(runs):
        before = runs[index].start() - 1
        while before >= 0 and text[before] == "\\":
            before -= 1
        if (runs[index].start() - before - 1) % 2:
            index += 1
            continue
        close = following.get(index)
        if close is None:
            index += 1
            continue
        parts.append(text[offset:runs[index].start()])
        parts.append(" ")
        offset = runs[close].end()
        index = close + 1
    parts.append(text[offset:])
    return "".join(parts)


def mojibake_score(value: str) -> int:
    text = corruption_prose(value)
    score = text.count("\ufffd") * 10
    score += sum(text.count(marker) * 4 for marker in _CJK_ARTIFACTS)
    score += sum(text.count(marker) * (4 if marker == "涓\ue15f" else 2) for marker in _REVERSIBLE_UTF8_MARKERS)
    score += len(_UTF8_MOJIBAKE_RE.findall(text)) * 2
    score += sum(4 for char in text if 0x80 <= ord(char) <= 0x9F)
    score += text.count("\x00") * 4
    return score


def has_high_confidence_corruption(value: str) -> bool:
    return mojibake_score(value) >= MOJIBAKE_BLOCK_THRESHOLD


def may_repair_utf8_mojibake(value: str) -> bool:
    # Broadening the publication gate must not introduce automatic CJK word
    # substitutions or recode a literal code example together with its prose.
    return corruption_prose(value) == value and (
        bool(_UTF8_MOJIBAKE_RE.search(value)) or any(marker in value for marker in _REVERSIBLE_UTF8_MARKERS)
    )
