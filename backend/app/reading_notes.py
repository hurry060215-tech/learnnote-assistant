"""Readable source-first fallback; never turn transcript snippets into invented teaching."""
from __future__ import annotations
import re
from .models import TranscriptResult

def stamp(value):
    seconds = max(0, int(value or 0))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}" if seconds >= 3600 else f"{seconds // 60:02}:{seconds % 60:02}"

def source_blocks(transcript: TranscriptResult, budget: int = 16000):
    """Keep every source character; segment timestamps travel with their text."""
    parts = [f"[{stamp(s.start)} – {stamp(s.end)}] {s.text}" for s in transcript.segments if s.text.strip()]
    if not parts:
        parts = [transcript.full_text]
    blocks, current = [], ""
    for part in parts:
        for offset in range(0, len(part), budget):
            piece = part[offset:offset + budget]
            if current and len(current) + len(piece) + 2 > budget:
                blocks.append(current)
                current = ""
            current += ("\n\n" if current else "") + piece
    if current.strip():
        blocks.append(current)
    return blocks

def readable_extract(title, transcript, grids, page_url=""):
    lines = [f"# {title or '学习笔记'}", "", "> 字幕摘录：尚未使用文字模型整理。以下保留原话和定位，不代表提炼后的知识点。", ""]
    if page_url:
        lines += [f"来源：{page_url}", ""]
    if transcript.warning:
        lines += [f"> 转写提示：{transcript.warning}", ""]
    if transcript.segments:
        group, length, start = [], 0, None
        for segment in transcript.segments:
            text = segment.text.strip()
            if not text:
                continue
            if group and (length + len(text) > 1800 or segment.start - start >= 180):
                lines += [f"## {stamp(start)}", "", *group, ""]
                group, length, start = [], 0, None
            if start is None:
                start = segment.start
            group += [f"`{stamp(segment.start)}` {text}", ""]
            length += len(text)
        if group:
            lines += [f"## {stamp(start)}", "", *group]
    elif transcript.full_text.strip():
        lines += ["## 原始文本", "", transcript.full_text.strip(), ""]
    else:
        lines += ["暂无可用字幕。可查看已有画面，或补充字幕后重新整理。", ""]
    if grids:
        lines += ["## 画面参考", "", "> 以下画面尚未经过内容核验。", ""]
        for grid in grids:
            lines += [f"![{stamp(grid.start)} – {stamp(grid.end)}]({grid.url})", ""]
    return "\n".join(lines).strip() + "\n"
