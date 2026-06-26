from __future__ import annotations

import re
from pathlib import Path

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .media import image_to_data_url
from .models import FrameGrid, TaskOptions, TranscriptResult, VisualWindow

MAX_GRIDS_PER_VISION_CALL = 4
MAX_VISION_GRIDS = 80


def _format_ts(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _overlapping_segments(transcript: TranscriptResult, start: float, end: float):
    return [seg for seg in transcript.segments if seg.end >= start and seg.start <= end]


def _segments_window(transcript: TranscriptResult, start: float, end: float) -> str:
    lines = []
    for seg in _overlapping_segments(transcript, start, end):
        lines.append(f"{_format_ts(seg.start)} {seg.text}")
    return "\n".join(lines)


def build_visual_windows(transcript: TranscriptResult, grids: list[FrameGrid], excerpt_limit: int = 520) -> list[VisualWindow]:
    windows: list[VisualWindow] = []
    for index, grid in enumerate(grids, start=1):
        segments = _overlapping_segments(transcript, grid.start, grid.end)
        excerpt = " ".join(f"{_format_ts(seg.start)} {seg.text}" for seg in segments)
        if len(excerpt) > excerpt_limit:
            excerpt = excerpt[:excerpt_limit].rstrip() + "..."
        windows.append(
            VisualWindow(
                id=f"W{index:03d}",
                index=index,
                start=grid.start,
                end=grid.end,
                duration=max(0, grid.end - grid.start),
                frame_count=grid.frame_count,
                grid_url=grid.url,
                grid_path=grid.path,
                transcript_excerpt=excerpt,
                segments=segments,
            )
        )
    return windows


def _sentences(text: str, limit: int = 8) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s*", cleaned)
    ranked = sorted((part.strip() for part in parts if part.strip()), key=len, reverse=True)
    return ranked[:limit]


def _timeline_lines(transcript: TranscriptResult, grids: list[FrameGrid]) -> list[str]:
    if grids:
        lines = []
        for grid in grids:
            window = _segments_window(transcript, grid.start, grid.end)
            if window:
                lines.append(f"- `{_format_ts(grid.start)} - {_format_ts(grid.end)}`\n{window}")
            else:
                lines.append(f"- `{_format_ts(grid.start)} - {_format_ts(grid.end)}` 参考画面网格：{grid.url}")
        return lines
    if transcript.segments:
        return [f"- `{_format_ts(seg.start)}` {seg.text}" for seg in transcript.segments[:30]]
    return ["- 暂无字幕或画面窗口。"]


def _window_summary_lines(transcript: TranscriptResult, grids: list[FrameGrid]) -> list[str]:
    if not grids:
        return ["- 未生成画面窗口。"]
    lines = []
    for grid in grids:
        window = _segments_window(transcript, grid.start, grid.end).replace("\n", " ")
        if window:
            lines.append(
                f"- `{_format_ts(grid.start)} - {_format_ts(grid.end)}` "
                f"结合画面网格和字幕：{window[:260]}{'...' if len(window) > 260 else ''}"
            )
        else:
            lines.append(f"- `{_format_ts(grid.start)} - {_format_ts(grid.end)}` 仅生成画面网格，需结合截图回看：{grid.url}")
    return lines


def _grid_batches(grids: list[FrameGrid], batch_size: int = MAX_GRIDS_PER_VISION_CALL) -> list[list[FrameGrid]]:
    if batch_size <= 0:
        batch_size = MAX_GRIDS_PER_VISION_CALL
    limited = grids[:MAX_VISION_GRIDS]
    return [limited[index: index + batch_size] for index in range(0, len(limited), batch_size)]


def _grid_index_lines(grids: list[FrameGrid]) -> list[str]:
    return [
        (
            f"- W{index:03d} `{_format_ts(grid.start)} - {_format_ts(grid.end)}` "
            f"{grid.frame_count} 帧，画面网格：{grid.url}"
        )
        for index, grid in enumerate(grids, start=1)
    ]


def _grid_window_prompt(transcript: TranscriptResult, grids: list[FrameGrid], offset: int = 0) -> str:
    sections = []
    for index, grid in enumerate(grids, start=offset + 1):
        sections.append(
            "\n".join([
                f"窗口 W{index:03d}：{_format_ts(grid.start)} - {_format_ts(grid.end)}",
                f"画面网格：{grid.url}",
                f"帧数：{grid.frame_count}",
                f"对应字幕：\n{_segments_window(transcript, grid.start, grid.end) or '无对应字幕'}",
                "请结合紧随其后的画面网格，只输出这个窗口的局部学习摘要，并保留 W 编号。",
            ])
        )
    return "\n\n".join(sections)


def local_markdown_note(title: str, transcript: TranscriptResult, grids: list[FrameGrid], page_url: str = "") -> str:
    lines = [f"# {title or '学习笔记'}", ""]
    if page_url:
        lines += [f"来源：{page_url}", ""]
    if transcript.warning:
        lines += [f"> 转写提示：{transcript.warning}", ""]

    key_sentences = _sentences(transcript.full_text, limit=6)

    lines += ["## 课程主题", ""]
    if transcript.full_text and "未安装 faster-whisper" not in transcript.full_text:
        preview = transcript.full_text.replace("\n", " ")[:320]
        lines += [f"{preview}{'...' if len(transcript.full_text) > 320 else ''}", ""]
    else:
        lines += ["根据可下载视频画面和可用文本生成初步笔记。", ""]

    lines += ["## 时间轴重点", ""]
    lines.extend(_timeline_lines(transcript, grids))
    lines.append("")

    lines += ["## 分段图文摘要", ""]
    lines.extend(_window_summary_lines(transcript, grids))
    lines.append("")

    windows = build_visual_windows(transcript, grids)
    if windows:
        lines += ["## 画面-字幕对齐索引", ""]
        for window in windows:
            lines.append(
                f"- {window.id} `{_format_ts(window.start)} - {_format_ts(window.end)}` "
                f"{window.frame_count} 帧：{window.grid_url}"
            )
            if window.transcript_excerpt:
                lines.append(f"  同步字幕：{window.transcript_excerpt}")
        lines.append("")

    lines += ["## 核心概念", ""]
    if key_sentences:
        for item in key_sentences[:5]:
            lines.append(f"- {item}")
    else:
        lines.append("- 当前任务没有可用字幕；请优先查看画面索引，或安装 faster-whisper 后重新处理。")
    lines.append("")

    lines += ["## 例题 / 演示步骤", ""]
    if grids:
        for grid in grids[:8]:
            window = _segments_window(transcript, grid.start, grid.end).replace("\n", " ")
            detail = window[:180] + ("..." if len(window) > 180 else "")
            lines.append(f"- `{_format_ts(grid.start)} - {_format_ts(grid.end)}` 回看画面网格：{grid.url}")
            if detail:
                lines.append(f"  相关字幕：{detail}")
    else:
        lines.append("- 未生成画面网格，无法定位演示步骤。")
    lines.append("")

    lines += ["## 易错点", ""]
    lines.append("- 对照时间轴回看术语首次出现的位置，避免只记结论、不记使用条件。")
    lines.append("- 对照画面索引回看界面操作、代码演示、PPT 切换等只靠字幕容易遗漏的内容。")
    if transcript.warning:
        lines.append("- 当前转写不完整，关键概念需要结合原视频再次确认。")
    lines.append("")

    lines += ["## 画面索引", ""]
    if grids:
        for index, grid in enumerate(grids, start=1):
            label = f"W{index:03d} {_format_ts(grid.start)} - {_format_ts(grid.end)}"
            lines.append(f"- W{index:03d} `{_format_ts(grid.start)} - {_format_ts(grid.end)}` {grid.frame_count} 帧：{grid.url}")
            lines.append(f"![{label}]({grid.url})")
    else:
        lines.append("- 未生成帧预览。")
    lines.append("")

    lines += [
        "## 复习问题",
        "",
        "1. 这段课程的核心概念是什么？",
        "2. 哪些画面或演示步骤需要回看？",
        "3. 哪些术语、公式或操作步骤容易遗漏？",
        "",
    ]
    return "\n".join(lines)


def summarize_with_llm(
    title: str,
    transcript: TranscriptResult,
    grids: list[FrameGrid],
    options: TaskOptions,
    page_url: str = "",
) -> str | None:
    api_key = options.llm_api_key or LLM_API_KEY
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    client = OpenAI(api_key=api_key, base_url=options.llm_base_url or LLM_BASE_URL)
    model = options.llm_model or LLM_MODEL

    if grids:
        partials = []
        batches = _grid_batches(grids)
        for index, batch in enumerate(batches, start=1):
            batch_offset = (index - 1) * MAX_GRIDS_PER_VISION_CALL
            content: list[dict] = [
                {
                    "type": "text",
                    "text": (
                        "你是严谨的课程学习笔记助手。下面是一批视频画面网格和对应字幕。"
                        "请先做局部图文总结，不要写完整总笔记。\n"
                        "每个窗口必须包含：时间范围、画面可见信息、字幕重点、操作/PPT/代码/公式/例题线索、可能的易错点。\n"
                        f"标题：{title}\n来源：{page_url}\n批次：{index}\n\n"
                        f"{_grid_window_prompt(transcript, batch, batch_offset)}"
                    ),
                }
            ]
            for grid in batch:
                path = Path(grid.path)
                if path.exists():
                    content.append({"type": "image_url", "image_url": {"url": image_to_data_url(path)}})
            if len(content) == 1:
                continue
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0.2,
                )
                partial = response.choices[0].message.content or ""
                if partial.strip():
                    partials.append(partial.strip())
            except Exception:
                return None

        if partials:
            merge_prompt = "\n\n".join(f"### 局部图文摘要 {idx}\n{partial}" for idx, partial in enumerate(partials, start=1))
            frame_index = "\n".join(_grid_index_lines(grids[:MAX_VISION_GRIDS]))
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "你是严谨的课程学习笔记助手。请把下面所有局部图文摘要和字幕合并成一份完整 Markdown 学习笔记。"
                                "必须覆盖所有时间窗口，不要只总结开头。\n\n"
                                "结构必须包含：课程主题、时间轴重点、核心概念、例题/演示步骤、易错点、复习问题、画面索引。\n"
                                "画面索引必须保留 W 编号、时间范围和画面网格 URL，方便用户回看截图。\n"
                                f"笔记风格：{options.note_style}；详略程度：{options.summary_depth}。\n"
                                f"标题：{title}\n来源：{page_url}\n\n"
                                f"画面索引清单：\n{frame_index}\n\n"
                                f"完整字幕节选：\n{transcript.full_text[:60000]}\n\n"
                                f"{merge_prompt}"
                            ),
                        }
                    ],
                    temperature=0.2,
                )
                return response.choices[0].message.content or None
            except Exception:
                return None

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "你是严谨的课程学习笔记助手。请结合字幕输出 Markdown。"
                "结构必须包含：课程主题、时间轴重点、核心概念、例题/演示步骤、易错点、复习问题、画面索引。\n\n"
                f"笔记风格：{options.note_style}；详略程度：{options.summary_depth}。\n"
                f"标题：{title}\n来源：{page_url}\n\n字幕：\n{transcript.full_text[:60000]}"
            ),
        }
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
        )
        return response.choices[0].message.content or None
    except Exception:
        return None


def summarize(title: str, transcript: TranscriptResult, grids: list[FrameGrid], options: TaskOptions, page_url: str = "") -> str:
    return summarize_with_llm(title, transcript, grids, options, page_url) or local_markdown_note(title, transcript, grids, page_url)


def summarize_page_text(title: str, page_url: str, page_text: str, options: TaskOptions) -> str:
    transcript = TranscriptResult(
        language="unknown",
        source="page-text",
        full_text=page_text,
        segments=[],
    )
    generated = summarize_with_llm(title, transcript, [], options, page_url)
    if generated:
        return generated
    text = (page_text or "").strip()
    excerpt = text[:1200] + ("..." if len(text) > 1200 else "")
    return "\n".join([
        f"# {title or '当前页面文本总结'}",
        "",
        f"来源：{page_url}",
        "",
        "## 页面摘要",
        "",
        excerpt or "当前页面没有提取到可用文本。",
        "",
        "## 复习问题",
        "",
        "1. 本页最重要的概念是什么？",
        "2. 哪些内容需要结合课程视频再确认？",
        "3. 哪些术语或步骤需要做成卡片复习？",
        "",
    ])
