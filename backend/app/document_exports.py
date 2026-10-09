from __future__ import annotations

import html
import hashlib
import ipaddress
import base64
import mimetypes
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import TASK_DIR
from .document_citations import project_claim_citations
from .pdf_unicode import emoji_font_for
from .note_document import section_anchor_id, strip_note_frontmatter
from .markdown_structure import structural_lines
from .math_text import inline_math_expressions, math_source_requires_fallback, render_math_text


DOCUMENT_EXPORT_SCHEMA_VERSION = 1
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RAW_URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(cookie|set-cookie|authorization|proxy-authorization|password|secret|"
    r"access[_-]?token|refresh[_-]?token|auth[_-]?token|session(?:id)?|api[_-]?key)"
    r"\b(\s*[:=]\s*)[^\r\n]*"
)
_NON_BMP_RE = re.compile(r"([\U00010000-\U0010FFFF])")
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_SAFE_URL_QUERY_KEYS = {"v", "p", "list", "index", "t", "start", "page", "bvid", "aid", "cid"}


class DocumentExportUnavailable(RuntimeError):
    """Raised when an explicitly declared document dependency is unavailable."""


@dataclass(frozen=True)
class DocumentExport:
    content: bytes
    media_type: str
    suffix: str
    font_name: str
    warnings: list[str] = field(default_factory=list)
    schema_version: int = DOCUMENT_EXPORT_SCHEMA_VERSION


@dataclass(frozen=True)
class _Block:
    kind: str
    text: str
    level: int = 0
    ordinal: int = 0


def _image_line(line: str) -> str | None:
    """Return the image source for one conservative Markdown image line."""
    value = line.strip()
    if not value.startswith("![") or not value.endswith(")"):
        return None
    marker = value.find("](", 2)
    if marker <= 2:
        return None
    source = value[marker + 2:-1]
    return source if source else None


def _is_horizontal_rule(line: str) -> bool:
    """Recognize Markdown horizontal rules with a linear scan."""
    value = line.strip()
    if len(value) < 3:
        return False
    marker = ""
    count = 0
    for char in value:
        if char.isspace():
            continue
        if char not in "-*_":
            return False
        if not marker:
            marker = char
        elif char != marker:
            return False
        count += 1
    return count >= 3


def _heading_line(line: str) -> tuple[int, str] | None:
    """Parse a heading without a backtracking expression over note content."""
    if not line.startswith("#"):
        return None
    level = 0
    while level < len(line) and line[level] == "#":
        level += 1
    if level > 6 or level >= len(line) or not line[level].isspace():
        return None
    text = line[level:].strip()
    return (level, text) if text else None


def _list_item(line: str) -> tuple[str, str, int, int] | None:
    """Scan a bounded Markdown marker once; preserve invalid input as prose.

    Like CommonMark, ordered markers have 1-9 ASCII digits. This avoids both
    backtracking on uncontrolled note text and unbounded integer conversion.
    The returned body offset also drives continuation indentation.
    """
    value = line.lstrip(" \t")
    offset = len(line) - len(value)
    if not value:
        return None
    ordinal = 0
    if value[0] in "-*+":
        kind, end = "bullet", 1
    else:
        kind, end = "ordered", 0
        while end < min(9, len(value)) and "0" <= value[end] <= "9":
            ordinal = ordinal * 10 + ord(value[end]) - ord("0")
            end += 1
        if not end or end >= len(value) or value[end] not in ".)":
            return None
        end += 1
    if end >= len(value) or not value[end].isspace():
        return None
    while end < len(value) and value[end].isspace():
        end += 1
    text = value[end:].rstrip()
    return (kind, text, ordinal, offset + end) if text else None


def _bullet_line(line: str) -> str | None:
    item = _list_item(line)
    return item[1] if item and item[0] == "bullet" else None


def _ordered_line(line: str) -> str | None:
    item = _list_item(line)
    return item[1] if item and item[0] == "ordered" else None


DEFAULT_EXPORT_OPTIONS = {
    "include_note": True,
    "include_annotations": True,
    "include_source_link": True,
    "include_timestamps": True,
    "include_images": True,
    "include_toc": False,
    "include_transcript": False,
    "include_practice": False,
    "include_diagnostics": False,
    "font_family": "Microsoft YaHei",
    "font_size": 10.5,
    "line_height": 1.6,
    "paragraph_before": 0,
    "paragraph_after": 7,
    "margin_top": 18,
    "margin_bottom": 18,
    "margin_left": 18,
    "margin_right": 18,
    "orientation": "portrait",
}



EXPORT_TEMPLATES = {
    "print": {},
    "academic": {"font_size": 11, "line_height": 1.8, "margin_top": 25,
                 "margin_bottom": 25, "margin_left": 25, "margin_right": 25, "include_toc": True},
    "compact": {"font_size": 9.5, "line_height": 1.25, "paragraph_after": 4,
                "margin_top": 12, "margin_bottom": 12, "margin_left": 12, "margin_right": 12},
}

def available_export_fonts() -> list[dict[str, object]]:
    """Report selectable fonts and whether the local generators can embed them."""

    candidates = {
        "Microsoft YaHei": [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/msyh.ttf")],
        "SimSun": [Path("C:/Windows/Fonts/simsun.ttc"), Path("C:/Windows/Fonts/simsun.ttf")],
        "Noto Sans SC": [Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), Path(__file__).resolve().parents[2] / "site" / "assets" / "fonts" / "learnnote-site-sans.woff2"],
        "Noto Serif SC": [Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")],
        "Arial": [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf")],
        "Consolas": [Path("C:/Windows/Fonts/consola.ttf")],
        "Segoe UI Emoji": [Path("C:/Windows/Fonts/seguiemj.ttf")],
    }
    return [{
        "name": name,
        "available": any(path.is_file() for path in paths),
        "embedding": "pdf-or-web" if name.startswith("Noto") else "host-fallback",
    } for name, paths in candidates.items()]


def _font_available(name: str) -> bool:
    return any(item["name"] == name and item["available"] for item in available_export_fonts())


def normalize_export_options(value: dict | None = None) -> dict:
    """Normalize the shared export contract without trusting client values."""
    incoming = value if isinstance(value, dict) else {}
    template = str(incoming.get("template") or "print")
    if template not in EXPORT_TEMPLATES:
        template = "print"
    result = {**DEFAULT_EXPORT_OPTIONS, **EXPORT_TEMPLATES[template], "template": template}
    for key in ("include_note", "include_annotations", "include_source_link", "include_timestamps", "include_images", "include_toc", "include_transcript", "include_practice", "include_diagnostics"):
        if key in incoming:
            result[key] = bool(incoming[key])
    for key, low, high in (("font_size", 8, 36), ("line_height", 1.0, 3.0), ("paragraph_before", 0, 60), ("paragraph_after", 0, 60), ("margin_top", 5, 50), ("margin_bottom", 5, 50), ("margin_left", 5, 50), ("margin_right", 5, 50)):
        if key in incoming:
            try:
                result[key] = max(low, min(high, float(incoming[key])))
            except (TypeError, ValueError):
                pass
    if str(incoming.get("orientation") or "").lower() in {"portrait", "landscape"}:
        result["orientation"] = str(incoming["orientation"]).lower()
    if str(incoming.get("font_family") or "").strip() in {"Microsoft YaHei", "SimSun", "Noto Sans SC", "Noto Serif SC", "Arial", "Consolas"}:
        result["font_family"] = str(incoming["font_family"]).strip()
    return result


def _transcript_markdown(transcript: dict | None) -> str:
    segments = transcript.get("segments") if isinstance(transcript, dict) else []
    if not isinstance(segments, list):
        return ""
    lines = ["## 完整字幕", ""]
    for segment in segments:
        if not isinstance(segment, dict) or not str(segment.get("text") or "").strip():
            continue
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or start)
        lines.append(f"- `{int(start // 60):02d}:{int(start % 60):02d}–{int(end // 60):02d}:{int(end % 60):02d}` {segment['text']}")
    return "\n".join(lines) if len(lines) > 2 else ""


def _practice_markdown(practice: list[dict] | None) -> str:
    if not isinstance(practice, list):
        return ""
    lines = ["## 学习空间练习", ""]
    for index, item in enumerate(practice, start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("front") or "").strip()
        answer = str(item.get("answer") or item.get("back") or "").strip()
        if not question or not answer:
            continue
        lines.extend([f"### 练习 {index}", "", question, "", f"答案：{answer}", ""])
    return "\n".join(lines).rstrip() if len(lines) > 2 else ""


def evidence_review_notice(task) -> str:
    if "llm" in str(getattr(task, "summary_source", "")).lower():
        return "**来源核对提示**：本笔记包含 AI 生成内容，尚未逐条人工核对。请结合字幕与原视频检查数字、名称和推断。"
    return ""



def _diagnostic_summary_markdown(task) -> str:
    """Opt-in machine-status summary; never export raw provider text or paths."""
    lines = ["## 诊断摘要", ""]
    for label, key in (("任务状态", "status"), ("处理阶段", "phase"), ("总结路线", "summary_source"), ("错误代码", "error_code")):
        value = str(getattr(task, key, "") or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value):
            lines.append(f"- {label}：{value}")
    diagnostics = getattr(task, "summary_diagnostics", {})
    quality = diagnostics.get("note_quality", {}) if isinstance(diagnostics, dict) else {}
    if isinstance(quality, dict):
        codes = [str(item.get("code") or "") for item in quality.get("issues", []) if isinstance(item, dict)]
        codes = [value for value in codes if re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value)]
        if codes: lines.append("- 结构检查：" + "、".join(codes[:20]))
    if len(lines) == 2: lines.append("当前资料没有可导出的诊断摘要。")
    return "\n".join(lines)

def build_structured_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
    claim_map: dict | None = None,
    options: dict | None = None,
) -> dict:
    """Build one portable content tree consumed by HTML, DOCX and PDF."""
    settings = normalize_export_options(options)
    title = str(getattr(task, "title", "LearnNote 学习笔记")) or "LearnNote 学习笔记"
    source_url = _safe_hyperlink(str(getattr(task, "page_url", ""))) if settings["include_source_link"] else ""
    note, citation_warnings = project_claim_citations(task, str(note or ""), claim_map, settings,
        safe_url=_safe_hyperlink, timed_url=_timestamp_source_url, sanitize=sanitize_export_text, transcript=transcript,
        heading_texts=[block.text for block in _content_blocks(strip_note_frontmatter(note), title) if block.kind == "heading"])
    parts: list[str] = []
    if settings["include_note"]:
        notice = evidence_review_notice(task)
        if notice:
            parts.append(notice)
        value = strip_note_frontmatter(str(note or ""))
        if not settings["include_images"]:
            value = re.sub(r"(?m)^!\[[^\]]*\]\([^\n]+\)\s*$", "", value)
        if not settings["include_timestamps"]:
            value = re.sub(r"(?<!\d)(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s*(?:-|–|—|~|至)\s*(?:\d{1,2}:)?\d{1,2}:\d{2})?", "", value)
        elif source_url:
            value = _linkify_video_timestamps(value, source_url)
        parts.append(value)
    if settings["include_annotations"] and str(annotations or "").strip():
        annotation_text = str(annotations).strip()
        parts.append(annotation_text if re.match(r"^#{1,6}\s+", annotation_text) else "## 我的补充\n\n" + annotation_text)
    if settings["include_transcript"]:
        value = _transcript_markdown(transcript)
        if value:
            parts.append(value)
    if settings["include_practice"]:
        value = _practice_markdown(practice)
        if value:
            parts.append(value)
    if settings["include_diagnostics"]:
        parts.append(_diagnostic_summary_markdown(task))
    # Only trim document-boundary line breaks.  Whitespace inside code blocks
    # and Markdown hard-breaks is content and must survive export.
    body = "\n\n".join(part for part in parts if str(part).strip()).strip("\n")
    if settings["include_toc"] and body:
        headings = []
        for block in _blocks(body):
            if block.kind == "heading" and block.level <= 3:
                headings.append((block.level, block.text))
        if headings:
            toc = ["## 目录", ""]
            for level, heading in headings:
                indent = "  " * max(0, level - 1)
                toc.append(f"{indent}- {_clean_inline_markdown(heading)}")
            body = "\n".join(toc) + "\n\n" + body
    content_blocks = _content_blocks(body, title)
    expressions = [block.text for block in content_blocks if block.kind == "math"]
    expressions += [expression for block in content_blocks if block.kind != "code" for expression in inline_math_expressions(block.text)]
    warnings = citation_warnings + (["unrecognized_math_commands_preserved_as_source"] if any(math_source_requires_fallback(value) for value in expressions) else [])
    return {
        "schema_version": DOCUMENT_EXPORT_SCHEMA_VERSION,
        "title": sanitize_export_text(title),
        "source": {"url": source_url, "label": source_url or "本地资料"},
        "blocks": [block.__dict__ for block in content_blocks],
        "warnings": warnings,
        "markdown": body,
        "options": settings,
    }


def _blocks(markdown: str) -> list[_Block]:
    """Parse the lesson-note subset, retaining list depth and code/math data."""
    result: list[_Block] = []
    paragraph: list[str] = []
    table: list[str] = []
    list_indents: list[int] = []
    content_indents: dict[int, int] = {}
    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            pieces = []
            for position, item in enumerate(paragraph):
                hard_break = item.endswith("  ") or item.endswith("\\")
                pieces.append((item[:-1] if item.endswith("\\") else item).strip())
                if position < len(paragraph) - 1:
                    pieces.append("\n" if hard_break else " ")
            result.append(_Block("paragraph", "".join(pieces)))
            paragraph.clear()

    def flush_table() -> None:
        if table:
            result.append(_Block("table", "\n".join(table)))
            table.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip(" \t")
        indent = len(line) - len(stripped)
        child_level = len(list_indents) if list_indents and indent > list_indents[-1] else 0
        fence = re.match(r"^(`{3,}|~{3,})(.*)$", stripped)
        if fence and (indent <= 3 or list_indents):
            flush_paragraph(); flush_table()
            character, length, code = fence[1][0], len(fence[1]), []
            index += 1
            while index < len(lines):
                current = lines[index]
                closing = re.match(r"^\s*([`~]+)\s*$", current)
                if closing and set(closing[1]) == {character} and len(closing[1]) >= length:
                    index += 1
                    break
                code.append(current[indent:] if current[:indent].isspace() else current)
                index += 1
            result.append(_Block("code", "\n".join(code), child_level))
            continue
        if stripped in {"$$", r"\["}:
            closing = "$$" if stripped == "$$" else r"\]"
            end = next((pos for pos in range(index + 1, len(lines)) if lines[pos].strip() == closing), None)
            if end is not None:
                flush_paragraph(); flush_table()
                result.append(_Block("math", "\n".join(lines[index + 1:end]), child_level))
                index = end + 1
                continue
        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            flush_paragraph(); flush_table()
            result.append(_Block("math", stripped[2:-2].strip(), child_level))
            index += 1
            continue
        item = _list_item(line)
        if item is not None and (indent < 4 or list_indents):
            flush_paragraph(); flush_table()
            while list_indents and list_indents[-1] > indent: list_indents.pop()
            if not list_indents or list_indents[-1] < indent: list_indents.append(indent)
            content_indents[indent] = item[3]
            level = min(8, len(list_indents) - 1)
            result.append(_Block(item[0], item[1], level, item[2]))
            index += 1
            continue
        if (child_level and result and result[-1].kind in {"bullet", "ordered"}
                and indent < content_indents.get(list_indents[-1],list_indents[-1]+2) + 4
                and stripped and not stripped.startswith(("|", ">"))):
            result[-1] = replace(result[-1], text=result[-1].text + " " + stripped)
            index += 1
            continue
        if line.startswith(("    ", "\t")):
            flush_paragraph(); flush_table()
            code = []
            while index < len(lines):
                current = lines[index]
                if current and not current.startswith(("    ", "\t")): break
                code.append(current[4:] if current.startswith("    ") else current[1:] if current.startswith("\t") else "")
                index += 1
            while code and not code[-1]: code.pop()
            result.append(_Block("code", "\n".join(code), child_level))
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph(); table.append(line); index += 1
            continue
        flush_table()
        if not stripped or _is_horizontal_rule(line):
            flush_paragraph(); index += 1
            continue
        image_source, heading = _image_line(line), _heading_line(line)
        if image_source is not None:
            flush_paragraph(); result.append(_Block("image", stripped, child_level))
        elif heading is not None:
            flush_paragraph(); result.append(_Block("heading", heading[1], heading[0])); list_indents = []
        elif stripped.startswith(">"):
            flush_paragraph(); result.append(_Block("quote", stripped[1:].lstrip(), child_level))
        else:
            paragraph.append(line)
            if not indent: list_indents = []
        index += 1
    flush_paragraph(); flush_table()
    return [block for block in result if block.text.strip()]


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        value = line.strip()
        cells, cell = [], []
        code_delimiter = 0
        index = 0
        while index < len(value):
            character = value[index]
            if character == "\\" and index + 1 < len(value) and value[index + 1] in "|\\":
                cell.append(value[index + 1])
                index += 2
                continue
            if character == "`":
                end = index + 1
                while end < len(value) and value[end] == "`":
                    end += 1
                count = end - index
                if not code_delimiter:
                    code_delimiter = count
                elif count == code_delimiter:
                    code_delimiter = 0
                cell.append(value[index:end])
                index = end
                continue
            if character == "|" and not code_delimiter:
                cells.append("".join(cell).strip())
                cell = []
            else:
                cell.append(character)
            index += 1
        cells.append("".join(cell).strip())
        if value.startswith("|") and cells and cells[0] == "":
            cells.pop(0)
        if value.endswith("|") and cells and cells[-1] == "":
            cells.pop()
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    width = max((len(row) for row in rows), default=1)
    return [row + [""] * (width - len(row)) for row in rows]


def _task_image(task, markdown: str) -> tuple[Path | None, str]:
    match = re.fullmatch(r"!\[([^\]]*)\]\(([^\n]+)\)", markdown)
    if not match:
        return None, ""
    caption, url = match.groups()
    expected_prefix = f"/api/tasks/{task.id}/"
    try:
        parsed = urlsplit(url)
        if not parsed.path.startswith(expected_prefix):
            return None, _sanitize_export_text(caption)
        root = (TASK_DIR / task.id).resolve()
        # Only embed indexed local frames; never download arbitrary Markdown
        # URLs or open a user-supplied local filename while exporting.
        for grid in getattr(task, "frame_grids", []):
            path = Path(grid.path).resolve()
            if path.is_relative_to(root) and path.is_file() and Path(parsed.path).name == path.name:
                return path, _sanitize_export_text(caption)
    except (ValueError, OSError):
        pass
    return None, _sanitize_export_text(caption)


def _safe_hyperlink(value: str) -> str:
    target = str(value or "").strip()
    try:
        parsed = urlsplit(target)
    except ValueError:
        return ""
    try:
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return ""
        hostname = parsed.hostname or ""
        lowered = hostname.rstrip(".").lower()
        if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith((".localhost", ".local", ".lan", ".internal", ".home", ".corp")):
            return ""
        try:
            if not ipaddress.ip_address(lowered).is_global:
                return ""
        except ValueError:
            pass
        port = f":{parsed.port}" if parsed.port else ""
        query = [
            (str(key)[:40], str(item)[:200])
            for key, item in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100)
            if key.lower() in _SAFE_URL_QUERY_KEYS
        ]
        fragment = parsed.fragment if parsed.fragment.lower().startswith(("t=", "page=")) else ""
        return urlunsplit((parsed.scheme.lower(), hostname + port, parsed.path[:1200], urlencode(query), fragment[:120]))[:1600]
    except (TypeError, ValueError):
        return ""


_EXPORT_TIMESTAMP_RE = re.compile(
    r"(?<![\d:])(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2})"
    r"(?:\s*(?:-|–|—|~|至)\s*(?:\d{1,2}:)?\d{1,2}:\d{2})?(?![\d:])"
)
_TIMESTAMP_EXCLUSIONS_RE = re.compile(r"`[^`]*`|!?\[[^\]]+\]\([^)]+\)|https?://[^\s]+", re.I)


def _timestamp_to_seconds(value: str) -> int:
    start = re.split(r"\s*(?:-|–|—|~|至)\s*", str(value), maxsplit=1)[0]
    parts = [int(item) for item in start.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[-3] * 3600 + parts[-2] * 60 + parts[-1]


def _timestamp_source_url(source_url: str, timestamp: str) -> str:
    try:
        parsed = urlsplit(source_url)
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in {"t", "start"}]
        query.append(("t", str(_timestamp_to_seconds(timestamp))))
        return _safe_hyperlink(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)))
    except (TypeError, ValueError):
        return ""


def _linkify_video_timestamps(markdown: str, source_url: str) -> str:
    """Make visible prose timecodes return to the source video position."""

    output = []
    for line, prose in structural_lines(str(markdown or "").splitlines()):
        if not prose or not line:
            output.append(line)
            continue
        excluded = [match.span() for match in _TIMESTAMP_EXCLUSIONS_RE.finditer(line)]
        pieces = []
        cursor = 0
        linked = False
        for match in _EXPORT_TIMESTAMP_RE.finditer(line):
            if any(start <= match.start() < end for start, end in excluded):
                continue
            target = _timestamp_source_url(source_url, match.group(0))
            if not target:
                continue
            pieces.append(line[cursor:match.start()])
            pieces.append(f"[{match.group(0)}]({target})")
            cursor = match.end()
            linked = True
        if linked:
            pieces.append(line[cursor:])
            output.append("".join(pieces))
        else:
            output.append(line)
    return "\n".join(output)


def sanitize_export_text(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 0x20)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)} [REDACTED]", text)

    def replace_url(match: re.Match[str]) -> str:
        safe = _safe_hyperlink(match.group(0).rstrip(".,;，。；"))
        return safe or "[private URL removed]"

    return _RAW_URL_RE.sub(replace_url, text)


_sanitize_export_text = sanitize_export_text


def _clean_inline_markdown(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    return text


def _content_blocks(markdown: str, title: str) -> list[_Block]:
    blocks = _blocks(markdown)
    if not blocks:
        return blocks
    def normalize(value: str) -> str:
        return re.sub(r"\s+", " ", _clean_inline_markdown(value)).strip().casefold()

    return [block for block in blocks if not (
        block.kind == "heading" and block.level == 1 and normalize(block.text) == normalize(title))]



def _heading_anchors(blocks: list[_Block]) -> dict[int, str]:
    occurrences: dict[str, int] = {}
    anchors = {}
    for index, block in enumerate(blocks):
        if block.kind == "heading":
            base = section_anchor_id(block.text)
            occurrences[base] = occurrences.get(base, 0) + 1
            anchors[index] = section_anchor_id(block.text, occurrences[base])
    return anchors


def _word_bookmark_name(anchor: str) -> str:
    # Word bookmark names must begin with a letter and fit in 40 characters.
    return "ln_" + hashlib.sha256(anchor.encode("utf-8")).hexdigest()[:32]


def _wrap_pdf_code(text: str, font_name: str, font_size: float, width: float) -> str:
    """Wrap code for the physical frame width, including wide CJK characters."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines = []
    for line in text.expandtabs(4).split("\n"):
        if not line:
            lines.append("")
            continue
        while line:
            low, high = 1, len(line)
            while low < high:
                middle = (low + high + 1) // 2
                measured = sum(stringWidth(part, selected, font_size) for part, selected in _pdf_text_runs(line[:middle], font_name))
                if measured <= width:
                    low = middle
                else:
                    high = middle - 1
            lines.append(line[:low])
            line = line[low:]
    return "\n".join(lines)


def _docx_numbering_sequence(document, start: int) -> int:
    """Create an editable decimal list with the source's starting ordinal."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    numbering = document.part.numbering_part.element
    abstract_id = max([int(node.get(qn("w:abstractNumId"))) for node in numbering.findall(qn("w:abstractNum"))] or [-1]) + 1
    num_id = max([int(node.get(qn("w:numId"))) for node in numbering.findall(qn("w:num"))] or [0]) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    for tag, value in (("start", str(start)), ("numFmt", "decimal"), ("lvlText", "%1."), ("lvlJc", "left")):
        item = OxmlElement(f"w:{tag}")
        item.set(qn("w:val"), value)
        level.append(item)
    abstract.append(level)
    first_num = numbering.find(qn("w:num"))
    numbering.insert(list(numbering).index(first_num) if first_num is not None else len(numbering), abstract)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_reference = OxmlElement("w:abstractNumId")
    abstract_reference.set(qn("w:val"), str(abstract_id))
    num.append(abstract_reference)
    numbering.append(num)
    return num_id

def _add_docx_hyperlink(paragraph, text: str, url: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    hyperlink = OxmlElement("w:hyperlink")
    if url.startswith("#"):
        hyperlink.set(qn("w:anchor"), url[1:])
    else:
        relation_id = paragraph.part.relate_to(
            url,
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True,
        )
        hyperlink.set(qn("r:id"), relation_id)
    from docx.text.paragraph import Paragraph as WordParagraph
    scratch = WordParagraph(OxmlElement("w:p"), paragraph._parent)
    scratch.style = paragraph.style
    _add_docx_text(scratch, text)
    for run in scratch.runs:
        properties = run._element.get_or_add_rPr()
        color = OxmlElement("w:color"); color.set(qn("w:val"), "0F766E")
        underline = OxmlElement("w:u"); underline.set(qn("w:val"), "single")
        properties.extend((color, underline))
        hyperlink.append(run._element)
    paragraph._p.append(hyperlink)


def _add_docx_text(paragraph, value: str, *, bold: bool = False, font_name: str = "") -> None:
    """Use a dedicated host emoji font for non-BMP runs in editable Word output."""

    from docx.oxml.ns import qn

    for part in re.split(r"([\U00010000-\U0010FFFF]|[\u2e80-\u9fff\uac00-\ud7af\uff00-\uffef]+)", str(value or "")):
        if not part:
            continue
        run = paragraph.add_run(part)
        if bold:
            run.bold = True
        if font_name:
            run.font.name = font_name
        if re.search(r"[\u2e80-\u9fff\uac00-\ud7af\uff00-\uffef]", part):
            style = paragraph.style
            for _ in range(8):
                if style is None or style.font.name:
                    break
                style = style.base_style
            preferred = style.font.name if style is not None else ""
            if preferred in {"Noto Serif SC", "Noto Serif CJK SC"}:
                family = "Noto Serif CJK SC"
            elif preferred == "SimSun" and _font_available("SimSun"):
                family = "SimSun"
            else:
                family = "Microsoft YaHei" if _font_available("Microsoft YaHei") else "Noto Sans CJK SC"
            run.font.name = family
            fonts = run._element.get_or_add_rPr().rFonts
            for script in ("ascii", "hAnsi", "eastAsia", "cs"):
                fonts.set(qn(f"w:{script}"), family)
        if _NON_BMP_RE.search(part):
            run.font.name = "Segoe UI Emoji"
            properties = run._element.get_or_add_rPr()
            fonts = properties.rFonts
            if fonts is not None:
                for script in ("ascii", "hAnsi", "eastAsia", "cs"):
                    fonts.set(qn(f"w:{script}"), "Segoe UI Emoji")


def _add_docx_inline(paragraph, value: str, *, anchors: dict[str, str] | None = None) -> None:
    cursor = 0
    text = str(value or "")
    token_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|(?<!\\)\$(?!\$)([^$\n]+)\$(?!\$)")
    for match in token_re.finditer(text):
        if match.start() > cursor:
            _add_docx_text(paragraph, _sanitize_export_text(text[cursor:match.start()]))
        if match.group(1) is not None:
            label, raw_url = match.group(1), match.group(2)
            url = (anchors or {}).get(raw_url) or _safe_hyperlink(raw_url)
            if url:
                display_label = url if "://" in label else _sanitize_export_text(label)
                _add_docx_hyperlink(paragraph, display_label, url)
            else:
                _add_docx_text(paragraph, f"{_sanitize_export_text(label)}（链接已移除）")
        elif match.group(3) is not None or match.group(4) is not None:
            _add_docx_text(paragraph, _sanitize_export_text(match.group(3) or match.group(4)), bold=True)
        elif match.group(6) is not None:
            _add_docx_text(paragraph, render_math_text(_sanitize_export_text(match.group(6))))
        else:
            _add_docx_text(paragraph, _sanitize_export_text(match.group(5) or ""), font_name="Consolas")
        cursor = match.end()
    if cursor < len(text):
        _add_docx_text(paragraph, _sanitize_export_text(text[cursor:]))


def build_docx_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
    claim_map: dict | None = None,
    export_options: dict | None = None,
) -> DocumentExport:
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.shared import Cm, Pt
        from docx.oxml import OxmlElement
    except ImportError as exc:
        raise DocumentExportUnavailable("docx_export_dependency_missing") from exc

    settings = normalize_export_options(export_options)
    structured = build_structured_export(
        task,
        note,
        transcript,
        annotations=annotations,
        practice=practice,
        claim_map=claim_map,
        options={**settings, "include_toc": False},
    )
    note = structured["markdown"]
    anchor_targets = {"#" + value: "#" + _word_bookmark_name(value)
                      for value in _heading_anchors(_content_blocks(note, structured["title"])).values()}
    def inline(paragraph, value):
        _add_docx_inline(paragraph, value, anchors=anchor_targets)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = Cm(settings["margin_top"] / 10)
    section.bottom_margin = Cm(settings["margin_bottom"] / 10)
    section.left_margin = Cm(settings["margin_left"] / 10)
    section.right_margin = Cm(settings["margin_right"] / 10)
    if settings["orientation"] == "landscape":
        from docx.enum.section import WD_ORIENT
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("LearnNote | ")

    def add_word_field(paragraph, instruction: str, cached: str = "1") -> None:
        begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
        command = OxmlElement("w:instrText"); command.set(qn("xml:space"), "preserve"); command.text = f" {instruction} "
        separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
        value = OxmlElement("w:t"); value.text = cached
        end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
        run = OxmlElement("w:r")
        for item in (begin, command, separate, value, end):
            run.append(item)
        paragraph._p.append(run)

    add_word_field(footer, "PAGE")
    footer.add_run(" / ")
    add_word_field(footer, "NUMPAGES")
    normal = document.styles["Normal"]
    normal.font.name = settings["font_family"]
    normal.font.size = Pt(settings["font_size"])
    normal.paragraph_format.space_before = Pt(settings["paragraph_before"])
    normal.paragraph_format.space_after = Pt(settings["paragraph_after"])
    normal.paragraph_format.line_spacing = settings["line_height"]
    normal.paragraph_format.widow_control = True
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), settings["font_family"])
    normal._element.rPr.rFonts.set(qn("w:ascii"), settings["font_family"])
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), settings["font_family"])
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        style = document.styles[name]
        style.font.name = settings["font_family"]
        style._element.rPr.rFonts.set(qn("w:eastAsia"), settings["font_family"])
        style._element.rPr.rFonts.set(qn("w:ascii"), settings["font_family"])
        style._element.rPr.rFonts.set(qn("w:hAnsi"), settings["font_family"])

    raw_title = str(getattr(task, "title", "LearnNote 学习笔记")) or "LearnNote 学习笔记"
    safe_title = _sanitize_export_text(raw_title)[:250]
    header = section.header.paragraphs[0]
    header_budget = max(8, int((section.page_width - section.left_margin - section.right_margin) / Pt(9)))
    header_text = safe_title if len(safe_title) <= header_budget else safe_title[:max(1, header_budget - 3)] + "..."
    _add_docx_text(header, header_text)
    for run in header.runs:
        run.font.size = Pt(8)
    document.core_properties.title = safe_title
    document.core_properties.subject = "LearnNote evidence-grounded local export"
    document.core_properties.author = "LearnNote"
    title_paragraph = document.add_heading("", 0)
    _add_docx_text(title_paragraph, safe_title)

    source_url = structured["source"]["url"]
    if settings["include_source_link"] or settings["include_timestamps"]:
        source_line = document.add_paragraph()
        if settings["include_source_link"]:
            _add_docx_text(source_line, "来源：", bold=True)
            if source_url:
                _add_docx_hyperlink(source_line, source_url, source_url)
            else:
                _add_docx_text(source_line, "本地资料")
        if settings["include_timestamps"]:
            _add_docx_text(source_line, ("\n" if settings["include_source_link"] else "") + f"导出时间：{datetime.now(timezone.utc).isoformat()}")
    segments = (transcript or {}).get("segments") if isinstance(transcript, dict) else []
    if settings["include_timestamps"] and isinstance(segments, list) and segments:
        source_line = locals().get("source_line") or document.add_paragraph()
        _add_docx_text(source_line, f"\n可追溯字幕片段：{len(segments)} 段")

    blocks = _content_blocks(note, raw_title)
    heading_anchors = _heading_anchors(blocks)
    if settings["include_toc"] and heading_anchors:
        _add_docx_text(document.add_paragraph(style="TOC Heading"), "目录")
        _add_docx_text(document.add_paragraph(), "页码由 Word/WPS 排版后更新目录生成。")
        toc_paragraph = document.add_paragraph()
        begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
        command = OxmlElement("w:instrText"); command.set(qn("xml:space"), "preserve")
        command.text = ' TOC \\o "1-3" \\h \\z \\u '
        separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
        run = OxmlElement("w:r")
        for item in (begin, command, separate):
            run.append(item)
        toc_paragraph._p.append(run)
        # A useful linked cached result remains visible in viewers which do
        # not update TOC fields, without inventing pagination for another host.
        entries = [(index, block) for index, block in enumerate(blocks) if block.kind == "heading" and block.level <= 3]
        for entry_index, (index, block) in enumerate(entries):
            if entry_index:
                toc_paragraph.add_run().add_break()
            _add_docx_hyperlink(toc_paragraph, _sanitize_export_text(_clean_inline_markdown(block.text)),
                "#" + _word_bookmark_name(heading_anchors[index]))
        end_run = OxmlElement("w:r")
        end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
        end_run.append(end)
        toc_paragraph._p.append(end_run)
        update_fields = OxmlElement("w:updateFields")
        update_fields.set(qn("w:val"), "true")
        document.settings.element.append(update_fields)

    numbering_sequences: dict[int, tuple[int, int]] = {}
    for block_index, block in enumerate(blocks):
        if block.kind == "table":
            rows = _table_rows(block.text)
            if not rows:
                _add_docx_text(document.add_paragraph(), _sanitize_export_text(block.text))
                continue
            table = document.add_table(rows=0, cols=len(rows[0]))
            table.style = "Table Grid"
            for index, values in enumerate(rows):
                cells = table.add_row().cells
                for cell, value in zip(cells, values):
                    inline(cell.paragraphs[0], value)
                if index == 0:
                    repeat = OxmlElement("w:tblHeader")
                    table.rows[0]._tr.get_or_add_trPr().append(repeat)
            document.add_paragraph()
        elif block.kind == "image":
            path, caption = _task_image(task, block.text)
            if path:
                from PIL import Image
                with Image.open(path) as image:
                    width, height = image.size
                available_width = (section.page_width - section.left_margin - section.right_margin) / Cm(1)
                available_height = (section.page_height - section.top_margin - section.bottom_margin) / Cm(1) - 2
                scale = min(available_width / max(1, width), available_height / max(1, height))
                picture = document.add_picture(str(path), width=Cm(width * scale), height=Cm(height * scale))
                document.paragraphs[-1].paragraph_format.keep_with_next = True
                picture._inline.docPr.set("descr", caption or "画面出处；请回原资料核对")
                caption_paragraph = document.add_paragraph()
                caption_text = caption or "画面出处；请回原资料核对"
                inline(caption_paragraph, _linkify_video_timestamps(caption_text, source_url) if source_url else caption_text)
        elif block.kind == "heading":
            paragraph = document.add_heading(level=max(1, min(block.level, 3)))
            inline(paragraph, block.text)
            bookmark = OxmlElement("w:bookmarkStart")
            bookmark.set(qn("w:id"), str(block_index + 1))
            bookmark.set(qn("w:name"), _word_bookmark_name(heading_anchors[block_index]))
            end = OxmlElement("w:bookmarkEnd")
            end.set(qn("w:id"), str(block_index + 1))
            paragraph._p.insert(0, bookmark)
            paragraph._p.append(end)
        elif block.kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.left_indent = Cm(.6 + .6 * block.level)
            inline(paragraph, block.text)
        elif block.kind == "ordered":
            paragraph = document.add_paragraph(style="List Number")
            paragraph.paragraph_format.left_indent = Cm(.6 + .6 * block.level)
            prior = numbering_sequences.get(block.level)
            previous = blocks[block_index - 1] if block_index else None
            continued = prior and block.ordinal == prior[1] + 1 and previous and (previous.kind in {"ordered", "bullet"} or previous.level > block.level)
            sequence_id = prior[0] if continued else _docx_numbering_sequence(document, block.ordinal)
            numbering = paragraph._p.get_or_add_pPr().get_or_add_numPr()
            numbering.get_or_add_ilvl().val = 0
            numbering.get_or_add_numId().val = sequence_id
            numbering_sequences[block.level] = (sequence_id, block.ordinal)
            inline(paragraph, block.text)
        elif block.kind == "quote":
            paragraph = document.add_paragraph(style="Quote")
            inline(paragraph, block.text)
        elif block.kind == "math":
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_docx_text(paragraph, render_math_text(_sanitize_export_text(block.text)))
        elif block.kind == "code":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Cm(.6 * block.level)
            _add_docx_text(paragraph, _sanitize_export_text(block.text), font_name="Consolas")
            for run in paragraph.runs:
                run.font.size = Pt(9)
        else:
            paragraph = document.add_paragraph()
            inline(paragraph, block.text)

    # Word handles page breaks and long documents more reliably when the final
    # paragraph is not part of a list or a code run.
    _add_docx_text(document.add_paragraph(), "由 LearnNote 在本机生成；原视频、Cookie 与诊断秘密未嵌入此文档。")
    buffer = BytesIO()
    document.save(buffer)
    warnings = [] if _font_available(settings["font_family"]) else ["requested_docx_font_unavailable_using_host_fallback"]
    warnings.extend(structured["warnings"])
    if settings["include_toc"] and heading_anchors:
        warnings.append("docx_toc_page_numbers_require_field_update")
    if _NON_BMP_RE.search(note + raw_title) and not _font_available("Segoe UI Emoji"):
        warnings.append("emoji_font_unavailable_using_host_fallback")
    return DocumentExport(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        suffix="docx",
        font_name=f"{settings['font_family']} (document preference with host fallback)",
        warnings=warnings,
    )


def _pdf_font(preferred: str = "") -> tuple[str, list[str]]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    preferred_paths = {
        "Microsoft YaHei": Path("C:/Windows/Fonts/msyh.ttc"),
        "SimSun": Path("C:/Windows/Fonts/simsun.ttc"),
        "Noto Sans SC": Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        "Noto Serif SC": Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
    }
    candidates = []
    if preferred_paths.get(preferred):
        candidates.append(("LearnNoteCJK", preferred_paths[preferred]))
    candidates.extend((
        ("LearnNoteCJK", Path("C:/Windows/Fonts/msyh.ttc")),
        ("LearnNoteCJK", Path("C:/Windows/Fonts/simsun.ttc")),
        ("LearnNoteCJK", Path("/System/Library/Fonts/PingFang.ttc")),
        ("LearnNoteCJK", Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")),
        ("LearnNoteCJK", Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")),
    ))
    attempted_preferred = bool(preferred and preferred_paths.get(preferred))
    for name, path in candidates:
        if not path.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
            warning = [] if not attempted_preferred or path == preferred_paths.get(preferred) else ["requested_pdf_font_unavailable_using_cjk_fallback"]
            return name, warning
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", ["embedded_system_cjk_font_unavailable_using_pdf_cid_fallback"]


def _pdf_compatible_text(value: str) -> str:
    """Keep PDF output legible when ReportLab cannot encode non-BMP glyphs."""

    source = str(value or "")
    pieces = []
    for character in source:
        if ord(character) <= 0xFFFF or emoji_font_for(character):
            pieces.append(character)
            continue
        name = unicodedata.name(character, "")
        if name and (unicodedata.category(character) == "So" or "EMOJI" in name):
            pieces.append(f"[{name.lower().replace('_', ' ')}]")
        else:
            pieces.append(f"[U+{ord(character):04X}]")
    return "".join(pieces)



def _pdf_symbol_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    name = "LearnNoteSymbols"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    for path in (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                 Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
                 Path("C:/Windows/Fonts/arial.ttf"),
                 Path("/System/Library/Fonts/Supplemental/Arial.ttf")):
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                return name
            except Exception:
                continue
    return "Symbol"


def _pdf_text_runs(value: str, base_font: str = "") -> list[tuple[str, str]]:
    symbols = "αβγδθλμπστφωΔΣΩ∂≤≥≠→←≈≡∑∫√∞"
    result: list[tuple[str, str]] = []
    for character in str(value or ""):
        font = emoji_font_for(character) or ("Helvetica" if 0xA0 <= ord(character) <= 0xFF
            else _pdf_symbol_font() if character in symbols else base_font)
        if result and result[-1][1] == font:
            result[-1] = (result[-1][0] + character, font)
        else:
            result.append((character, font))
    return result


def _pdf_escape_text(value: str) -> str:
    return "".join(f'<font name="{font}">{html.escape(part)}</font>' if font else html.escape(part)
                   for part, font in _pdf_text_runs(value))


def _pdf_inline(value: str, *, pdf_safe: bool = True, anchors: dict[str, str] | None = None) -> str:
    compatible = _pdf_compatible_text if pdf_safe else str
    escape_text = _pdf_escape_text if pdf_safe else html.escape
    source = str(value or "")
    parts: list[str] = []
    cursor = 0
    token_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|(?<!\\)\$(?!\$)([^$\n]+)\$(?!\$)")
    for match in token_re.finditer(source):
        parts.append(escape_text(compatible(_sanitize_export_text(source[cursor:match.start()]))))
        if match.group(1) is not None:
            label, raw_url = match.group(1), match.group(2)
            url = (anchors or {}).get(raw_url) or _safe_hyperlink(raw_url)
            if url:
                display_label = url if "://" in label else compatible(_sanitize_export_text(label))
                parts.append(f'<a href="{html.escape(url, quote=True)}" color="#0f766e"><u>{escape_text(display_label)}</u></a>')
            else:
                parts.append(escape_text(f"{compatible(_sanitize_export_text(label))}（链接已移除）"))
        elif match.group(3) is not None or match.group(4) is not None:
            parts.append(f"<strong>{escape_text(compatible(_sanitize_export_text(match.group(3) or match.group(4))))}</strong>")
        elif match.group(6) is not None:
            parts.append(escape_text(compatible(render_math_text(_sanitize_export_text(match.group(6))))))
        else:
            code_text = compatible(_sanitize_export_text(match.group(5) or ""))
            escaped = escape_text(code_text)
            if not pdf_safe:
                parts.append(f"<code>{escaped}</code>")
            elif code_text.isascii():
                parts.append(f'<font name="Courier">{escaped}</font>')
            else:
                # Courier cannot render CJK. Inherit the selected CJK font.
                parts.append(escaped)
        cursor = match.end()
    parts.append(escape_text(compatible(_sanitize_export_text(source[cursor:]))))
    return "".join(parts)


def build_pdf_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
    claim_map: dict | None = None,
    export_options: dict | None = None,
) -> DocumentExport:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, XPreformatted, SimpleDocTemplate, Spacer, LongTable, TableStyle, Image as PdfImage
    except ImportError as exc:
        raise DocumentExportUnavailable("pdf_export_dependency_missing") from exc

    settings = normalize_export_options(export_options)
    structured = build_structured_export(
        task,
        note,
        transcript,
        annotations=annotations,
        practice=practice,
        claim_map=claim_map,
        options={**settings, "include_toc": False},
    )
    note = structured["markdown"]
    anchor_targets = {"#" + value: "#" + value
                      for value in _heading_anchors(_content_blocks(note, structured["title"])).values()}
    def inline(value):
        return _pdf_inline(value, anchors=anchor_targets)
    font_name, warnings = _pdf_font(settings["font_family"])
    warnings.extend(structured["warnings"])
    raw_title = str(getattr(task, "title", "LearnNote 学习笔记")) or "LearnNote 学习笔记"
    safe_title = _pdf_compatible_text(_sanitize_export_text(raw_title))
    has_non_bmp_text = any(not emoji_font_for(character) for character in _NON_BMP_RE.findall(str(note or "") + raw_title))
    if has_non_bmp_text:
        warnings.append("non_bmp_symbols_rendered_as_unicode_names")
    buffer = BytesIO()
    from reportlab.lib.pagesizes import landscape
    class EvidenceDocTemplate(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            heading = getattr(flowable, "learnnote_heading", None)
            if heading:
                level, label, anchor = heading
                self.canv.bookmarkHorizontalAbsolute(anchor, self.frame._y + flowable.height)
                if level <= 2:
                    self.notify("TOCEntry", (level, label, self.page, anchor))

    document = EvidenceDocTemplate(
        buffer,
        pagesize=landscape(A4) if settings["orientation"] == "landscape" else A4,
        rightMargin=settings["margin_right"] * mm,
        leftMargin=settings["margin_left"] * mm,
        topMargin=settings["margin_top"] * mm,
        bottomMargin=settings["margin_bottom"] * mm,
        title=safe_title,
        author="LearnNote",
    )
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "LearnNoteBody",
        parent=sample["BodyText"],
        fontName=font_name,
        fontSize=settings["font_size"],
        leading=settings["font_size"] * settings["line_height"],
        textColor=colors.HexColor("#17201F"),
        spaceBefore=settings["paragraph_before"],
        spaceAfter=settings["paragraph_after"],
        wordWrap="CJK",
        allowWidows=0,
        allowOrphans=0,
    )
    title_style = ParagraphStyle(
        "LearnNoteTitle",
        parent=body,
        fontSize=21,
        leading=28,
        textColor=colors.HexColor("#123B37"),
        spaceAfter=12,
    )
    heading_styles = {
        1: ParagraphStyle("LearnNoteH1", parent=body, fontSize=16, leading=23, textColor=colors.HexColor("#0F5F58"), spaceBefore=12, spaceAfter=7, keepWithNext=True),
        2: ParagraphStyle("LearnNoteH2", parent=body, fontSize=13.5, leading=20, textColor=colors.HexColor("#155E58"), spaceBefore=10, spaceAfter=6, keepWithNext=True),
        3: ParagraphStyle("LearnNoteH3", parent=body, fontSize=11.5, leading=18, textColor=colors.HexColor("#1D514D"), spaceBefore=8, spaceAfter=4, keepWithNext=True),
    }
    meta = ParagraphStyle("LearnNoteMeta", parent=body, fontSize=8.5, leading=13, textColor=colors.HexColor("#52615F"))
    code = ParagraphStyle("LearnNoteCode", parent=body, fontName=font_name, fontSize=8.5, leading=12, backColor=colors.HexColor("#F2F6F5"), borderPadding=7)
    bullet = ParagraphStyle("LearnNoteBullet", parent=body, leftIndent=10, firstLineIndent=-8, bulletIndent=0)

    story = [Paragraph(_pdf_escape_text(safe_title), title_style)]
    source_url = structured["source"]["url"]
    source = f'<a href="{html.escape(source_url, quote=True)}" color="#0f766e">{html.escape(source_url)}</a>' if source_url else "本地资料"
    segments = (transcript or {}).get("segments") if isinstance(transcript, dict) else []
    meta_parts = []
    if settings["include_source_link"]:
        meta_parts.append(f"来源：{source}")
    if settings["include_timestamps"]:
        meta_parts.append(f"导出时间：{datetime.now(timezone.utc).isoformat()}")
        if isinstance(segments, list) and segments:
            meta_parts.append(f"可追溯字幕片段：{len(segments)} 段")
    if meta_parts:
        story.extend((Paragraph("<br/>".join(meta_parts), meta), Spacer(1, 5 * mm)))
    blocks = _content_blocks(note, raw_title)
    heading_anchors = _heading_anchors(blocks)
    if settings["include_toc"] and heading_anchors:
        from reportlab.platypus.tableofcontents import TableOfContents
        toc = TableOfContents()
        toc.levelStyles = [ParagraphStyle(f"LearnNoteTOC{level}", parent=body,
            leftIndent=level * 12, firstLineIndent=0, spaceBefore=3, spaceAfter=3)
            for level in range(3)]
        toc_heading = ParagraphStyle("LearnNoteTOCHeading", parent=heading_styles[2], keepWithNext=False)
        story.extend([Paragraph("目录", toc_heading), toc, Spacer(1, 8 * mm)])
    for block_index, block in enumerate(blocks):
        if block.kind == "table":
            rows = [[Paragraph(inline(cell), body) for cell in row] for row in _table_rows(block.text)]
            if not rows:
                story.append(Paragraph(html.escape(_pdf_compatible_text(_sanitize_export_text(block.text))), body))
                continue
            table = LongTable(rows, colWidths=[document.width / len(rows[0])] * len(rows[0]), repeatRows=1, splitInRow=1)
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#ccd9db")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf4f3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]))
            story.extend((table, Spacer(1, 4 * mm)))
        elif block.kind == "image":
            path, caption = _task_image(task, block.text)
            if path:
                image = PdfImage(str(path))
                scale = min(document.width / image.imageWidth, max(1, document.height - 25 * mm) / image.imageHeight)
                image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
                story.append(image)
            caption_text = caption or "画面出处；请回原资料核对"
            story.append(Paragraph(inline(_linkify_video_timestamps(caption_text, source_url) if source_url else caption_text), meta))
        elif block.kind == "heading":
            paragraph = Paragraph(inline(block.text), heading_styles[max(1, min(block.level, 3))])
            paragraph.learnnote_heading = (max(0, block.level - 1),
                _pdf_escape_text(_pdf_compatible_text(_sanitize_export_text(_clean_inline_markdown(block.text)))),
                heading_anchors[block_index])
            story.append(paragraph)
        elif block.kind == "bullet":
            style = ParagraphStyle("NestedBullet", parent=bullet, leftIndent=10+12*block.level, bulletIndent=12*block.level)
            story.append(Paragraph(inline(block.text), style, bulletText="•"))
        elif block.kind == "ordered":
            style = ParagraphStyle("NestedNumber", parent=bullet, leftIndent=10+12*block.level, bulletIndent=12*block.level)
            story.append(Paragraph(inline(block.text), style, bulletText=f"{block.ordinal}."))
        elif block.kind == "quote":
            quote = ParagraphStyle("LearnNoteQuote", parent=body, leftIndent=14,
                borderColor=colors.HexColor("#ccd9db"), borderWidth=.5, borderPadding=6)
            story.append(Paragraph(inline(block.text), quote))
        elif block.kind == "math":
            style = ParagraphStyle("LessonMath", parent=body, alignment=TA_CENTER)
            story.append(Paragraph(_pdf_escape_text(_pdf_compatible_text(render_math_text(_sanitize_export_text(block.text)))), style))
        elif block.kind == "code":
            style = ParagraphStyle("NestedCode", parent=code, leftIndent=12*block.level)
            wrapped_code = _wrap_pdf_code(_pdf_compatible_text(_sanitize_export_text(block.text)),
                font_name, code.fontSize, max(1, document.width - 14 - 12*block.level))
            story.append(XPreformatted(_pdf_escape_text(wrapped_code), style))
        else:
            story.append(Paragraph(inline(block.text).replace("\n", "<br/>"), body))
    story.extend((Spacer(1, 4 * mm), Paragraph("由 LearnNote 在本机生成；原视频、Cookie 与诊断秘密未嵌入此文档。", meta)))

    def draw_footer(canvas, doc) -> None:
        canvas.saveState()
        from reportlab.pdfbase.pdfmetrics import stringWidth
        label = safe_title
        while label and sum(stringWidth(part, selected, 7) for part, selected in _pdf_text_runs(label, font_name)) > doc.width:
            label = label[:-1]
        if label != safe_title:
            label = label[:-3] + "..."
        header_style = ParagraphStyle("LearnNotePageHeader", parent=meta, fontSize=7, leading=8)
        header = Paragraph(_pdf_escape_text(label), header_style)
        _width, height = header.wrap(doc.width, 15 * mm)
        page_height = landscape(A4)[1] if settings["orientation"] == "landscape" else A4[1]
        header.drawOn(canvas, doc.leftMargin, page_height - 7 * mm - height)
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#71807E"))
        page_width = landscape(A4)[0] if settings["orientation"] == "landscape" else A4[0]
        canvas.drawCentredString(page_width / 2, 9 * mm, f"LearnNote | {doc.page}")
        canvas.restoreState()

    document.multiBuild(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return DocumentExport(
        content=buffer.getvalue(),
        media_type="application/pdf",
        suffix="pdf",
        font_name=font_name,
        warnings=warnings,
    )


def _html_image_data(path: Path) -> str:
    try:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except (OSError, ValueError):
        return ""


def build_html_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
    claim_map: dict | None = None,
    export_options: dict | None = None,
) -> DocumentExport:
    """Render the same structured blocks as an offline, self-contained HTML file."""
    settings = normalize_export_options(export_options)
    structured = build_structured_export(
        task,
        note,
        transcript,
        annotations=annotations,
        practice=practice,
        claim_map=claim_map,
        options={**settings, "include_toc": False},
    )
    anchor_targets = {"#" + value: "#" + value
                      for value in _heading_anchors(_content_blocks(structured["markdown"], structured["title"])).values()}
    def inline(value):
        return _pdf_inline(value, pdf_safe=False, anchors=anchor_targets)
    title = html.escape(structured["title"])
    body: list[str] = []
    toc: list[str] = []
    heading_occurrences: dict[str, int] = {}
    list_stack: list[str] = []
    def close_list() -> None:
        while list_stack: body.append(f"</li></{list_stack.pop()}>")
    def list_item(block: _Block) -> None:
        kind = "ul" if block.kind == "bullet" else "ol"
        target = min(block.level, len(list_stack))
        while len(list_stack) > target + 1: body.append(f"</li></{list_stack.pop()}>")
        if len(list_stack) == target + 1:
            body.append("</li>")
            if list_stack[-1] != kind: body.append(f"</{list_stack.pop()}>")
        if len(list_stack) <= target:
            body.append(f"<{kind}>"); list_stack.append(kind)
        ordinal = f' value="{block.ordinal}"' if kind == "ol" else ""
        body.append(f"<li{ordinal}>{inline(block.text)}")
    for block in _content_blocks(structured["markdown"], structured["title"]):
        if block.kind == "heading":
            close_list()
            stable_base = section_anchor_id(block.text)
            heading_occurrences[stable_base] = heading_occurrences.get(stable_base, 0) + 1
            anchor = section_anchor_id(block.text, heading_occurrences[stable_base])
            level = max(1, min(int(block.level), 4))
            text = html.escape(_clean_inline_markdown(block.text))
            body.append(f'<h{level} id="{anchor}">{text}</h{level}>')
            if settings["include_toc"] and level <= 3:
                toc.append(f'<li class="toc-level-{level}"><a href="#{anchor}">{text}</a></li>')
        elif block.kind == "table":
            close_list()
            rows = _table_rows(block.text)
            if rows:
                rendered_rows = []
                for row_index, row in enumerate(rows):
                    tag = "th" if row_index == 0 else "td"
                    rendered_rows.append("<tr>" + "".join(f"<{tag}>{inline(cell)}</{tag}>" for cell in row) + "</tr>")
                body.append("<table>" + "".join(rendered_rows) + "</table>")
        elif block.kind == "image":
            close_list()
            path, caption = _task_image(task, block.text) if settings["include_images"] else (None, "")
            if path:
                body.append(f'<figure><img src="{_html_image_data(path)}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>')
            elif caption:
                body.append(f"<p class=\"image-note\">{html.escape(caption)}（图片未嵌入）</p>")
        elif block.kind in {"bullet", "ordered"}:
            list_item(block)
        elif block.kind == "quote":
            close_list()
            body.append(f"<blockquote>{inline(block.text)}</blockquote>")
        elif block.kind == "math":
            if not block.level: close_list()
            expression = html.escape(render_math_text(_sanitize_export_text(block.text)))
            body.append(f'<div class="math" role="math">{expression}</div>')
        elif block.kind == "code":
            if not block.level: close_list()
            body.append(f"<pre><code>{html.escape(_sanitize_export_text(block.text))}</code></pre>")
        else:
            close_list()
            body.append(f"<p>{inline(block.text).replace(chr(10), '<br>')}</p>")
    close_list()
    rendered = body

    font_path = Path(__file__).resolve().parents[2] / "site" / "assets" / "fonts" / "learnnote-site-sans.woff2"
    font_face = ""
    font_name = "system Chinese fallback"
    warnings: list[str] = list(structured["warnings"])
    if font_path.is_file():
        font_face = f"@font-face{{font-family:LearnNoteEmbedded;src:url(data:font/woff2;base64,{base64.b64encode(font_path.read_bytes()).decode('ascii')}) format('woff2');font-display:swap;}}"
        font_name = "LearnNote Embedded (with system fallback)"
    else:
        warnings.append("embedded_html_font_unavailable_using_system_fallback")
    source = structured["source"]
    source_html = ""
    if settings["include_source_link"]:
        source_html = f'<p class="meta">来源：{f'<a href="{html.escape(source["url"], quote=True)}">{html.escape(source["label"])}</a>' if source["url"] else html.escape(source["label"])}</p>'
    toc_html = f'<nav class="toc"><strong>目录</strong><ol>{"".join(toc)}</ol></nav>' if toc else ""
    css = f"""{font_face}
:root{{--ink:#24302d;--muted:#66736f;--line:#dfe7e3;--paper:#fff;--accent:#0f766e;}}
*{{box-sizing:border-box}}body{{margin:0;background:#f4f7f5;color:var(--ink);font-family:LearnNoteEmbedded,"Microsoft YaHei","Noto Sans SC",sans-serif;font-size:{settings['font_size']}pt;line-height:{settings['line_height']};}}
main{{max-width:860px;margin:0 auto;background:var(--paper);min-height:100vh;padding:{settings['margin_top']}mm {settings['margin_right']}mm {settings['margin_bottom']}mm {settings['margin_left']}mm;}}
h1{{font-size:2em;line-height:1.3;margin:0 0 1.2em}}h2{{font-size:1.45em;margin:1.5em 0 .55em}}h3,h4{{margin:1.2em 0 .45em}}p{{margin:{settings['paragraph_before']}pt 0 {settings['paragraph_after']}pt}}.meta{{color:var(--muted);font-size:.85em}}a{{color:var(--accent)}}blockquote{{border-left:3px solid var(--line);padding:.2em 1em;color:var(--muted)}}.math{{text-align:center;white-space:pre-wrap;margin:1em 0}}pre{{background:#f1f5f3;border:1px solid var(--line);padding:1em;overflow:auto;font-family:Consolas,monospace}}code{{font-family:Consolas,monospace}}table{{width:100%;border-collapse:collapse;margin:1em 0}}th,td{{border:1px solid var(--line);padding:.55em;text-align:left;vertical-align:top}}th{{background:#edf4f1}}img{{max-width:100%;height:auto}}figure{{margin:1.1em 0}}figcaption,.image-note{{color:var(--muted);font-size:.82em}}.toc{{border:1px solid var(--line);padding:1em;margin:1em 0}}.toc ol{{margin:.5em 0 0;padding-left:1.5em}}.toc-level-3{{margin-left:1em}}footer{{margin-top:2em;color:var(--muted);font-size:.8em;border-top:1px solid var(--line);padding-top:1em}}"""
    document = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head><body><main><h1>{title}</h1>{source_html}{toc_html}{"".join(rendered)}<footer>由 LearnNote 在本机生成；原视频、Cookie 与诊断秘密未嵌入此文档。</footer></main></body></html>'
    return DocumentExport(
        content=document.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        suffix="html",
        font_name=font_name,
        warnings=warnings,
    )
