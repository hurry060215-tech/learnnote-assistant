from __future__ import annotations

import html
import ipaddress
import base64
import mimetypes
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import TASK_DIR


DOCUMENT_EXPORT_SCHEMA_VERSION = 1
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RAW_URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(cookie|set-cookie|authorization|proxy-authorization|password|secret|"
    r"access[_-]?token|refresh[_-]?token|auth[_-]?token|session(?:id)?|api[_-]?key)"
    r"\b(\s*[:=]\s*)[^\r\n]*"
)
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


def _bullet_line(line: str) -> str | None:
    value = line.lstrip()
    if len(value) < 3 or value[0] not in "-*+" or not value[1].isspace():
        return None
    text = value[2:].strip()
    return text if text else None


def _ordered_line(line: str) -> str | None:
    value = line.lstrip()
    index = 0
    while index < len(value) and value[index].isdigit():
        index += 1
    if index == 0 or index >= len(value) or value[index] not in ".)":
        return None
    index += 1
    if index >= len(value) or not value[index].isspace():
        return None
    text = value[index:].strip()
    return text if text else None


DEFAULT_EXPORT_OPTIONS = {
    "include_note": True,
    "include_annotations": True,
    "include_source_link": True,
    "include_timestamps": True,
    "include_images": True,
    "include_toc": False,
    "include_transcript": False,
    "include_practice": False,
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


def normalize_export_options(value: dict | None = None) -> dict:
    """Normalize the shared export contract without trusting client values."""
    incoming = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_EXPORT_OPTIONS)
    for key in ("include_note", "include_annotations", "include_source_link", "include_timestamps", "include_images", "include_toc", "include_transcript", "include_practice"):
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


def build_structured_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
    options: dict | None = None,
) -> dict:
    """Build one portable content tree consumed by HTML, DOCX and PDF."""
    settings = normalize_export_options(options)
    title = str(getattr(task, "title", "LearnNote 学习笔记")) or "LearnNote 学习笔记"
    parts: list[str] = []
    if settings["include_note"]:
        value = str(note or "")
        if not settings["include_images"]:
            value = re.sub(r"(?m)^!\[[^\]]*\]\([^\n]+\)\s*$", "", value)
        if not settings["include_timestamps"]:
            value = re.sub(r"(?<!\d)(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s*(?:-|–|—|~|至)\s*(?:\d{1,2}:)?\d{1,2}:\d{2})?", "", value)
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
    body = "\n\n".join(part for part in parts if str(part).strip()).strip()
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
    source_url = _safe_hyperlink(str(getattr(task, "page_url", ""))) if settings["include_source_link"] else ""
    return {
        "schema_version": DOCUMENT_EXPORT_SCHEMA_VERSION,
        "title": sanitize_export_text(title),
        "source": {"url": source_url, "label": source_url or "本地资料"},
        "blocks": [block.__dict__ for block in _content_blocks(body, title)],
        "markdown": body,
        "options": settings,
    }


def _blocks(markdown: str) -> list[_Block]:
    """Parse a conservative Markdown subset while preserving unknown content."""
    result: list[_Block] = []
    paragraph: list[str] = []
    code: list[str] = []
    table: list[str] = []
    in_code = False
    fence_character = ""
    fence_length = 0

    def flush_paragraph() -> None:
        if paragraph:
            result.append(_Block("paragraph", " ".join(item.strip() for item in paragraph if item.strip())))
            paragraph.clear()

    def flush_code() -> None:
        if code:
            result.append(_Block("code", "\n".join(code)))
            code.clear()

    def flush_table() -> None:
        if table:
            result.append(_Block("table", "\n".join(table)))
            table.clear()

    for raw_line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence and (not in_code or fence.group(1)[0] == fence_character and len(fence.group(1)) >= fence_length and not fence.group(2).strip()):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                flush_table()
                in_code = True
                fence_character, fence_length = fence.group(1)[0], len(fence.group(1))
            continue
        if in_code:
            code.append(line)
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            flush_paragraph()
            table.append(line)
            continue
        flush_table()
        image_source = _image_line(line)
        if image_source is not None:
            flush_paragraph()
            result.append(_Block("image", line.strip()))
            continue
        if not line.strip():
            flush_paragraph()
            continue
        if _is_horizontal_rule(line):
            flush_paragraph()
            continue
        heading = _heading_line(line)
        if heading is not None:
            flush_paragraph()
            result.append(_Block("heading", heading[1], heading[0]))
            continue
        bullet = _bullet_line(line)
        if bullet is not None:
            flush_paragraph()
            result.append(_Block("bullet", bullet))
            continue
        ordered = _ordered_line(line)
        if ordered is not None:
            flush_paragraph()
            result.append(_Block("ordered", ordered))
            continue
        paragraph.append(line)
    flush_paragraph()
    flush_code()
    flush_table()
    return [block for block in result if block.text.strip()]


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
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
    first = blocks[0]
    def normalize(value: str) -> str:
        return re.sub(r"\s+", " ", _clean_inline_markdown(value)).strip().casefold()

    if first.kind == "heading" and first.level == 1 and normalize(first.text) == normalize(title):
        return blocks[1:]
    return blocks


def _add_docx_hyperlink(paragraph, text: str, url: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    relation_id = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relation_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0F766E")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.extend((color, underline))
    run.append(properties)
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _add_docx_inline(paragraph, value: str) -> None:
    cursor = 0
    text = str(value or "")
    token_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`")
    for match in token_re.finditer(text):
        if match.start() > cursor:
            paragraph.add_run(_sanitize_export_text(text[cursor:match.start()]))
        if match.group(1) is not None:
            label, raw_url = match.group(1), match.group(2)
            url = _safe_hyperlink(raw_url)
            if url:
                display_label = url if "://" in label else _sanitize_export_text(label)
                _add_docx_hyperlink(paragraph, display_label, url)
            else:
                paragraph.add_run(f"{_sanitize_export_text(label)}（链接已移除）")
        elif match.group(3) is not None or match.group(4) is not None:
            run = paragraph.add_run(_sanitize_export_text(match.group(3) or match.group(4)))
            run.bold = True
        else:
            run = paragraph.add_run(_sanitize_export_text(match.group(5) or ""))
            run.font.name = "Consolas"
        cursor = match.end()
    if cursor < len(text):
        paragraph.add_run(_sanitize_export_text(text[cursor:]))


def build_docx_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
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
        options=settings,
    )
    note = structured["markdown"]
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(settings["margin_top"] / 10)
    section.bottom_margin = Cm(settings["margin_bottom"] / 10)
    section.left_margin = Cm(settings["margin_left"] / 10)
    section.right_margin = Cm(settings["margin_right"] / 10)
    if settings["orientation"] == "landscape":
        from docx.enum.section import WD_ORIENT
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    normal = document.styles["Normal"]
    normal.font.name = settings["font_family"]
    normal.font.size = Pt(settings["font_size"])
    normal.paragraph_format.space_before = Pt(settings["paragraph_before"])
    normal.paragraph_format.space_after = Pt(settings["paragraph_after"])
    normal.paragraph_format.line_spacing = settings["line_height"]
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
    document.core_properties.title = safe_title
    document.core_properties.subject = "LearnNote evidence-grounded local export"
    document.core_properties.author = "LearnNote"
    document.add_heading(safe_title, 0)

    source_url = structured["source"]["url"]
    if settings["include_source_link"] or settings["include_timestamps"]:
        source_line = document.add_paragraph()
        if settings["include_source_link"]:
            source_line.add_run("来源：").bold = True
            if source_url:
                _add_docx_hyperlink(source_line, source_url, source_url)
            else:
                source_line.add_run("本地资料")
        if settings["include_timestamps"]:
            source_line.add_run(("\n" if settings["include_source_link"] else "") + f"导出时间：{datetime.now(timezone.utc).isoformat()}")
    segments = (transcript or {}).get("segments") if isinstance(transcript, dict) else []
    if settings["include_timestamps"] and isinstance(segments, list) and segments:
        source_line = locals().get("source_line") or document.add_paragraph()
        source_line.add_run(f"\n可追溯字幕片段：{len(segments)} 段")

    for block in _content_blocks(note, raw_title):
        if block.kind == "table":
            rows = _table_rows(block.text)
            if not rows:
                document.add_paragraph(_sanitize_export_text(block.text))
                continue
            table = document.add_table(rows=0, cols=len(rows[0]))
            table.style = "Table Grid"
            for index, values in enumerate(rows):
                cells = table.add_row().cells
                for cell, value in zip(cells, values):
                    _add_docx_inline(cell.paragraphs[0], value)
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
                scale = min(16 / max(1, width), 18 / max(1, height))
                document.add_picture(str(path), width=Cm(width * scale), height=Cm(height * scale))
            document.add_paragraph(caption or "画面出处；请回原资料核对")
        elif block.kind == "heading":
            paragraph = document.add_heading(level=max(1, min(block.level, 3)))
            _add_docx_inline(paragraph, block.text)
        elif block.kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            _add_docx_inline(paragraph, block.text)
        elif block.kind == "ordered":
            paragraph = document.add_paragraph(style="List Number")
            _add_docx_inline(paragraph, block.text)
        elif block.kind == "code":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(_sanitize_export_text(block.text))
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        else:
            paragraph = document.add_paragraph()
            _add_docx_inline(paragraph, block.text)

    # Word handles page breaks and long documents more reliably when the final
    # paragraph is not part of a list or a code run.
    document.add_paragraph("由 LearnNote 在本机生成；原视频、Cookie 与诊断秘密未嵌入此文档。")
    buffer = BytesIO()
    document.save(buffer)
    return DocumentExport(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        suffix="docx",
        font_name=f"{settings['font_family']} (document preference with host fallback)",
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


def _pdf_inline(value: str) -> str:
    source = str(value or "")
    parts: list[str] = []
    cursor = 0
    token_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`")
    for match in token_re.finditer(source):
        parts.append(html.escape(_sanitize_export_text(source[cursor:match.start()])))
        if match.group(1) is not None:
            label, raw_url = match.group(1), match.group(2)
            url = _safe_hyperlink(raw_url)
            if url:
                display_label = url if "://" in label else _sanitize_export_text(label)
                parts.append(f'<a href="{html.escape(url, quote=True)}" color="#0f766e"><u>{html.escape(display_label)}</u></a>')
            else:
                parts.append(html.escape(f"{_sanitize_export_text(label)}（链接已移除）"))
        elif match.group(3) is not None or match.group(4) is not None:
            parts.append(f"<strong>{html.escape(_sanitize_export_text(match.group(3) or match.group(4)))}</strong>")
        else:
            parts.append(f'<font name="Courier">{html.escape(_sanitize_export_text(match.group(5) or ""))}</font>')
        cursor = match.end()
    parts.append(html.escape(_sanitize_export_text(source[cursor:])))
    return "".join(parts)


def build_pdf_export(
    task,
    note: str,
    transcript: dict | None = None,
    *,
    annotations: str = "",
    practice: list[dict] | None = None,
    export_options: dict | None = None,
) -> DocumentExport:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, LongTable, TableStyle, Image as PdfImage
    except ImportError as exc:
        raise DocumentExportUnavailable("pdf_export_dependency_missing") from exc

    settings = normalize_export_options(export_options)
    structured = build_structured_export(
        task,
        note,
        transcript,
        annotations=annotations,
        practice=practice,
        options=settings,
    )
    note = structured["markdown"]
    font_name, warnings = _pdf_font(settings["font_family"])
    buffer = BytesIO()
    from reportlab.lib.pagesizes import landscape
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4) if settings["orientation"] == "landscape" else A4,
        rightMargin=settings["margin_right"] * mm,
        leftMargin=settings["margin_left"] * mm,
        topMargin=settings["margin_top"] * mm,
        bottomMargin=settings["margin_bottom"] * mm,
        title=_sanitize_export_text(str(getattr(task, "title", "LearnNote 学习笔记"))),
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

    raw_title = str(getattr(task, "title", "LearnNote 学习笔记")) or "LearnNote 学习笔记"
    safe_title = _sanitize_export_text(raw_title)
    story = [Paragraph(html.escape(safe_title), title_style)]
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
    for block in _content_blocks(note, raw_title):
        if block.kind == "table":
            rows = [[Paragraph(_pdf_inline(cell), body) for cell in row] for row in _table_rows(block.text)]
            if not rows:
                story.append(Paragraph(html.escape(_sanitize_export_text(block.text)), body))
                continue
            table = LongTable(rows, colWidths=[document.width / len(rows[0])] * len(rows[0]), repeatRows=1, splitInRow=1)
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#ccd9db")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf4f3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]))
            story.extend((table, Spacer(1, 4 * mm)))
        elif block.kind == "image":
            path, caption = _task_image(task, block.text)
            if path:
                image = PdfImage(str(path))
                scale = min(document.width / image.imageWidth, 180 * mm / image.imageHeight)
                image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
                story.append(image)
            story.append(Paragraph(html.escape(caption or "画面出处；请回原资料核对"), meta))
        elif block.kind == "heading":
            story.append(Paragraph(_pdf_inline(block.text), heading_styles[max(1, min(block.level, 3))]))
        elif block.kind == "bullet":
            story.append(Paragraph(_pdf_inline(block.text), bullet, bulletText="•"))
        elif block.kind == "ordered":
            story.append(Paragraph("• " + _pdf_inline(block.text), bullet))
        elif block.kind == "code":
            story.append(Preformatted(_sanitize_export_text(block.text), code, maxLineLength=88))
        else:
            story.append(Paragraph(_pdf_inline(block.text), body))
    story.extend((Spacer(1, 4 * mm), Paragraph("由 LearnNote 在本机生成；原视频、Cookie 与诊断秘密未嵌入此文档。", meta)))

    def draw_footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#71807E"))
        page_width = landscape(A4)[0] if settings["orientation"] == "landscape" else A4[0]
        canvas.drawCentredString(page_width / 2, 9 * mm, f"LearnNote · {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
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
        options={**settings, "include_toc": False},
    )
    title = html.escape(structured["title"])
    body: list[str] = []
    toc: list[str] = []
    heading_index = 0
    list_kind = ""
    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            body.append(f"</{list_kind}>")
            list_kind = ""
    for block in _content_blocks(structured["markdown"], structured["title"]):
        if block.kind == "heading":
            close_list()
            heading_index += 1
            anchor = f"section-{heading_index}"
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
                    rendered_rows.append("<tr>" + "".join(f"<{tag}>{_pdf_inline(cell)}</{tag}>" for cell in row) + "</tr>")
                body.append("<table>" + "".join(rendered_rows) + "</table>")
        elif block.kind == "image":
            close_list()
            path, caption = _task_image(task, block.text) if settings["include_images"] else (None, "")
            if path:
                body.append(f'<figure><img src="{_html_image_data(path)}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>')
            elif caption:
                body.append(f"<p class=\"image-note\">{html.escape(caption)}（图片未嵌入）</p>")
        elif block.kind == "bullet":
            if list_kind != "ul":
                close_list()
                list_kind = "ul"
                body.append("<ul>")
            body.append(f"<li>{_pdf_inline(block.text)}</li>")
        elif block.kind == "ordered":
            if list_kind != "ol":
                close_list()
                list_kind = "ol"
                body.append("<ol>")
            body.append(f"<li>{_pdf_inline(block.text)}</li>")
        elif block.kind == "code":
            close_list()
            body.append(f"<pre><code>{html.escape(_sanitize_export_text(block.text))}</code></pre>")
        else:
            close_list()
            body.append(f"<p>{_pdf_inline(block.text).replace(chr(10), '<br>')}</p>")
    close_list()
    rendered = body

    font_path = Path(__file__).resolve().parents[2] / "site" / "assets" / "fonts" / "learnnote-site-sans.woff2"
    font_face = ""
    font_name = "system Chinese fallback"
    warnings: list[str] = []
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
h1{{font-size:2em;line-height:1.3;margin:0 0 1.2em}}h2{{font-size:1.45em;margin:1.5em 0 .55em}}h3,h4{{margin:1.2em 0 .45em}}p{{margin:{settings['paragraph_before']}pt 0 {settings['paragraph_after']}pt}}.meta{{color:var(--muted);font-size:.85em}}a{{color:var(--accent)}}blockquote{{border-left:3px solid var(--line);padding:.2em 1em;color:var(--muted)}}pre{{background:#f1f5f3;border:1px solid var(--line);padding:1em;overflow:auto;font-family:Consolas,monospace}}code{{font-family:Consolas,monospace}}table{{width:100%;border-collapse:collapse;margin:1em 0}}th,td{{border:1px solid var(--line);padding:.55em;text-align:left;vertical-align:top}}th{{background:#edf4f1}}img{{max-width:100%;height:auto}}figure{{margin:1.1em 0}}figcaption,.image-note{{color:var(--muted);font-size:.82em}}.toc{{border:1px solid var(--line);padding:1em;margin:1em 0}}.toc ol{{margin:.5em 0 0;padding-left:1.5em}}.toc-level-3{{margin-left:1em}}footer{{margin-top:2em;color:var(--muted);font-size:.8em;border-top:1px solid var(--line);padding-top:1em}}"""
    document = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head><body><main><h1>{title}</h1>{source_html}{toc_html}{"".join(rendered)}<footer>由 LearnNote 在本机生成；原视频、Cookie 与诊断秘密未嵌入此文档。</footer></main></body></html>'
    return DocumentExport(
        content=document.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        suffix="html",
        font_name=font_name,
        warnings=warnings,
    )
