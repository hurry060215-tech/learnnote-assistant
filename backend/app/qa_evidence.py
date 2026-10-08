"""Pure task-QA citation selection, text projection and prompt formatting.

Inputs/outputs retain the existing citation dictionaries. Runtime trust and
formatting callbacks are explicit so this layer imports neither API nor pipeline.
No model calls, file access, history mutation or persistence occur here.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from .models import TaskRecord

def clip_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def question_terms(question: str) -> set[str]:
    text = str(question or "").lower()
    focus_text = re.split(r"(?:不要|别再?|无需|不必|避免|排除|不讨论)", text, maxsplit=1)[0].strip() or text
    terms = {item for item in re.findall(r"[a-z0-9_]{2,}", focus_text, re.I) if item.strip()}
    for phrase in re.findall(r"[\u4e00-\u9fff]+", focus_text):
        if len(phrase) <= 8:
            terms.add(phrase)
        for size in range(2, min(4, len(phrase)) + 1):
            terms.update(phrase[index:index + size] for index in range(len(phrase) - size + 1))
    if re.search(r"原话|说话|讲了|讲的|字幕|转写|台词|transcript", text):
        terms.add("__source_transcript__")
    if re.search(r"画面|截图|视觉|演示|操作|界面|切片|ppt|slide", text):
        terms.add("__source_visual__")
    terms.difference_update({
        "什么", "怎么", "如何", "一下", "这个", "那个", "哪些", "是否", "可以", "请问",
        "视频", "回答", "根据", "只根", "只根据", "介绍", "说话人",
        "the", "and", "what", "how", "this", "that", "with", "from",
    })
    if not terms:
        terms.update(char for char in focus_text if char.strip())
    return terms


def score_excerpt(text: str, terms: set[str]) -> int:
    lowered = str(text or "").lower()
    return sum(lowered.count(term.lower()) * min(4, max(1, len(term))) for term in terms)


def strict_transcript_evidence_requested(question: str) -> bool:
    text = re.sub(r"\s+", "", str(question or "").lower())
    transcript_source = r"(?:字幕|转写|原话|台词|transcript)"
    return bool(
        re.search(rf"(?:只|仅|必须|务必).{{0,8}}{transcript_source}", text)
        or re.search(rf"{transcript_source}(?:证据|为准|回答)", text)
        or (
            re.search(transcript_source, text)
            and re.search(r"不要(?:使用|依据|根据|看|用)?.{0,4}(?:笔记|总结|画面)", text)
        )
    )


def sanitize_note_markdown_for_qa(note: str) -> str:
    """Remove legacy browser-page context that was never course evidence."""
    lines = str(note or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(
            r"^\s*-\s*Page context:\s*captured from the current browser page\b",
            line,
            flags=re.I,
        ):
            index += 1
            while index < len(lines) and re.match(r"^(?: {2,}|\t)\S", lines[index]):
                index += 1
            continue
        cleaned.append(line)
        index += 1
    return "\n".join(cleaned)


def note_evidence_chunks(note: str, limit: int = 80, source_id: str = "") -> list[dict]:
    chunks: list[dict] = []
    heading = ""
    clean_note = sanitize_note_markdown_for_qa(note)
    for raw_block in re.split(r"\n{2,}|(?=^#{1,6}\s)", clean_note, flags=re.M):
        block = raw_block.strip()
        if not block:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+)", block)
        if heading_match:
            heading = clip_text(heading_match.group(1), 100)
            if "\n" not in block:
                continue
        text = clip_text(block, 900)
        if len(text) < 2:
            continue
        chunks.append({
            "source": "note",
            "source_kind": "task" if source_id else "",
            "source_id": source_id,
            "label": heading or f"笔记片段 {len(chunks) + 1}",
            "text": text,
            "target_tab": "note",
        })
        if len(chunks) >= limit:
            break
    return chunks


def is_broad_summary_question(question: str) -> bool:
    text = re.sub(r"\s+", "", str(question or "").lower())
    return bool(re.search(
        r"总结|概括|核心内容|主要内容|主要讲|讲了(?:什么|啥)|内容是什么|"
        r"summar(?:y|ize)|overview|keypoints|mainpoints",
        text,
    ))


def is_follow_up_question(question: str) -> bool:
    text = re.sub(r"\s+", "", str(question or "").lower())
    return bool(re.search(
        r"^(那|那么|所以|然后|还有|另外|刚才|前面|上面)|"
        r"(它|这个|那个|上述|前述|前面提到|刚才提到|继续说|展开说|为什么必须有它)",
        text,
    ))


def qa_history_terms(history: list[dict]) -> set[str]:
    terms: set[str] = set()
    for item in history:
        terms.update(question_terms(str(item.get("question") or "")))
        for citation in item.get("citations") or []:
            if isinstance(citation, dict):
                terms.update(question_terms(str(citation.get("text") or "")))
    return terms


def qa_history_messages(history: list[dict]) -> list[dict]:
    messages: list[dict] = []
    for item in history[-4:]:
        question = clip_text(str(item.get("question") or ""), 600)
        if question:
            messages.append({"role": "user", "content": question})
    return messages


def qa_evidence_prompt(citations: list[dict]) -> str:
    lines = []
    for index, citation in enumerate(citations, start=1):
        metadata = " · ".join(
            str(citation.get(key) or "") for key in ("window_id", "time_range") if citation.get(key)
        )
        suffix = f" ({metadata})" if metadata else ""
        lines.append(
            f"[E{index}] {citation.get('label') or citation.get('source')}{suffix}: "
            f"{clip_text(str(citation.get('text') or ''), 900)}"
        )
    return "\n".join(lines)


def local_task_answer(question: str, citations: list[dict]) -> tuple[str, list[dict]]:
    if not citations:
        return "现有笔记、字幕和画面索引中没有找到与这个问题相关的内容。", []
    excerpts = []
    for citation in citations[:3]:
        text = clip_text(str(citation.get("text") or ""), 360)
        if text:
            excerpts.append(f"- {text}")
    if not excerpts:
        return "现有证据不足，暂时无法回答这个问题。", citations
    return "根据现有内容：\n" + "\n".join(excerpts), citations


def qa_history_preview(history: list[dict], limit: int = 5) -> list[dict]:
    preview = []
    for item in history[-limit:]:
        preview.append({
            "id": item.get("id", ""),
            "created_at": item.get("created_at", ""),
            "question": clip_text(str(item.get("question") or ""), 180),
            "answer_excerpt": clip_text(str(item.get("answer") or ""), 420),
            "source": item.get("source", ""),
            "warning": clip_text(str(item.get("warning") or ""), 220),
            "provider": item.get("provider", ""),
            "model": item.get("model", ""),
            "citation_count": len(item.get("citations") or []) if isinstance(item.get("citations"), list) else 0,
        })
    return list(reversed(preview))


def task_qa_suggestions(task: TaskRecord, limit: int = 7, *, format_timestamp: Callable) -> list[dict]:
    suggestions: list[dict] = []
    seen: set[str] = set()

    def add(label: str, question: str, source: str) -> None:
        normalized = " ".join(question.split())
        if not normalized or normalized in seen or len(suggestions) >= limit:
            return
        seen.add(normalized)
        suggestions.append({"label": label, "question": normalized, "source": source})

    has_note = bool(task.note_path)
    has_transcript = bool(task.transcript_path or task.browser_subtitles)
    has_visual = bool(task.visual_index_path or task.visual_windows or task.frame_grids)

    if has_note:
        add("核心概念", "这节课最重要的 3 个概念是什么？请用适合复习的方式解释。", "note")
        add("时间轴重点", "按时间顺序列出这节课的重点、例题和操作步骤。", "note")
        add("易错点", "这节课有哪些容易混淆或考试容易错的地方？", "note")
    if has_transcript:
        add("字幕梳理", "根据字幕提取老师反复强调的关键词，并说明它们之间的关系。", "transcript")
        add("自测题", "基于这节课生成 5 道复习自测题，并附简短答案。", "transcript")
    if has_visual:
        add("画面线索", "结合画面索引，哪些 PPT、代码或演示步骤最值得回看？", "visual")
        first_window = task.visual_windows[0] if task.visual_windows else None
        if first_window:
            label = first_window.id or f"W{first_window.index + 1:03d}"
            add(
                label,
                f"请解释 {label}（{format_timestamp(first_window.start)}-{format_timestamp(first_window.end)}）这一段画面和字幕对应的学习重点。",
                "visual",
            )
    if not suggestions:
        add("页面文本", "如果当前任务没有视频结果，请先总结当前页面文本的主要内容。", "page")
    return suggestions


def citation_is_trusted(citation: dict, *, is_player_ui: Callable[[str], bool]) -> bool:
    if not isinstance(citation, dict):
        return False
    text = clip_text(str(citation.get("text") or ""), 1800)
    if not text:
        return False
    return not is_player_ui(text)


def sanitize_citations(citations: list[dict], *, is_trusted: Callable[[dict], bool]) -> list[dict]:
    return [citation for citation in citations if is_trusted(citation)]


def transcript_window_chunks(
    segments: list[dict],
    window_seconds: int = 120,
    step_seconds: int = 60,
    task_id: str = "",
    *,
    is_player_ui: Callable[[str], bool],
    safe_seconds: Callable = float,
    format_timestamp: Callable,
) -> list[dict]:
    valid_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = clip_text(str(segment.get("text") or ""), 700)
        if not text or is_player_ui(text):
            continue
        valid_segments.append({
            "start": safe_seconds(segment.get("start")),
            "end": safe_seconds(segment.get("end")),
            "text": text,
        })
    if not valid_segments:
        return []

    from .transcript_passages import caption_passages
    chunks = []
    for members in caption_passages(valid_segments, max_seconds=window_seconds):
        start_seconds = members[0]["start"]
        end_seconds = max(item["end"] for item in members)
        start, end = format_timestamp(start_seconds), format_timestamp(end_seconds)
        chunks.append({"source": "transcript", "source_kind": "task", "granularity": "window", "segmentation": "caption_boundaries",
            "source_id": task_id,
            "label": f"字幕片段 {start}-{end}", "text": " ".join(item["text"] for item in members),
            "start": start_seconds, "end": end_seconds, "time_range": f"{start}-{end}", "target_tab": "transcript"})
    return chunks


def rank_citations_for_question(
    citations: list[dict],
    terms: set[str],
    related_terms: set[str] | None = None,
    limit: int = 6,
    *,
    sanitize_citations: Callable[[list[dict]], list[dict]],
) -> list[dict]:
    ranked = []
    related_terms = related_terms or set()
    citations = sanitize_citations(citations)
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            continue
        text = " ".join([
            str(citation.get("label") or ""),
            str(citation.get("text") or ""),
            str(citation.get("window_id") or ""),
        ])
        current_score = score_excerpt(text, terms)
        history_score = score_excerpt(text, related_terms)
        score = current_score * 6 + history_score
        source = str(citation.get("source") or "")
        if "__source_transcript__" in terms and source == "transcript":
            score += 10000
        if "__source_visual__" in terms and source.startswith("visual"):
            score += 10000
        ranked.append((score, -index, citation))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top_score = ranked[0][0] if ranked else 0
    relevance_floor = max(1, int(top_score * 0.2))
    relevant = [citation for score, _index, citation in ranked if score >= relevance_floor][:limit]
    if relevant:
        if "__source_transcript__" in terms:
            windows = sorted(
                (item for item in citations if item.get("source") == "transcript" and item.get("granularity") == "window"),
                key=lambda item: float(item.get("start") or 0),
            )
            expanded: list[dict] = []
            seen_ids: set[int] = set()
            for citation in relevant:
                start = float(citation.get("start") or 0)
                following = [item for item in windows if start < float(item.get("start") or 0) <= start + 120][:2]
                for item in (citation, *following):
                    if not item or id(item) in seen_ids:
                        continue
                    expanded.append(item)
                    seen_ids.add(id(item))
                    if len(expanded) >= limit:
                        return expanded
            if expanded:
                return expanded
        return relevant

    # Broad requests such as “总结一下” still need a small, source-diverse sample.
    fallback: list[dict] = []
    seen_sources: set[str] = set()
    for _score, _index, citation in ranked:
        source = str(citation.get("source") or "")
        if source in seen_sources and len(fallback) < 3:
            continue
        fallback.append(citation)
        seen_sources.add(source)
        if len(fallback) >= min(3, limit):
            break
    return fallback


def summary_citations(citations: list[dict], limit: int = 6, *, sanitize_citations: Callable, rank_citations: Callable) -> list[dict]:
    """Prefer non-overlapping transcript windows spanning the full timeline."""
    trusted = sanitize_citations(citations)
    windows = sorted(
        (
            item for item in trusted
            if item.get("source") == "transcript" and item.get("granularity") == "window"
        ),
        key=lambda item: float(item.get("start") or 0),
    )
    selected: list[dict] = []
    last_end = -1.0
    for item in windows:
        start = float(item.get("start") or 0)
        if selected and start < last_end:
            continue
        selected.append(item)
        last_end = float(item.get("end") or start)
        if len(selected) >= limit:
            return selected
    if selected:
        selected_ids = {id(item) for item in selected}
        for item in windows:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
        return sorted(selected, key=lambda item: float(item.get("start") or 0))
    return rank_citations(trusted, set(), limit=limit)
