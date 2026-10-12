"""Read the selected saved edition's actual headings without a model request."""
from __future__ import annotations

import re
from fastapi import HTTPException

from .document_exports import _blocks, _clean_inline_markdown
from .note_document import strip_note_frontmatter


def read_outline(kind: str, source_id: str, revision: str = "") -> dict:
    from .routers.notes import get_edition
    from .assistant_skills import BY_ID

    edition = get_edition(kind, source_id)
    if revision and edition["revision"] != revision:
        raise HTTPException(409, "当前笔记已更新，请重新打开后读取目录。未改动正文。")
    headings = [{"level": block.level, "title": _clean_inline_markdown(block.text)}
                for block in _blocks(strip_note_frontmatter(edition["text"]))
                if block.kind == "heading"]
    visible = headings[:200]
    def literal(value: str) -> str:
        return re.sub(r"([\\`*_\[\]<>])", r"\\\1", value)
    lines = ["  " * (item["level"] - 1) + "- " + literal(item["title"]) for item in visible]
    answer = ("当前已保存笔记的目录：\n\n" + "\n".join(lines)) if lines else (
        "已读取当前保存的笔记，正文还没有 Markdown 标题，无法提取现有目录。"
        "可在编辑正文时用 #、##、### 标记标题，保存后再读取。")
    if len(headings) > len(visible):
        answer += f"\n\n共 {len(headings)} 个标题，这里显示前 {len(visible)} 个。"
    return {"skill": BY_ID["note.outline"], "answer": answer, "source": "local",
            "source_ref": {"kind": kind, "id": source_id, "revision": edition["revision"]},
            "outline": visible, "citations": [], "actions": [],
            "execution": {"state": "completed", "automatic_actions": False},
            "warning": "目录来自已保存的正文；未保存的编辑不包含在内。未改写笔记或调用模型。"}
