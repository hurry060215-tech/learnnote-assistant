from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MAX_RETRIES, LLM_MODEL, LLM_REQUEST_TIMEOUT_SECONDS
from .media import image_to_data_url
from .models import FrameGrid, TaskOptions, TranscriptResult, VisualWindow

MAX_GRIDS_PER_VISION_CALL = 4
MAX_VISION_GRIDS = 80
MAX_LLM_ERROR_MESSAGE = 240
PAGE_UI_EXACT_TEXTS = {
    "字幕", "主字幕", "副字幕", "添加字幕", "暂无字幕", "关闭", "弹幕", "弹幕设置",
    "弹幕列表", "关闭弹幕", "发送弹幕", "播放", "暂停", "倍速", "自动播放", "网页全屏", "全屏",
}
PAGE_UI_MARKERS = (
    "字幕设置", "字幕大小", "字幕颜色", "恢复默认设置", "关闭弹幕", "弹幕设置", "弹幕列表",
    "发送弹幕", "按类型屏蔽", "按用户屏蔽", "播放速度", "自动播放", "网页全屏",
)


def llm_provider_name(base_url: str) -> str:
    host = (urlparse(base_url or "").hostname or "").lower()
    if "openai.com" in host:
        return "openai"
    if "groq.com" in host:
        return "groq"
    if "generativelanguage.googleapis.com" in host:
        return "gemini"
    if "dashscope.aliyuncs.com" in host:
        return "dashscope"
    if "siliconflow.cn" in host:
        return "siliconflow"
    if "openrouter.ai" in host:
        return "openrouter"
    if "deepseek.com" in host:
        return "deepseek"
    if "moonshot.cn" in host or "platform.kimi.com" in host:
        return "kimi"
    if "bigmodel.cn" in host:
        return "zhipu"
    if "volces.com" in host:
        return "doubao"
    if "minimaxi.com" in host or "minimax.io" in host:
        return "minimax"
    if "baidubce.com" in host or "baiduqianfan.ai" in host:
        return "qianfan"
    if host in {"127.0.0.1", "localhost"}:
        return "local-openai-compatible"
    return "openai-compatible"


def chat_completion_provider_kwargs(base_url: str) -> dict:
    provider = llm_provider_name(base_url)
    if provider == "deepseek":
        return {"temperature": 0.2, "extra_body": {"thinking": {"type": "disabled"}}}
    if provider == "kimi":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {"temperature": 0.2}


def llm_model_supports_vision(base_url: str, model: str) -> bool:
    provider = llm_provider_name(base_url)
    normalized = str(model or "").strip().lower()
    if provider in {"deepseek", "minimax"}:
        return False
    if provider == "dashscope":
        return any(token in normalized for token in ("-vl", "omni", "qvq"))
    if provider == "kimi":
        return any(token in normalized for token in ("k2.6", "k2.7"))
    if provider == "zhipu":
        return "vision" in normalized or bool(re.search(r"glm-[0-9.]+v(?:-|$)", normalized))
    if provider == "doubao":
        return "vision" in normalized
    if provider == "qianfan":
        return "ernie-4.5" in normalized or "vision" in normalized
    return True


def llm_base_host(base_url: str) -> str:
    parsed = urlparse(base_url or "")
    return parsed.netloc or parsed.path.strip("/") or ""


def _safe_llm_error(exc: BaseException) -> str:
    message = re.sub(r"\s+", " ", str(exc or "")).strip()
    message = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-<redacted>", message)
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer <redacted>", message)
    message = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[A-Za-z0-9._~+/=-]{8,}", r"\1<redacted>", message)
    if len(message) > MAX_LLM_ERROR_MESSAGE:
        message = message[:MAX_LLM_ERROR_MESSAGE].rstrip() + "..."
    return message or exc.__class__.__name__


def _record_llm_event(events: list[dict] | None, stage: str, code: str, exc: BaseException | None = None, **extra) -> None:
    if events is None:
        return
    event = {
        "stage": stage,
        "code": code,
    }
    if exc is not None:
        event.update({
            "error_type": exc.__class__.__name__,
            "message": _safe_llm_error(exc),
        })
    event.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    events.append(event)


def llm_warning_from_events(options: TaskOptions, events: list[dict], fallback: str) -> str:
    if not events:
        return fallback
    base_url = options.llm_base_url or LLM_BASE_URL
    model = options.llm_model or LLM_MODEL
    provider = llm_provider_name(base_url)
    latest = events[-1]
    stage = latest.get("stage") or "llm"
    code = latest.get("code") or "api_error"
    message = latest.get("message") or latest.get("error_type") or "unknown error"
    return (
        f"LLM 调用降级：provider={provider}，model={model}，base={llm_base_host(base_url) or '-'}，"
        f"stage={stage}，code={code}，reason={message}；已使用本地画面索引模板。"
    )


def _format_ts(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _segment_overlaps_window(segment, start: float, end: float) -> bool:
    seg_start = float(getattr(segment, "start", 0) or 0)
    seg_end = float(getattr(segment, "end", seg_start) or seg_start)
    if seg_end < seg_start:
        seg_start, seg_end = seg_end, seg_start
    if seg_start == seg_end:
        return start <= seg_start < end
    return seg_end > start and seg_start < end


def _overlapping_segments(transcript: TranscriptResult, start: float, end: float):
    return [seg for seg in transcript.segments if _segment_overlaps_window(seg, start, end)]


def _segments_window(transcript: TranscriptResult, start: float, end: float) -> str:
    lines = []
    for seg in _overlapping_segments(transcript, start, end):
        lines.append(f"{_format_ts(seg.start)} {seg.text}")
    return "\n".join(lines)


def _window_learning_points(segments: list[TranscriptSegment], frame_timestamps: list[float], limit: int = 3) -> list[str]:
    points: list[str] = []
    for segment in segments:
        text = re.sub(r"\s+", " ", segment.text or "").strip(" -•\t")
        if not text or text in points:
            continue
        if len(text) > 120:
            text = text[:120].rstrip() + "..."
        points.append(text)
        if len(points) >= limit:
            break
    if points:
        return points
    frame_times = " / ".join(_format_ts(value) for value in frame_timestamps[:3])
    if frame_times:
        return [f"按 {frame_times} 这几帧核对本段画面变化。"]
    return ["暂无同步字幕；先从截图标题、公式、代码或演示状态提炼本段主题。"]


def build_visual_windows(transcript: TranscriptResult, grids: list[FrameGrid], excerpt_limit: int = 520) -> list[VisualWindow]:
    windows: list[VisualWindow] = []
    for index, grid in enumerate(grids, start=1):
        segments = _overlapping_segments(transcript, grid.start, grid.end)
        excerpt = " ".join(f"{_format_ts(seg.start)} {seg.text}" for seg in segments)
        if len(excerpt) > excerpt_limit:
            excerpt = excerpt[:excerpt_limit].rstrip() + "..."
        key_points = _window_learning_points(segments, grid.frame_timestamps)
        windows.append(
            VisualWindow(
                id=f"W{index:03d}",
                index=index,
                start=grid.start,
                end=grid.end,
                duration=max(0, grid.end - grid.start),
                frame_count=grid.frame_count,
                frame_timestamps=grid.frame_timestamps,
                grid_url=grid.url,
                grid_path=grid.path,
                transcript_excerpt=excerpt,
                local_summary=key_points[0],
                key_points=key_points,
                summary_points=key_points,
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


def _source_host(page_url: str) -> str:
    match = re.match(r"^https?://([^/?#]+)", page_url or "", re.I)
    return match.group(1) if match else ""


def note_template_instruction(options: TaskOptions) -> str:
    template = str(options.note_template or "standard").strip().lower()
    mapping = {
        "classroom-review": "Classroom review: organize knowledge points, explanations, common mistakes, and review questions supported by the source.",
        "operation-tutorial": "Operation tutorial: document verified steps, visible interface changes, exact commands, and evidenced common errors; omit any unsupported step or result.",
        "exam-review": "Exam review: organize definitions, testable points, memory cards, and practice questions using only source-supported facts.",
        "quick-summary": "Quick summary: keep only supported conclusions and a compact timestamped timeline.",
        "custom": "Custom profile: follow note_profile_name, note_profile_prompt, and note_profile_sections without weakening evidence constraints.",
        "standard": "标准学习笔记：按课程主题、时间轴重点、核心概念、例题/演示步骤、易错点、复习问题组织。",
        "timeline": "时间轴模板：优先按时间段组织，每段保留关键结论、画面证据、字幕依据和回看动作。",
        "cornell": "康奈尔模板：每个主题输出线索栏、笔记栏和课后总结，并在末尾生成复习问题。",
        "qa": "问答复习模板：把内容整理成问题、答案、证据时间点和易错提醒，适合背诵复盘。",
        "visual-handout": "图文讲义模板：突出画面窗口、截图索引、PPT/板书/代码/公式证据和对应字幕摘要。",
        "mindmap": "层级脑图模板：使用多级 Markdown 列表呈现主题、分支、概念关系和时间点，不使用 Mermaid。",
        "flashcards": "记忆卡片模板：按“问题 / 简答 / 证据时间点 / 易错提醒”生成可独立复习的卡片。",
        "formula-sheet": "公式清单模板：集中整理公式、变量含义、适用条件、推导线索和例题时间点。",
        "bilingual": "双语对照模板：关键术语保留原文并给出中文解释，重点结论按中英对照组织。",
    }
    return mapping.get(template, mapping["standard"])


def note_style_instruction(options: TaskOptions) -> str:
    style = str(options.note_style or "study").strip().lower()
    if style == "custom" and options.note_profile_prompt:
        return f"自定义风格 {options.note_profile_name or '用户模板'}：{options.note_profile_prompt}"
    mapping = {
        "classroom-review": "Classroom review: explain concepts, preserve examples and common mistakes, then create evidence-grounded review questions.",
        "operation-tutorial": "Operation tutorial: require steps, interface changes, commands, and common errors. Every item must cite transcript or visual evidence; never invent missing operations.",
        "exam-review": "Exam review: extract definitions, test points, memory cards, and answerable practice questions grounded in the material.",
        "quick-summary": "Quick summary: output only key conclusions and timestamped navigation, with no speculative background.",
        "study": "学习笔记：解释概念、保留例子和易错点，结尾给出可执行的复习任务。",
        "concise": "重点速记：只保留高价值结论、关键词和时间点，避免重复背景。",
        "outline": "重点速记：只保留高价值结论、关键词和时间点，避免重复背景。",
        "exam": "考点复习：突出定义、公式、常见题型、易错项和自测问题。",
        "lecture": "课程讲义：按授课顺序完整解释主题，并串联板书、PPT、演示和例题。",
        "concept": "概念精讲：先给直观解释，再写严格定义、概念关系、反例和应用。",
        "code": "代码教程：保留代码步骤、关键 API、输入输出、运行结果和调试注意事项。",
        "academic": "论文导读：围绕研究问题、方法、证据、贡献、局限和可复现实验整理。",
        "language": "语言学习：提取词汇、表达、语法、语境例句和跟读复习材料。",
    }
    return mapping.get(style, mapping["study"])


def learning_goal(options: TaskOptions) -> str:
    """Resolve the new learning-goal semantics while accepting legacy option values."""
    style = str(options.note_style or "").strip().lower().replace("_", "-")
    template = str(options.note_template or "").strip().lower().replace("_", "-")
    explicit_goals = {
        "classroom-review": "deep",
        "operation-tutorial": "deep",
        "exam-review": "exam",
        "quick-summary": "quick",
        "custom": "auto",
        "auto": "auto",
        "automatic": "auto",
        "default": "auto",
        "自动": "auto",
        "自动默认": "auto",
        "deep": "deep",
        "deep-understanding": "deep",
        "understanding": "deep",
        "深入理解": "deep",
        "quick": "quick",
        "quick-review": "quick",
        "review": "quick",
        "快速回顾": "quick",
        "exam": "exam",
        "exam-practice": "exam",
        "self-test": "exam",
        "备考自测": "exam",
    }
    if style in explicit_goals:
        return explicit_goals[style]
    if template in explicit_goals:
        return explicit_goals[template]

    # Legacy style/template combinations map to the closest learning intent.
    if style in {"concise", "outline"} or template in {"timeline", "mindmap"}:
        return "quick"
    if style == "exam" or template in {"qa", "flashcards", "formula-sheet"}:
        return "exam"
    if style in {"lecture", "concept", "code", "academic", "language"}:
        return "deep"
    return "auto"


def learning_goal_instruction(options: TaskOptions) -> str:
    goal = learning_goal(options)
    instructions = {
        "auto": (
            "自动默认：先判断材料更适合深入理解、快速回顾还是备考自测，再采用对应结构；"
            "在开头用一行写明所选目标和判断依据。不要为了凑模板生成材料中不存在的章节。"
        ),
        "deep": (
            "深入理解：严格按“知识地图 → 概念精讲（直觉、定义、机制）→ 证据与应用 → "
            "概念联系、边界与迁移 → 理解检验”组织。例题、易错点和视觉证据仅在材料支持时出现。"
        ),
        "quick": (
            "快速回顾：严格按“一页速览 → 关键结论 → 回看定位 → 下一步复习”组织。"
            "使用短条目，删除推导、重复背景和非关键例题；不要生成独立的课程主题、例题或易错点章节。"
        ),
        "exam": (
            "备考自测：严格按“考点清单 → 闭卷自测题 → 答案与评分点 → 题型/陷阱复盘”组织。"
            "题目必须可作答、答案必须与题号对应；只收录材料支持的考点，不生成通用课程讲义结构。"
        ),
    }
    return instructions[goal]


def summary_depth_instruction(options: TaskOptions) -> str:
    depth = str(options.summary_depth or "standard").strip().lower()
    aliases = {"concise": "brief", "short": "brief", "detailed": "deep", "long": "deep"}
    depth = aliases.get(depth, depth)
    constraints = {
        "brief": (
            "简洁深度：覆盖字幕中至少 60% 的高价值知识点；正文目标 500-900 个中文字符；"
            "例题/应用练习 0-1 个；复习或自测题恰好 2 题。"
        ),
        "standard": (
            "标准深度：覆盖字幕中至少 80% 的高价值知识点；正文目标 1000-1800 个中文字符；"
            "例题/应用练习 1-2 个；复习或自测题恰好 4 题。"
        ),
        "deep": (
            "深入深度：覆盖字幕中至少 95% 的高价值知识点及其前提和联系；正文目标 2200-3600 个中文字符；"
            "例题/应用练习 2-4 个；复习或自测题 6-8 题。"
        ),
    }
    return constraints.get(depth, constraints["standard"])


def note_generation_contract(options: TaskOptions) -> str:
    custom_profile = ""
    if options.note_profile_prompt:
        sections = "、".join(item for item in options.note_profile_sections if str(item).strip())
        custom_profile = (
            f"用户导入风格：{options.note_profile_name or '自定义'}。\n"
            f"风格要求：{options.note_profile_prompt}\n"
            f"章节框架：{sections or '按内容自然组织'}。\n"
            "自定义风格不能覆盖真实性、时间戳来源和不编造内容等共同约束。\n"
        )
    style_use_case = str(options.note_style or "").strip().lower().replace("_", "-")
    template_use_case = str(options.note_template or "").strip().lower().replace("_", "-")
    supported_use_cases = {"classroom-review", "operation-tutorial", "exam-review", "quick-summary", "custom"}
    use_case = style_use_case if style_use_case in supported_use_cases else template_use_case
    use_case_contracts = {
        "classroom-review": "Required use case: knowledge points, explanations, common mistakes, and review questions; include only source-supported items.\n",
        "operation-tutorial": (
            "Required use case: operation tutorial. Organize verified steps in execution order; for each step capture visible interface changes, exact commands when present, and evidenced common errors. "
            "Every step and error must be supported by transcript timestamps or visual-window evidence. Omit unsupported commands, clicks, outcomes, and troubleshooting advice.\n"
        ),
        "exam-review": "Required use case: definitions, testable points, memory cards, and practice questions; answers must be derivable from the evidence.\n",
        "quick-summary": "Required use case: concise conclusions and timestamped timeline only; remove repetition and unsupported context.\n",
        "custom": "Required use case: apply the imported note_profile fields while preserving all shared evidence rules.\n",
    }
    return (
        use_case_contracts.get(use_case, "")
        + custom_profile + f"学习目标：{learning_goal_instruction(options)}\n"
        f"深度约束：{summary_depth_instruction(options)}\n"
        "共同约束：时间戳只能来自字幕段或画面窗口；不要编造画面、例题或事实。"
        "没有对应内容时省略可选章节，不要用空章节或套话补齐。"
    )


def _depth_counts(options: TaskOptions) -> tuple[int, int]:
    depth = str(options.summary_depth or "standard").strip().lower()
    if depth in {"brief", "concise", "short"}:
        return 1, 2
    if depth in {"deep", "detailed", "long"}:
        return 3, 6
    return 2, 4


def _context_topic_lines(title: str, transcript: TranscriptResult, limit: int = 3) -> list[str]:
    candidates = []
    for item in [title, *_sentences(transcript.full_text, limit=limit * 2)]:
        cleaned = re.sub(r"\s+", " ", item or "").strip(" -•\t")
        if not cleaned or cleaned in candidates:
            continue
        if len(cleaned) > 96:
            cleaned = cleaned[:96].rstrip() + "..."
        candidates.append(cleaned)
        if len(candidates) >= limit:
            break
    return candidates


def _page_context_excerpt(page_context: str = "", limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", page_context or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _page_context_markdown_lines(page_context: str = "") -> list[str]:
    excerpt = _page_context_excerpt(page_context)
    if not excerpt:
        return []
    return [
        "- Page context: captured from the current browser page and used only as course/chapter context, not as transcript.",
        f"  {excerpt}",
    ]


def _page_context_prompt(page_context: str = "") -> str:
    excerpt = _page_context_excerpt(page_context, limit=4000)
    if not excerpt:
        return ""
    return (
        "Page context captured from the current browser page. Use it for course title, chapter, outline, "
        "exercise wording, and surrounding learning context. Do not treat it as timestamped transcript.\n"
        f"{excerpt}\n"
    )


def _learning_context_lines(title: str, transcript: TranscriptResult, windows: list[VisualWindow], page_url: str = "", page_context: str = "") -> list[str]:
    lines = ["## 学习上下文", ""]
    title_text = (title or "未命名课程").strip()
    lines.append(f"- 课程标题：{title_text}")
    if page_url:
        host = _source_host(page_url)
        lines.append(f"- 来源页面：{page_url}" + (f"（{host}）" if host else ""))
    lines.append(f"- 文本来源：{transcript.source or 'unknown'}")
    if windows:
        first, last = windows[0], windows[-1]
        covered = sum(1 for window in windows if window.transcript_excerpt.strip())
        lines.append(
            f"- 画面切片：{len(windows)} 个窗口，覆盖 `{_format_ts(first.start)} - {_format_ts(last.end)}`；"
            f"{covered}/{len(windows)} 个窗口有同步字幕。"
        )
    else:
        lines.append("- 画面切片：未生成；当前笔记主要依赖字幕、页面文本或后续本地视频回看。")
    lines.extend(_page_context_markdown_lines(page_context))
    topics = _context_topic_lines(title_text, transcript)
    if topics:
        lines.append("- 主题线索：" + "；".join(topics))
    lines.append("- 使用方式：先按时间轴扫一遍，再用 W 编号回看画面网格，最后把易错点和自测问题整理成复习卡。")
    lines.append("")
    return lines


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


def _window_learning_card_lines(windows: list[VisualWindow]) -> list[str]:
    if not windows:
        return ["- 未生成视觉切片。"]

    lines: list[str] = []
    for window in windows:
        excerpt = window.transcript_excerpt.strip()
        label = f"{window.id} {_format_ts(window.start)} - {_format_ts(window.end)}"
        frame_times = ", ".join(_format_ts(value) for value in window.frame_timestamps[:9]) or "-"
        lines.extend([
            f"### {window.id} `{_format_ts(window.start)} - {_format_ts(window.end)}`",
            f"- 画面网格：{window.grid_url}",
            f"![{label}]({window.grid_url})",
            f"- 帧时间：{frame_times}",
            f"- 切片范围：约 {int(window.duration)} 秒，{window.frame_count} 帧。",
        ])
        if excerpt:
            lines.append(f"- 字幕线索：{excerpt}")
            lines.append("- 回看目标：对照画面确认本段的板书、PPT 切换、代码/界面操作和例题步骤是否被字幕完整覆盖。")
            lines.append("- 复习动作：用自己的话复述这一窗口的结论，再回到截图核对关键术语和操作顺序。")
            lines.append("- 窗口检查点：")
            lines.extend(_window_checkpoint_lines(window))
            lines.append("- 自测问题：")
            lines.extend(visual_window_review_question_lines(window))
        else:
            lines.append("- 字幕线索：本窗口没有匹配到字幕。")
            lines.append("- 回看目标：重点检查画面里的 PPT 标题、板书、公式、代码、界面状态或演示步骤。")
            lines.append("- 复习动作：先根据截图补一句本段主题，再和前后窗口串起来复盘。")
            lines.append("- 窗口检查点：")
            lines.extend(_window_checkpoint_lines(window))
            lines.append("- 自测问题：")
            lines.extend(visual_window_review_question_lines(window))
        lines.append("")
    return lines


def _checkpoint_text(text: str, limit: int = 96) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _window_checkpoint_lines(window: VisualWindow, limit: int = 3) -> list[str]:
    if window.segments:
        lines = []
        for segment in window.segments[:limit]:
            text = _checkpoint_text(segment.text)
            if not text:
                continue
            lines.append(
                f"  - `{_format_ts(segment.start)}` {text}；对照画面确认对应的板书、PPT、代码或操作步骤。"
            )
        if lines:
            return lines
    return [
        "  - 无同步字幕；先描述画面网格中的标题、公式、代码或界面状态，再回看原视频确认上下文。"
    ]


def visual_window_review_question_lines(window: VisualWindow, limit: int = 2) -> list[str]:
    if window.segments:
        lines = []
        for segment in window.segments[:limit]:
            text = _checkpoint_text(segment.text, 72)
            if not text:
                continue
            lines.append(
                f"  - `{_format_ts(segment.start)}` 这句“{text}”在画面中对应的标题、公式、代码或操作状态是什么？"
            )
        if lines:
            return lines

    frame_times = ", ".join(_format_ts(value) for value in window.frame_timestamps[:3])
    if frame_times:
        return [
            f"  - 这些帧（{frame_times}）里最能说明本段主题的画面证据是什么？",
            "  - 如果没有字幕，能否用一句话描述这组截图的操作顺序或 PPT 结构？",
        ]
    return [
        "  - 这个窗口里最值得回看的标题、公式、代码、界面状态或演示步骤是什么？",
    ]


def _study_route_lines(transcript: TranscriptResult, windows: list[VisualWindow]) -> list[str]:
    if windows:
        covered = [window for window in windows if window.transcript_excerpt.strip()]
        uncovered = [window for window in windows if not window.transcript_excerpt.strip()]
        priority = uncovered[:2] or covered[:2] or windows[:2]
        lines = [
            f"- 先用“时间轴重点”快速扫完整体，再按 {len(windows)} 个画面窗口回看截图证据。",
            f"- 字幕覆盖：{len(covered)}/{len(windows)} 个窗口有同步字幕；无字幕窗口优先看 PPT 标题、板书、代码、公式和界面状态。",
        ]
        if priority:
            focus = "、".join(
                f"{window.id} `{_format_ts(window.start)} - {_format_ts(window.end)}`"
                for window in priority
            )
            lines.append(f"- 优先回看：{focus}，把画面变化和字幕结论对齐后再整理概念。")
        lines.append("- 最后用“复习问题”自测：先口头复述，再回到对应 W 窗口核对遗漏的演示步骤。")
        return lines
    if transcript.segments:
        return [
            "- 先按转写时间轴建立知识框架，再回到原视频补齐画面演示。",
            "- 当前没有画面窗口；如果需要图文笔记，请确认 ffmpeg 可用并重新生成切片。",
            "- 最后用“复习问题”自测，重点核对术语、步骤和例题条件。",
        ]
    return [
        "- 当前缺少字幕和画面窗口；先检查下载/转写诊断，或改用本地视频入口重新处理。",
        "- 如果课程页无法直取，上传本地视频后仍会走同一套转写、切片和图文总结管线。",
    ]


VisionGridEntry = tuple[int, FrameGrid]


def select_vision_grid_entries(grids: list[FrameGrid], limit: int = MAX_VISION_GRIDS) -> list[VisionGridEntry]:
    if limit <= 0 or not grids:
        return []
    total = len(grids)
    if total <= limit:
        return list(enumerate(grids))
    if limit == 1:
        return [(0, grids[0])]
    selected_indices = [
        round(index * (total - 1) / (limit - 1))
        for index in range(limit)
    ]
    seen: set[int] = set()
    unique_indices: list[int] = []
    for index in selected_indices:
        bounded = min(total - 1, max(0, int(index)))
        if bounded not in seen:
            seen.add(bounded)
            unique_indices.append(bounded)
    if len(unique_indices) < limit:
        for index in range(total):
            if index not in seen:
                seen.add(index)
                unique_indices.append(index)
                if len(unique_indices) >= limit:
                    break
    unique_indices = sorted(unique_indices[:limit])
    return [(index, grids[index]) for index in unique_indices]


def _grid_batches(grids: list[FrameGrid], batch_size: int = MAX_GRIDS_PER_VISION_CALL) -> list[list[VisionGridEntry]]:
    if batch_size <= 0:
        batch_size = MAX_GRIDS_PER_VISION_CALL
    selected = select_vision_grid_entries(grids)
    return [selected[index: index + batch_size] for index in range(0, len(selected), batch_size)]


def _grid_index_lines(grids: list[FrameGrid]) -> list[str]:
    return [
        (
            f"- W{index + 1:03d} `{_format_ts(grid.start)} - {_format_ts(grid.end)}` "
            f"{grid.frame_count} 帧，画面网格：{grid.url}"
        )
        for index, grid in select_vision_grid_entries(grids)
    ]


def _grid_window_prompt(transcript: TranscriptResult, entries: list[VisionGridEntry]) -> str:
    sections = []
    for original_index, grid in entries:
        window_id = f"W{original_index + 1:03d}"
        sections.append(
            "\n".join([
                f"窗口 {window_id}：{_format_ts(grid.start)} - {_format_ts(grid.end)}",
                f"画面网格：{grid.url}",
                f"帧数：{grid.frame_count}",
                f"对应字幕：\n{_segments_window(transcript, grid.start, grid.end) or '无对应字幕'}",
                "请结合同编号标注的画面网格，只输出这个窗口的局部学习摘要，并保留 W 编号。",
            ])
        )
    return "\n\n".join(sections)


def _visual_appendix_markdown(transcript: TranscriptResult, grids: list[FrameGrid]) -> str:
    windows = build_visual_windows(transcript, grids)
    if not windows:
        return ""

    lines = [
        "## 画面切片附录",
        "",
        "> 这是系统自动附加的确定性切片索引，用来保证每个视觉窗口都有 W 编号、时间范围、截图入口和回看检查点。",
        "",
    ]
    for window in windows:
        label = f"{window.id} {_format_ts(window.start)} - {_format_ts(window.end)}"
        frame_times = ", ".join(_format_ts(value) for value in window.frame_timestamps) or "-"
        lines.extend([
            f"### {window.id} `{_format_ts(window.start)} - {_format_ts(window.end)}`",
            f"- 画面网格：{window.grid_url}",
            f"![{label}]({window.grid_url})",
            f"- 帧时间：{frame_times}",
            f"- 字幕线索：{window.transcript_excerpt or '本窗口没有匹配到字幕。'}",
            "- 回看检查点：",
            *_window_checkpoint_lines(window),
            "- 自测问题：",
            *visual_window_review_question_lines(window),
            "",
        ])
    return "\n".join(lines).rstrip()


def ensure_visual_appendix(markdown: str, transcript: TranscriptResult, grids: list[FrameGrid]) -> str:
    note = (markdown or "").strip()
    appendix = _visual_appendix_markdown(transcript, grids)
    if not appendix:
        return note
    if re.search(r"^##\s+画面切片附录\b", note, re.M):
        return note
    return f"{note}\n\n{appendix}" if note else appendix


def _looks_like_shell_command(command: str, explicit: bool = False) -> bool:
    tokens = re.sub(r"\s+", " ", command or "").strip().split(" ")
    if len(tokens) < 2:
        return False
    tool = tokens[0].lower()
    argument = tokens[1].lower().rstrip(".,:;")
    known_subcommands = {
        "docker": {"build", "compose", "exec", "images", "info", "inspect", "login", "logs", "network", "ps", "pull", "push", "restart", "rm", "rmi", "run", "start", "stop", "version", "volume"},
        "podman": {"build", "compose", "exec", "images", "info", "inspect", "login", "logs", "network", "ps", "pull", "push", "restart", "rm", "rmi", "run", "start", "stop", "version", "volume"},
        "pip": {"download", "freeze", "install", "list", "show", "uninstall", "wheel"},
        "pip3": {"download", "freeze", "install", "list", "show", "uninstall", "wheel"},
        "npm": {"ci", "exec", "install", "link", "publish", "run", "start", "test", "uninstall", "update"},
        "pnpm": {"add", "build", "dlx", "exec", "install", "remove", "run", "start", "test", "update"},
        "yarn": {"add", "build", "install", "remove", "run", "start", "test", "upgrade"},
        "conda": {"activate", "create", "deactivate", "env", "install", "list", "remove", "run", "update"},
        "git": {"add", "branch", "checkout", "clone", "commit", "diff", "fetch", "log", "merge", "pull", "push", "rebase", "remote", "restore", "status", "switch"},
    }
    if explicit or argument.startswith("-") or argument.startswith(("http://", "https://")):
        return True
    if tool in known_subcommands:
        return argument in known_subcommands[tool]
    if tool in {"python", "python3"}:
        return argument in {"-m", "-c"} or argument.endswith(".py")
    if tool in {"ffmpeg", "yt-dlp", "curl", "wget", "winget", "brew", "choco"}:
        return True
    return False


def _grid_image_content_items(entries: list[VisionGridEntry]) -> list[dict]:
    items: list[dict] = []
    for original_index, grid in entries:
        window_id = f"W{original_index + 1:03d}"
        path = Path(grid.path)
        if not path.exists():
            items.append({
                "type": "text",
                "text": (
                    f"\u7a97\u53e3 {window_id}\uff08{_format_ts(grid.start)} - {_format_ts(grid.end)}\uff09"
                    f"\u7684\u753b\u9762\u7f51\u683c\u6587\u4ef6\u7f3a\u5931\uff0c\u539f\u59cb\u7d22\u5f15 URL\uff1a{grid.url}\u3002"
                    "\u8bf7\u53ea\u6839\u636e\u5b57\u5e55\u7247\u6bb5\u548c\u753b\u9762\u7d22\u5f15\u5904\u7406\u8fd9\u4e2a\u7a97\u53e3\uff0c\u4e0d\u8981\u7f16\u9020\u753b\u9762\u7ec6\u8282\u3002"
                ),
            })
            continue
        items.append({
            "type": "text",
            "text": (
                f"下面这张画面网格对应窗口 {window_id}："
                f"{_format_ts(grid.start)} - {_format_ts(grid.end)}；"
                f"网格 URL：{grid.url}。请把这张图只用于 {window_id} 的局部摘要。"
            ),
        })
        items.append({"type": "image_url", "image_url": {"url": image_to_data_url(path)}})
    return items


def _operation_tutorial_sections(transcript: TranscriptResult, grids: list[FrameGrid]) -> list[str]:
    segments = [segment for segment in transcript.segments if re.sub(r"\s+", " ", segment.text or "").strip()]
    if not segments:
        segments = [
            TranscriptSegment(start=0.0, end=0.0, text=text)
            for text in _sentences(transcript.full_text, limit=16)
        ]

    interface_pattern = re.compile(
        r"\b(open|click|select|choose|settings?|menu|window|panel|dialog|save|enter|screen|page|tab)\b|"
        r"打开|点击|选择|设置|菜单|窗口|面板|弹窗|保存|输入|页面|选项卡",
        re.I,
    )
    command_pattern = re.compile(
        r"(?:^|[\n`$>]\s*|\b(?:run|execute)\s+)((?:docker|podman|pip|pip3|npm|pnpm|yarn|conda|python|python3|git|ffmpeg|yt-dlp|curl|wget|winget|brew|choco)\s+[^\n`]+)",
        re.I,
    )
    error_pattern = re.compile(
        r"\b(error|failed?|failure|cannot|can't|unable|timeout|denied|not found|troubleshoot)\b|"
        r"错误|失败|报错|异常|无法|超时|拒绝|找不到|排错|故障",
        re.I,
    )

    lines = ["## 操作目标", ""]
    first_step = re.sub(r"\s+", " ", segments[0].text).strip() if segments else ""
    lines.append(f"- {first_step}" if first_step else "- 材料未明确说明操作目标，请先回看开头确认。")

    lines += ["", "## 准备工作", ""]
    lines.append("- 材料未单独说明前置条件；从第一个有时间戳的操作开始，不补写未展示的安装或配置。")

    lines += ["", "## 操作步骤", ""]
    if segments:
        for index, segment in enumerate(segments[:24], start=1):
            text = re.sub(r"\s+", " ", segment.text).strip()
            lines.append(f"{index}. `{_format_ts(segment.start)}` {text}")
    else:
        lines.append("1. 暂无可核对的字幕步骤；请先补充字幕或重新转写。")

    lines += ["", "## 界面变化", ""]
    interface_segments = [segment for segment in segments if interface_pattern.search(segment.text or "")]
    if interface_segments:
        for segment in interface_segments[:12]:
            text = re.sub(r"\s+", " ", segment.text).strip()
            lines.append(f"- `{_format_ts(segment.start)}` {text}")
    elif grids:
        for index, grid in enumerate(grids[:8], start=1):
            lines.append(
                f"- W{index:03d} `{_format_ts(grid.start)} - {_format_ts(grid.end)}`："
                f"字幕未说明界面状态；只按截图复核，不推断未展示的点击结果。"
            )
    else:
        lines.append("- 没有可核对的界面变化证据。")

    command_matches: list[str] = []
    for segment in segments:
        for match in command_pattern.finditer(segment.text or ""):
            command = re.sub(r"\s+", " ", match.group(1)).strip(" .")
            explicit = bool(re.match(r"^\s*(?:run|execute)\s+", match.group(0), re.I)) or bool(re.match(r"^\s*[$>`]", match.group(0)))
            if command and _looks_like_shell_command(command, explicit=explicit) and command not in command_matches:
                command_matches.append(command)
    lines += ["", "## 命令与参数", ""]
    if command_matches:
        lines.extend(f"- `{command}`" for command in command_matches[:16])
    else:
        lines.append("- 材料中未出现可逐字核对的完整命令；不要把口头操作描述改写成可执行命令。")

    error_segments = [segment for segment in segments if error_pattern.search(segment.text or "")]
    lines += ["", "## 常见错误与处理", ""]
    if error_segments:
        for segment in error_segments[:12]:
            text = re.sub(r"\s+", " ", segment.text).strip()
            lines.append(f"- `{_format_ts(segment.start)}` {text}")
    else:
        lines.append("- 材料没有展示可核对的报错或处理结果；不补写通用故障。")

    lines += ["", "## 完成检查", ""]
    lines.append("- 按上面的时间点回看原视频，逐项确认界面状态、命令文本和最终结果；未被画面或字幕证实的步骤保持为待确认。")
    return lines


def _local_goal_note(
    title: str,
    transcript: TranscriptResult,
    grids: list[FrameGrid],
    page_url: str,
    options: TaskOptions,
    page_context: str,
) -> str:
    goal = learning_goal(options)
    goal_labels = {"deep": "深入理解", "quick": "快速回顾", "exam": "备考自测"}
    example_count, question_count = _depth_counts(options)
    key_sentences = _sentences(transcript.full_text, limit=max(8, question_count))
    windows = build_visual_windows(transcript, grids)
    lines = [f"# {title or '学习笔记'}", ""]
    if page_url:
        lines += [f"来源：{page_url}", ""]
    if transcript.warning:
        lines += [f"> 转写提示：{transcript.warning}", ""]
    use_case = str(options.note_style or "").strip().lower().replace("_", "-")
    if use_case == "operation-tutorial":
        lines.extend(_operation_tutorial_sections(transcript, grids))
        return ensure_visual_appendix("\n".join(lines).rstrip() + "\n", transcript, grids)

    lines.extend(_learning_context_lines(title, transcript, windows, page_url, page_context))
    depth_labels = {"brief": "简洁", "standard": "标准", "deep": "详细"}
    depth_label = depth_labels.get(str(options.summary_depth or "standard").strip().lower(), "标准")
    lines += [f"> 整理方式：{goal_labels[goal]} · {depth_label}", ""]
    template = str(options.note_template or "standard").strip().lower().replace("_", "-")
    if use_case not in {"classroom-review", "exam-review", "quick-summary"} and (use_case != "study" or template != "standard"):
        lines += [
            "## 本篇整理重点",
            "",
            f"- 内容重点：{note_style_instruction(options)}",
            f"- 笔记格式：{note_template_instruction(options)}",
            "",
        ]

    if goal == "quick":
        lines += ["## 一页速览", ""]
        for item in key_sentences[: max(3, question_count)]:
            lines.append(f"- {item}")
        lines += ["", "## 关键结论", ""]
        for item in key_sentences[:question_count]:
            lines.append(f"- {item}")
        lines += ["", "## 回看定位", ""]
        lines.extend(_timeline_lines(transcript, grids)[: max(2, question_count)])
        lines += ["", "## 下一步复习", ""]
        for index in range(question_count):
            topic = key_sentences[index % len(key_sentences)] if key_sentences else "本节关键结论"
            lines.append(f"{index + 1}. 用一句话复述：{topic}")
    elif goal == "deep":
        topics = _context_topic_lines(title, transcript, limit=max(3, example_count))
        lines += ["## 知识地图", ""]
        lines.extend(f"- {item}" for item in topics)
        lines += ["", "## 概念精讲", ""]
        for item in key_sentences[: max(4, question_count)]:
            lines.append(f"- {item}")
        lines += ["", "## 证据与应用", ""]
        for index in range(example_count):
            topic = key_sentences[index % len(key_sentences)] if key_sentences else "本节概念"
            lines.append(f"- 应用练习 {index + 1}：解释“{topic}”成立的前提，并给出一个适用场景。")
        lines += ["", "## 概念联系、边界与迁移", ""]
        lines.append("- 对照上下文检查各概念的前提、因果关系和适用边界；转写未明确的关系保持为待确认项。")
        lines += ["", "## 理解检验", ""]
        for index in range(question_count):
            topic = key_sentences[index % len(key_sentences)] if key_sentences else "本节核心概念"
            lines.append(f"{index + 1}. 如何解释并应用：{topic}")
    else:
        lines += ["## 考点清单", ""]
        for item in key_sentences[: max(4, question_count)]:
            lines.append(f"- {item}")
        lines += ["", "## 闭卷自测题", ""]
        for index in range(question_count):
            topic = key_sentences[index % len(key_sentences)] if key_sentences else "本节核心考点"
            lines.append(f"{index + 1}. 请准确说明：{topic}")
        lines += ["", "## 答案与评分点", ""]
        for index in range(question_count):
            topic = key_sentences[index % len(key_sentences)] if key_sentences else "需结合原视频确认"
            lines.append(f"{index + 1}. {topic}")
        lines += ["", "## 题型 / 陷阱复盘", ""]
        lines.append("- 作答时区分原始材料明确给出的结论与需要自行推导的内容，并核对条件和术语。")

    return ensure_visual_appendix("\n".join(lines).rstrip() + "\n", transcript, grids)


def local_markdown_note(title: str, transcript: TranscriptResult, grids: list[FrameGrid], page_url: str = "", options: TaskOptions | None = None, page_context: str = "") -> str:
    lines = [f"# {title or '学习笔记'}", ""]
    if page_url:
        lines += [f"来源：{page_url}", ""]
    if transcript.warning:
        lines += [f"> 转写提示：{transcript.warning}", ""]

    resolved_options = options or TaskOptions()
    if learning_goal(resolved_options) != "auto":
        return _local_goal_note(title, transcript, grids, page_url, resolved_options, page_context)

    key_sentences = _sentences(transcript.full_text, limit=6)
    windows = build_visual_windows(transcript, grids)

    lines.extend(_learning_context_lines(title, transcript, windows, page_url, page_context))
    lines += ["> 整理方式：智能整理 · 标准", ""]

    lines += ["## 课程主题", ""]
    if transcript.full_text and "未安装 faster-whisper" not in transcript.full_text:
        preview = transcript.full_text.replace("\n", " ")[:320]
        lines += [f"{preview}{'...' if len(transcript.full_text) > 320 else ''}", ""]
    else:
        lines += ["根据可下载视频画面和可用文本生成初步笔记。", ""]

    lines += ["## 时间轴重点", ""]
    lines.extend(_timeline_lines(transcript, grids))
    lines.append("")

    lines += ["## 学习路线", ""]
    lines.extend(_study_route_lines(transcript, windows))
    lines.append("")

    lines += ["## 分段图文摘要", ""]
    lines.extend(_window_summary_lines(transcript, grids))
    lines.append("")

    if windows:
        lines += ["## 视觉切片学习卡", ""]
        lines.extend(_window_learning_card_lines(windows))

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
    page_context: str = "",
    events: list[dict] | None = None,
) -> tuple[str, str] | None:
    api_key = options.llm_api_key or LLM_API_KEY
    if not api_key:
        _record_llm_event(events, "configuration", "missing_api_key")
        return None

    try:
        from openai import OpenAI
    except Exception as exc:
        _record_llm_event(events, "client_import", "missing_openai_sdk", exc)
        return None

    model = options.llm_model or LLM_MODEL
    page_context_prompt = _page_context_prompt(page_context)
    base_url = options.llm_base_url or LLM_BASE_URL
    provider_kwargs = chat_completion_provider_kwargs(base_url)
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
    except Exception as exc:
        _record_llm_event(events, "client_init", "client_init_failed", exc, model=model)
        return None

    if grids and llm_model_supports_vision(base_url, model):
        partials = []
        failed_batches = 0
        batches = _grid_batches(grids)
        for index, batch in enumerate(batches, start=1):
            content: list[dict] = [
                {
                    "type": "text",
                    "text": (
                        "你是严谨的课程学习笔记助手。下面是一批视频画面网格和对应字幕。"
                        "请先做局部图文总结，不要写完整总笔记。\n"
                        "每个窗口只需包含时间范围、画面可见信息和字幕重点；操作、PPT、代码、公式或例题线索仅在确实出现时记录。\n"
                        "不要为了统一格式补写易错点、例题或其他未出现的内容。\n"
                        f"标题：{title}\n来源：{page_url}\n批次：{index}\n\n"
                        f"{page_context_prompt}\n"
                        f"{_grid_window_prompt(transcript, batch)}"
                    ),
                }
            ]
            content.extend(_grid_image_content_items(batch))
            if not any(item.get("type") == "image_url" for item in content):
                continue
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    **provider_kwargs,
                )
                partial = response.choices[0].message.content or ""
                if partial.strip():
                    partials.append(partial.strip())
            except Exception as exc:
                failed_batches += 1
                _record_llm_event(events, "vision_batch", "api_error", exc, batch=index, model=model)
                continue

        if partials:
            merge_prompt = "\n\n".join(f"### 局部图文摘要 {idx}\n{partial}" for idx, partial in enumerate(partials, start=1))
            if failed_batches:
                merge_prompt = (
                    "### Vision batch warning\n"
                    f"{failed_batches} vision batch(es) failed. Merge the successful visual summaries, "
                    "use the full transcript and frame index to preserve coverage, and state any uncertainty.\n\n"
                    f"{merge_prompt}"
                )
            frame_index = "\n".join(_grid_index_lines(grids))
            if page_context_prompt:
                frame_index = f"{page_context_prompt}\n{frame_index}"
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "你是严谨的课程学习笔记助手。请把下面所有局部图文摘要和字幕合并成一份完整 Markdown 学习笔记。"
                                "必须覆盖所有时间窗口，不要只总结开头。\n\n"
                                "画面索引必须保留 W 编号、时间范围和画面网格 URL，方便用户回看截图。\n"
                                f"笔记风格：{options.note_style}；笔记模板：{options.note_template}；详略程度：{options.summary_depth}。\n"
                                f"{note_generation_contract(options)}\n"
                                f"用途要求：{note_style_instruction(options)}\n"
                                f"版式要求：{note_template_instruction(options)}\n"
                                "不要在成品笔记中复述模型提示、内部参数、风格名称、深度约束或兼容说明；直接输出读者需要的正文。\n"
                                f"标题：{title}\n来源：{page_url}\n\n"
                                f"画面索引清单：\n{frame_index}\n\n"
                                f"完整字幕节选：\n{transcript.full_text[:60000]}\n\n"
                                f"{merge_prompt}"
                            ),
                        }
                    ],
                    **provider_kwargs,
                )
                generated = response.choices[0].message.content or ""
                note = ensure_visual_appendix(generated, transcript, grids) or ""
                return (note, "vision-llm") if note else None
            except Exception as exc:
                _record_llm_event(events, "vision_merge", "api_error", exc, model=model)
                return None

    text_transcript_prompt = transcript.full_text[:60000]
    original_transcript_full_text = transcript.full_text
    if page_context_prompt:
        text_transcript_prompt = f"{page_context_prompt}\n{text_transcript_prompt}"
        transcript.full_text = text_transcript_prompt
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "你是严谨的课程学习笔记助手。请结合字幕输出 Markdown。\n"
                f"笔记风格：{options.note_style}；笔记模板：{options.note_template}；详略程度：{options.summary_depth}。\n"
                f"{note_generation_contract(options)}\n"
                f"用途要求：{note_style_instruction(options)}\n"
                f"版式要求：{note_template_instruction(options)}\n"
                "不要在成品笔记中复述模型提示、内部参数、风格名称、深度约束或兼容说明；直接输出读者需要的正文。\n"
                f"标题：{title}\n来源：{page_url}\n\n字幕：\n{transcript.full_text[:60000]}"
            ),
        }
    ]
    transcript.full_text = original_transcript_full_text

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            **provider_kwargs,
        )
        generated = response.choices[0].message.content or ""
        note = ensure_visual_appendix(generated, transcript, grids) or ""
        return (note, "text-llm") if note else None
    except Exception as exc:
        _record_llm_event(events, "text_summary", "api_error", exc, model=model)
        return None


def summarize_with_diagnostics(
    title: str,
    transcript: TranscriptResult,
    grids: list[FrameGrid],
    options: TaskOptions,
    page_url: str = "",
    page_context: str = "",
) -> tuple[str, str, str]:
    note, source, warning, _events = summarize_with_diagnostics_audit(title, transcript, grids, options, page_url, page_context)
    return note, source, warning


def summarize_with_diagnostics_audit(
    title: str,
    transcript: TranscriptResult,
    grids: list[FrameGrid],
    options: TaskOptions,
    page_url: str = "",
    page_context: str = "",
) -> tuple[str, str, str, list[dict]]:
    events: list[dict] = []
    api_key = options.llm_api_key or LLM_API_KEY
    if not api_key:
        events.append({"stage": "configuration", "code": "missing_api_key"})
        return (
            local_markdown_note(title, transcript, grids, page_url, options, page_context),
            "local-template",
            "未配置 OpenAI-compatible API Key，已使用本地画面索引模板生成笔记。",
            events,
        )
    generated = summarize_with_llm(title, transcript, grids, options, page_url, page_context, events)
    if generated:
        note, source = generated
        warning = ""
        failed_vision_batches = [event for event in events if event.get("stage") == "vision_batch"]
        if source == "vision-llm" and failed_vision_batches:
            warning = llm_warning_from_events(
                options,
                failed_vision_batches,
                f"{len(failed_vision_batches)} vision batch(es) failed; merged successful visual summaries.",
            )
        return note, source, warning, events
    fallback_warning = "Vision/LLM summary failed or unavailable; using local frame-index template."
    if events:
        return (
            local_markdown_note(title, transcript, grids, page_url, options, page_context),
            "local-template",
            llm_warning_from_events(options, events, fallback_warning),
            events,
        )
    events.append({"stage": "summary", "code": "llm_unavailable"})
    return (
        local_markdown_note(title, transcript, grids, page_url, options, page_context),
        "local-template",
        "视觉/LLM 总结调用失败或不可用，已降级为本地画面索引模板。",
        events,
    )


def summarize(title: str, transcript: TranscriptResult, grids: list[FrameGrid], options: TaskOptions, page_url: str = "", page_context: str = "") -> str:
    return summarize_with_diagnostics(title, transcript, grids, options, page_url, page_context)[0]


def _split_page_text_sections(text: str) -> tuple[str, str]:
    parts = re.split(r"\n+\s*---\s*浏览器字幕\s*---\s*\n+", text or "", maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return (text or "").strip(), ""


def _clean_outline_lines(text: str, limit: int = 8) -> list[str]:
    lines = []
    seen = set()
    for raw in re.split(r"[\r\n]+", text or ""):
        cleaned = re.sub(r"\s+", " ", raw).strip(" -•\t")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        if len(cleaned) > 120:
            cleaned = cleaned[:120].rstrip() + "..."
        lines.append(cleaned)
        if len(lines) >= limit:
            break
    if lines:
        return lines
    return _sentences(text, limit=limit)


def _page_text_line_is_player_ui(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text or "").strip(" -•\t,，。:：;；!?！？()（）[]【】")
    if not normalized:
        return False
    if normalized in PAGE_UI_EXACT_TEXTS:
        return True
    marker_hits = sum(marker in normalized for marker in PAGE_UI_MARKERS)
    return marker_hits >= 3


def _clean_page_context(text: str) -> str:
    lines = []
    for raw in re.split(r"[\r\n]+", text or ""):
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned and not _page_text_line_is_player_ui(cleaned):
            lines.append(cleaned)
    return "\n".join(lines)


def _bullet_lines(items: list[str], fallback: str) -> list[str]:
    if not items:
        return [f"- {fallback}"]
    return [f"- {item}" for item in items]


def _page_text_provenance_notice(has_browser_subtitles: bool) -> str:
    inputs = "页面 DOM 文本和未经媒体校验的浏览器字幕线索" if has_browser_subtitles else "页面 DOM 文本"
    return (
        f"> 来源质量：低。本笔记仅基于{inputs}；未取得视频文件、音轨或画面证据，"
        "不能视为视频字幕或完整视频笔记。"
    )


def _summarize_page_text_with_llm(
    title: str,
    page_url: str,
    page_body: str,
    subtitle_body: str,
    options: TaskOptions,
) -> str | None:
    api_key = options.llm_api_key or LLM_API_KEY
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    base_url = options.llm_base_url or LLM_BASE_URL
    model = options.llm_model or LLM_MODEL
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": (
                    "你是严谨的学习资料整理助手。以下输入不是已验证的视频转写。"
                    "页面 DOM 文本可能包含导航、按钮、播放器控件、评论或其他界面字符串；"
                    "浏览器字幕线索也可能不完整。只总结输入中明确出现的内容，不得称其为视频字幕，"
                    "不得声称已观看、听取或完整总结视频，不得补写视频中未被证据支持的细节。\n"
                    "请输出 Markdown，并在开头保留来源限制说明。\n"
                    f"笔记风格：{options.note_style}；笔记模板：{options.note_template}；详略程度：{options.summary_depth}。\n"
                    f"标题：{title}\n页面 URL：{page_url}\n\n"
                    f"页面 DOM 文本（低可信上下文）：\n{page_body[:50000] or '(empty)'}\n\n"
                    f"浏览器字幕线索（未经媒体校验）：\n{subtitle_body[:10000] or '(empty)'}"
                ),
            }],
            **chat_completion_provider_kwargs(base_url),
        )
    except Exception:
        return None
    generated = (response.choices[0].message.content or "").strip()
    return generated or None


def summarize_page_text_with_diagnostics(title: str, page_url: str, page_text: str, options: TaskOptions) -> tuple[str, str, str]:
    text = (page_text or "").strip()
    page_body, subtitle_body = _split_page_text_sections(text)
    page_body = _clean_page_context(page_body)
    notice = _page_text_provenance_notice(bool(subtitle_body))
    generated = _summarize_page_text_with_llm(title, page_url, page_body, subtitle_body, options)
    if generated:
        note = generated if notice in generated else f"{notice}\n\n{generated}"
        return note, "page-text-llm", "缺少可信视频证据；结果仅基于页面文本和未经媒体校验的浏览器字幕线索。"
    page_points = _clean_outline_lines(page_body, limit=8)
    subtitle_points = _clean_outline_lines(subtitle_body, limit=8)
    all_points = page_points or subtitle_points
    clean_combined_text = "\n\n".join(part for part in (page_body, subtitle_body) if part)
    excerpt = clean_combined_text[:1200] + ("..." if len(clean_combined_text) > 1200 else "")
    note = "\n".join([
        f"# {title or '当前页面文本总结'}",
        "",
        f"来源：{page_url}",
        "",
        notice,
        "",
        "## 页面要点",
        "",
        *_bullet_lines(page_points, "当前页面没有提取到明确章节文本，可结合浏览器字幕或原页面继续确认。"),
        "",
        "## 浏览器字幕线索",
        "",
        *_bullet_lines(subtitle_points, "没有同步到浏览器字幕；如果页面正在播放课程，可回到扩展侧栏重新检测或改用视频直取/本地上传。"),
        "",
        "## 兜底学习笔记",
        "",
        f"- 主题判断：{all_points[0] if all_points else title or '当前页面内容'}",
        "- 回看目标：直取视频不可用时，先用页面标题、章节文本和浏览器字幕建立知识框架，再用原页面或本地视频补齐画面演示。",
        "- 复习动作：把页面要点整理成 3-5 条概念卡片；如果后续拿到视频，再用画面切片核对 PPT、板书、代码或操作步骤。",
        "",
        "## 页面摘录",
        "",
        excerpt or "当前页面没有提取到可用文本。",
        "",
        "## 复习问题",
        "",
        "1. 本页标题、章节文本和字幕共同指向的核心概念是什么？",
        "2. 哪些步骤只靠文本还不够，需要回到视频画面确认 PPT、板书、代码或界面操作？",
        "3. 哪些术语、公式、例题或演示流程应该做成卡片复习？",
        "4. 如果稍后改用本地视频或直取成功，哪些时间段/章节最值得优先切片复核？",
        "",
    ])
    return note, "local-template", "缺少可信视频证据；已降级为本地页面文本模板，不能视为视频字幕或完整视频笔记。"


def summarize_page_text(title: str, page_url: str, page_text: str, options: TaskOptions) -> str:
    return summarize_page_text_with_diagnostics(title, page_url, page_text, options)[0]
