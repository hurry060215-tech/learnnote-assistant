"""Backward-compatible task-QA history serialization with injected storage.

The caller owns the task directory, file name, clock and identifiers. This
module keeps the version-1 history schema/export text and never chooses paths.
"""
from __future__ import annotations

from collections.abc import Callable

from .models import TaskRecord, TaskQuestionRequest
from .qa_evidence import clip_text as _clip_text

def read_task_qa_history(task_id: str, *, read_json: Callable, filename: str, sanitize_citations: Callable) -> list[dict]:
    data = read_json(task_id, filename, {"items": []})
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items", [])
    else:
        items = []
    sanitized_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sanitized = dict(item)
        citations = item.get("citations") if isinstance(item.get("citations"), list) else []
        trusted_citations = sanitize_citations(citations)
        # A historical answer whose entire evidence trail is player chrome or
        # danmaku should not remain visible after the evidence is rejected.
        if citations and not trusted_citations:
            continue
        sanitized["citations"] = trusted_citations
        sanitized_items.append(sanitized)
    return sanitized_items


def append_task_qa_history(task: TaskRecord, request: TaskQuestionRequest, result: dict, *, read_history: Callable, write_json: Callable, filename: str, sanitize_citations: Callable, new_id: Callable, now: Callable) -> tuple[dict, list[dict]]:
    history = read_history(task.id)
    item = {
        "id": new_id(),
        "created_at": now(),
        "skill_id": request.skill_id,
        "question": _clip_text(request.question, 1000),
        "answer": str(result.get("answer") or ""),
        "source": str(result.get("source") or ""),
        "warning": _clip_text(str(result.get("warning") or ""), 500),
        "provider": str(result.get("provider") or ""),
        "model": str(result.get("model") or ""),
        "citations": [
            {
                "source": _clip_text(str(citation.get("source") or ""), 120),
                "label": _clip_text(str(citation.get("label") or ""), 120),
                "text": _clip_text(str(citation.get("text") or ""), 800),
                "window_id": _clip_text(str(citation.get("window_id") or ""), 80),
                "time_range": _clip_text(str(citation.get("time_range") or ""), 80),
                "grid_url": _clip_text(str(citation.get("grid_url") or ""), 500),
                "target_tab": _clip_text(str(citation.get("target_tab") or ""), 40),
                "source_kind": _clip_text(str(citation.get("source_kind") or "task"), 40),
                "source_id": _clip_text(str(citation.get("source_id") or task.id), 128),
                "start": citation.get("start") if isinstance(citation.get("start"), (int, float)) else None,
                "end": citation.get("end") if isinstance(citation.get("end"), (int, float)) else None,
            }
            for citation in sanitize_citations(result.get("citations") or [])[:12]
            if isinstance(citation, dict)
        ],
    }
    history.append(item)
    write_json(task.id, filename, {"schema_version": 1, "items": history})
    return item, history


def render_qa_history_markdown(task: TaskRecord, history: list[dict] | None = None, *, read_history: Callable) -> str:
    items = history if history is not None else read_history(task.id)
    lines = [
        "# LearnNote 问答记录",
        "",
        f"- 任务：{task.title}",
        f"- ID：{task.id}",
        f"- 页面：{task.page_url or '-'}",
        f"- 问答数：{len(items)}",
        "",
    ]
    if not items:
        lines.append("暂无问答记录。")
        return "\n".join(lines)
    for index, item in enumerate(items, start=1):
        lines.extend([
            f"## Q{index}. {item.get('question') or '-'}",
            "",
            f"- 时间：{item.get('created_at') or '-'}",
            f"- 来源：{item.get('source') or '-'}",
            f"- 模型：{item.get('provider') or '-'} / {item.get('model') or '-'}",
        ])
        if item.get("warning"):
            lines.append(f"- 提示：{item.get('warning')}")
        lines.extend(["", str(item.get("answer") or "-"), ""])
        citations = item.get("citations") if isinstance(item.get("citations"), list) else []
        if citations:
            lines.append("### 证据")
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                label = citation.get("label") or citation.get("source") or "证据"
                text = citation.get("text") or ""
                meta = " · ".join(str(citation.get(key) or "") for key in ("window_id", "time_range") if citation.get(key))
                grid = citation.get("grid_url") or ""
                suffix = f"（{meta}）" if meta else ""
                lines.append(f"- **{label}**{suffix}：{text}")
                if grid:
                    lines.append(f"  - 画面网格：{grid}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"
