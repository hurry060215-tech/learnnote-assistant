from __future__ import annotations

from pathlib import Path

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .media import image_to_data_url
from .models import FrameGrid, TaskOptions, TranscriptResult


def _format_ts(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _segments_window(transcript: TranscriptResult, start: float, end: float) -> str:
    lines = []
    for seg in transcript.segments:
        if seg.end >= start and seg.start <= end:
            lines.append(f"{_format_ts(seg.start)} {seg.text}")
    return "\n".join(lines)


def local_markdown_note(title: str, transcript: TranscriptResult, grids: list[FrameGrid], page_url: str = "") -> str:
    lines = [f"# {title or '学习笔记'}", ""]
    if page_url:
        lines += [f"来源：{page_url}", ""]
    if transcript.warning:
        lines += [f"> 转写提示：{transcript.warning}", ""]

    lines += ["## 课程主题", ""]
    if transcript.full_text and "未安装 faster-whisper" not in transcript.full_text:
        preview = transcript.full_text.replace("\n", " ")[:320]
        lines += [f"{preview}{'...' if len(transcript.full_text) > 320 else ''}", ""]
    else:
        lines += ["根据可下载视频画面和可用文本生成初步笔记。", ""]

    lines += ["## 时间轴重点", ""]
    if transcript.segments:
        for seg in transcript.segments[:30]:
            lines.append(f"- `{_format_ts(seg.start)}` {seg.text}")
    else:
        lines.append("- 暂无字幕。")
    lines.append("")

    lines += ["## 画面索引", ""]
    if grids:
        for grid in grids:
            lines.append(f"- `{_format_ts(grid.start)} - {_format_ts(grid.end)}` 帧预览：{grid.url}")
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
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "你是严谨的课程学习笔记助手。请结合字幕和视频画面，输出 Markdown。"
                "结构必须包含：课程主题、时间轴重点、核心概念、例题/演示步骤、易错点、复习问题、画面索引。\n\n"
                f"标题：{title}\n来源：{page_url}\n\n字幕：\n{transcript.full_text[:60000]}"
            ),
        }
    ]
    for grid in grids[:8]:
        path = Path(grid.path)
        if path.exists():
            content.append({"type": "text", "text": f"画面网格 {_format_ts(grid.start)} - {_format_ts(grid.end)}"})
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(path)}})

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
