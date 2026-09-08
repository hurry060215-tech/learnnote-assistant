"""Evidence-preserving, extractive review prompts; never invent an answer."""
from __future__ import annotations

import re

from .markdown_structure import prose_text


def review_points(text: str) -> list[tuple[str, str]]:
    points = []
    heading = ""
    for raw in prose_text(text).splitlines():
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            continue
        if not line or line.startswith(("![", "|", ">", "---", "http://", "https://")):
            continue
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        if re.match(r"(?:课程标题|文本来源|画面切片|使用方式|整理方式|主题线索|导出时间|帧时间|画面网格|切片范围|回看目标|复习动作|来源)\s*[:：]", line):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[`*_]", "", line)
        for sentence in re.split(r"(?<=[。！？.!?])\s*", line):
            sentence = sentence.strip()
            # Keep a complete, short quotation. Long material is not truncated
            # into an unanswerable card; users can select/edit it explicitly.
            minimum = 8 if len(re.findall(r"[\u4e00-\u9fff]", sentence)) >= 6 else 20
            if minimum <= len(sentence) <= 360:
                points.append((heading, sentence))
    return points
