"""Real note operations, reusing editions and portable document exporters."""
import difflib
import re
from types import SimpleNamespace

from fastapi import HTTPException
from .assistant_operation_store import digest
from .markdown_structure import structural_lines
from .routers.notes import get_edition


def selected_edition(source: dict):
    value = get_edition(source["kind"], source["id"])
    if value["revision"] != source["revision"]:
        raise HTTPException(409, "当前笔记已变化，请重新读取并预览。未覆盖新修改。")
    return value


def read_note(source: dict, arguments: dict):
    value = selected_edition(source)
    lines = value["text"].splitlines()
    start, count = arguments["start_line"] - 1, arguments["line_count"]
    selected = "\n".join(lines[start:start + count])
    text = selected[:24000]
    return {"text": text, "revision": value["revision"], "start_line": start + 1,
            "line_count": min(count, max(0, len(lines) - start)), "total_lines": len(lines),
            "truncated": len(selected) > len(text), "edited": value["edited"]}


def edit_text(before: str, arguments: dict) -> str:
    mode, text, old = arguments["mode"], arguments["text"], arguments["old_text"]
    if mode == "append":
        separator = "" if not before or before.endswith("\n\n") else "\n" if before.endswith("\n") else "\n\n"
        return before + separator + text + "\n"
    if mode == "replace":
        if not old or before.count(old) != 1:
            raise HTTPException(409, "原文字串必须恰好匹配一处；请缩小或明确需要替换的段落。")
        return before.replace(old, text, 1)
    if "\n" in text or "\r" in text or len(text) > 200:
        raise HTTPException(422, "正文标题必须是 200 字以内的一行文字。")
    lines = before.splitlines(keepends=True)
    for index, (line, prose) in enumerate(structural_lines(lines)):
        if prose and re.match(r"^ {0,3}#\s+", line):
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = "# " + text + ending
            return "".join(lines)
    raise HTTPException(409, "当前正文没有一级标题；可使用追加或精确替换，不会猜测代码中的标题。")


def prepare_edit(source: dict, arguments: dict):
    before = selected_edition(source)["text"]
    if len(before.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(422, "这份正文超出助手单次编辑范围，请使用正文编辑器。")
    after = edit_text(before, arguments)
    diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                      fromfile="当前保存版本", tofile="拟保存版本", n=3))
    if len(diff) > 64000:
        raise HTTPException(422, "差异过长，请缩小本次修改范围。")
    return {"before": before, "after": after, "before_revision": digest(before), "after_revision": digest(after)}, {
        "diff": diff, "changed": before != after, "notice": "应用后只保存个人修订。用于撤销的前后正文副本仅保存在本机；不会改动原始资料。"}


def export_note(source: dict, arguments: dict):
    from .document_exports import build_docx_export, build_pdf_export, build_html_export, sanitize_export_text, DocumentExport
    from .review_presentation import project_source_reviews
    from .storage import get_task
    from .library import get_material
    value = selected_edition(source)
    if source["kind"] == "task":
        task = get_task(source["id"])
    else:
        task = SimpleNamespace(id=source["id"], title=get_material(source["id"])["title"], page_url="")
    format = arguments["format"]
    if format == "markdown":
        text = sanitize_export_text(project_source_reviews(value["text"])["markdown"])
        artifact = DocumentExport(text.encode("utf-8"), "text/markdown; charset=utf-8", "md", "UTF-8")
    else:
        builder = {"docx": build_docx_export, "pdf": build_pdf_export, "html": build_html_export}[format]
        artifact = builder(task, value["text"])
    # Refuse a stale export if another editor changed the source while rendering.
    selected_edition(source)
    return artifact
