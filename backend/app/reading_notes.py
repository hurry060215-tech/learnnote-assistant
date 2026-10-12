"""Readable source-first fallback; never turn transcript snippets into invented teaching."""
from __future__ import annotations
import re
from typing import TypedDict
from .models import TranscriptResult

def stamp(value):
    seconds = max(0, int(value or 0))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}" if seconds >= 3600 else f"{seconds // 60:02}:{seconds % 60:02}"

class SourceWindow(TypedDict):
    index: int
    start: float
    end: float


class SourceBlock(TypedDict):
    text: str
    source_windows: list[SourceWindow]


def source_block_entries(transcript: TranscriptResult, budget: int = 16000) -> list[SourceBlock]:
    """The existing request blocks, with positions from original cues only."""
    parts = [(f"[{stamp(s.start)} – {stamp(s.end)}] {s.text}",
              {"index": index, "start": s.start, "end": s.end})
             for index, s in enumerate(transcript.segments) if s.text.strip()]
    if not parts:
        parts = [(transcript.full_text, None)]
    blocks, current, windows = [], "", []
    for part, window in parts:
        for offset in range(0, len(part), budget):
            piece = part[offset:offset + budget]
            if current and len(current) + len(piece) + 2 > budget:
                blocks.append({"text": current, "source_windows": windows})
                current, windows = "", []
            current += ("\n\n" if current else "") + piece
            if window is not None and window not in windows:
                windows.append(window)
    if current.strip():
        blocks.append({"text": current, "source_windows": windows})
    return blocks


def source_blocks(transcript: TranscriptResult, budget: int = 16000):
    """Keep every source character; segment timestamps travel with their text."""
    return [block["text"] for block in source_block_entries(transcript, budget)]

def readable_extract(title, transcript, grids, page_url=""):
    lines = [
        f"# {title or '学习笔记'}",
        "",
        "> 字幕摘录：未使用文字模型。以下内容只来自已取得的字幕或转写，并保留原文定位。",
        "",
    ]
    if page_url:
        lines += [f"来源：{page_url}", ""]
    if transcript.warning:
        lines += [f"> 转写提示：{transcript.warning}", ""]
    if transcript.segments:
        usable = [segment for segment in transcript.segments if segment.text.strip()]
        if usable:
            start = stamp(usable[0].start)
            end = stamp(usable[-1].end)
            lines += ["## 概述", "", f"已取得 {len(usable)} 段带时间点的字幕，覆盖 {start}–{end}；以下按原文停顿分节。", ""]
        lines += ["## 核心要点", ""]
        for segment in usable[: min(8, len(usable))]:
            lines.append(f"- `{stamp(segment.start)}` 原文段落，见下方定位。")
        lines.append("")
        group, length, start = [], 0, None
        for segment in usable:
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
