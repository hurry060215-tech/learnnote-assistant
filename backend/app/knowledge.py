from __future__ import annotations

import html
import hashlib
import json
import re
import sqlite3
from io import BytesIO
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import DATA_DIR, ensure_dirs
from .embeddings import semantic_rank
from .models import SourceEvidence
from .text_cleanup import (
    TEXT_NORMALIZATION_VERSION,
    TextDecodingError,
    canonicalize_unicode_text,
    decode_text_bytes,
    declared_text_encoding,
)


KNOWLEDGE_SCHEMA_VERSION = 1
MAX_IMPORTED_PDF_PAGES = 500
MAX_EXTRACTED_TEXT_CHARS = 5_000_000
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff-]{2,}")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._pre_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
        if self._hidden_depth:
            return
        tag = tag.lower()
        if tag == "pre":
            self.parts.append("\n\n```\n")
            self._pre_depth += 1
        elif not self._pre_depth:
            if re.fullmatch(r"h[1-6]", tag):
                self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
            elif tag in {"p", "div", "section", "article", "blockquote"}:
                self.parts.append("\n\n")
            elif tag == "li":
                self.parts.append("\n- ")
            elif tag == "br":
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"} and self._hidden_depth:
            self._hidden_depth -= 1
            return
        if self._hidden_depth:
            return
        if tag.lower() == "pre" and self._pre_depth:
            self._pre_depth -= 1
            self.parts.append("\n```\n\n")
        elif not self._pre_depth and (tag.lower() in {"p", "div", "section", "article", "blockquote"} or re.fullmatch(r"h[1-6]", tag.lower())):
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and (self._pre_depth or data.strip() or "\n" not in data):
            self.parts.append(data)


def _db_path() -> Path:
    return DATA_DIR / "library.sqlite3"


def preserve_raw_import(content: bytes, filename: str = "") -> dict[str, object]:
    """Store the exact uploaded bytes next to the decoded evidence metadata."""
    raw = bytes(content or b"")
    digest = hashlib.sha256(raw).hexdigest()
    suffix = re.sub(r"[^a-z0-9]+", "", Path(filename or "").suffix.lower())[:12]
    target = DATA_DIR / "raw-imports" / f"{digest}{suffix}"
    if not target.is_file():
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(raw)
            temporary.replace(target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ValueError("import_raw_storage_failed") from exc
    return {"sha256": digest, "byte_count": len(raw)}


def _raw_import_path(raw_sha256: str) -> Path:
    digest = str(raw_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("raw_import_missing")
    root = (DATA_DIR / "raw-imports").resolve()
    candidates = [path for path in root.glob(f"{digest}*") if path.is_file()]
    if len(candidates) != 1 or candidates[0].resolve().parent != root:
        raise ValueError("raw_import_missing")
    return candidates[0]


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    connection = sqlite3.connect(_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_evidence (
          evidence_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          source_type TEXT NOT NULL,
          title TEXT NOT NULL,
          source_uri TEXT NOT NULL,
          locator TEXT NOT NULL,
          text TEXT NOT NULL,
          task_id TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS source_evidence_task_idx ON source_evidence(task_id);
        """
    )
    try:
        connection.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS source_evidence_fts USING fts5(
               evidence_id UNINDEXED, title, source_uri, locator, text
            )"""
        )
    except sqlite3.OperationalError:
        pass
    return connection


def _fts_available(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_evidence_fts'").fetchone())


def _tokens(value: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(str(value or ""))]


def _fts_query(value: str) -> str:
    return " AND ".join(f'"{token.replace(chr(34), "")}"' for token in _tokens(value))


def add_evidence(evidence: SourceEvidence) -> SourceEvidence:
    item = evidence.model_copy(update={
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "evidence_id": evidence.evidence_id or uuid4().hex,
    })
    # Search projections may collapse whitespace, but canonical evidence must
    # retain code fences, paragraphs, tables and indentation for reading/export.
    text = str(item.text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ValueError("evidence_text_required")
    item = item.model_copy(update={"text": text[:2_000_000]})
    connection = _connect()
    try:
        connection.execute(
            """INSERT OR REPLACE INTO source_evidence
               (evidence_id, schema_version, source_type, title, source_uri, locator, text,
                task_id, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.evidence_id,
                item.schema_version,
                item.source_type,
                item.title[:500],
                item.source_uri[:1000],
                item.locator[:300],
                item.text,
                item.task_id[:128],
                json.dumps(item.metadata, ensure_ascii=False)[:20_000],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        if _fts_available(connection):
            connection.execute("DELETE FROM source_evidence_fts WHERE evidence_id = ?", (item.evidence_id,))
            connection.execute(
                "INSERT INTO source_evidence_fts(evidence_id, title, source_uri, locator, text) VALUES (?, ?, ?, ?, ?)",
                (item.evidence_id, item.title, item.source_uri, item.locator, item.text),
            )
        connection.commit()
    finally:
        connection.close()
    return item


def remove_task_evidence(task_id: str) -> None:
    if not task_id:
        return
    connection = _connect()
    try:
        ids = [row[0] for row in connection.execute("SELECT evidence_id FROM source_evidence WHERE task_id = ?", (task_id,))]
        connection.execute("DELETE FROM source_evidence WHERE task_id = ?", (task_id,))
        if _fts_available(connection):
            for evidence_id in ids:
                connection.execute("DELETE FROM source_evidence_fts WHERE evidence_id = ?", (evidence_id,))
        connection.commit()
    finally:
        connection.close()


def clear_task_evidence() -> None:
    connection = _connect()
    try:
        ids = [row[0] for row in connection.execute("SELECT evidence_id FROM source_evidence WHERE task_id != ''")]
        connection.execute("DELETE FROM source_evidence WHERE task_id != ''")
        if _fts_available(connection):
            for evidence_id in ids:
                connection.execute("DELETE FROM source_evidence_fts WHERE evidence_id = ?", (evidence_id,))
        connection.commit()
    finally:
        connection.close()


def remove_evidence(evidence_id: str) -> bool:
    connection = _connect()
    try:
        row = connection.execute("SELECT evidence_id FROM source_evidence WHERE evidence_id = ?", (str(evidence_id or "")[:128],)).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM source_evidence WHERE evidence_id = ?", (row[0],))
        if _fts_available(connection):
            connection.execute("DELETE FROM source_evidence_fts WHERE evidence_id = ?", (row[0],))
        connection.commit()
        return True
    finally:
        connection.close()


def search_evidence(query: str = "", limit: int = 12, mode: str = "lexical") -> list[dict[str, object]]:
    limit = max(1, min(int(limit or 12), 50))
    semantic_mode = str(mode or "lexical").lower() in {"embedding", "semantic", "local-embedding"}
    query_limit = 500 if semantic_mode else limit
    connection = _connect()
    try:
        term = _fts_query(query)
        if term and _fts_available(connection):
            try:
                rows = connection.execute(
                    """SELECT e.*, bm25(source_evidence_fts) AS score FROM source_evidence_fts f
                       JOIN source_evidence e ON e.evidence_id = f.evidence_id
                       WHERE source_evidence_fts MATCH ?
                       ORDER BY score ASC, e.created_at DESC LIMIT ?""",
                    (term, query_limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                like = f"%{str(query).strip()}%"
                rows = connection.execute(
                    "SELECT * FROM source_evidence WHERE title LIKE ? OR source_uri LIKE ? OR locator LIKE ? OR text LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (like, like, like, like, query_limit),
                ).fetchall()
        else:
            if term:
                like = f"%{str(query).strip()}%"
                rows = connection.execute(
                    "SELECT * FROM source_evidence WHERE title LIKE ? OR source_uri LIKE ? OR locator LIKE ? OR text LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (like, like, like, like, query_limit),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM source_evidence ORDER BY created_at DESC LIMIT ?", (query_limit,)).fetchall()
    finally:
        connection.close()
    result: list[dict[str, object]] = []
    for row in rows:
        result.append({
            "evidence_id": row["evidence_id"],
            "schema_version": int(row["schema_version"]),
            "source_type": row["source_type"],
            "title": row["title"],
            "source_uri": row["source_uri"],
            "locator": row["locator"],
            "text": row["text"],
            "task_id": row["task_id"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "score": float(row["score"]) if "score" in row.keys() and row["score"] is not None else 0.0,
        })
    if semantic_mode:
        return semantic_rank(query, result, limit)
    return result


def evidence_for_task(task_id: str, limit: int = 200) -> list[dict[str, object]]:
    if not str(task_id or "").strip():
        return []
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT * FROM source_evidence WHERE task_id = ? ORDER BY created_at ASC LIMIT ?",
            (str(task_id or "")[:128], max(1, min(int(limit or 200), 500))),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "evidence_id": row["evidence_id"], "schema_version": int(row["schema_version"]),
            "source_type": row["source_type"], "title": row["title"], "source_uri": row["source_uri"],
            "locator": row["locator"], "text": row["text"], "task_id": row["task_id"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }
        for row in rows
    ]


def evidence_by_ids(evidence_ids: list[str], limit: int = 100) -> list[dict[str, object]]:
    ordered = []
    seen = set()
    for value in evidence_ids:
        item = str(value or "")[:128]
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
        if len(ordered) >= max(1, min(int(limit or 100), 500)):
            break
    if not ordered:
        return []
    connection = _connect()
    try:
        placeholders = ",".join("?" for _ in ordered)
        rows = connection.execute(
            f"SELECT * FROM source_evidence WHERE evidence_id IN ({placeholders})",
            tuple(ordered),
        ).fetchall()
    finally:
        connection.close()
    by_id = {str(row["evidence_id"]): row for row in rows}
    return [
        {
            "evidence_id": row["evidence_id"], "schema_version": int(row["schema_version"]),
            "source_type": row["source_type"], "title": row["title"], "source_uri": row["source_uri"],
            "locator": row["locator"], "text": row["text"], "task_id": row["task_id"],
            "metadata": json.loads(row["metadata_json"] or "{}"), "created_at": row["created_at"],
        }
        for evidence_id in ordered
        if (row := by_id.get(evidence_id)) is not None
    ]


def evidence_ids_for_task(task_id: str) -> set[str]:
    connection = _connect()
    try:
        return {str(row[0]) for row in connection.execute("SELECT evidence_id FROM source_evidence WHERE task_id=?", (task_id,))}
    finally:
        connection.close()


def answer_from_evidence(question: str, limit: int = 6, mode: str = "lexical") -> dict[str, object]:
    hits = search_evidence(question, limit, mode)
    if not hits:
        return {
            "answer": "资料库中没有找到足够的证据，未生成无依据答案。",
            "grounded": False,
            "citations": [],
            "results": [],
            "retrieval_method": mode,
        }
    snippets = []
    citations = []
    for item in hits:
        text = str(item["text"])
        snippets.append(f"[{item['title']} · {item['locator']}] {text[:360]}")
        citations.append({
            "evidence_id": item["evidence_id"],
            "title": item["title"],
            "source_type": item["source_type"],
            "locator": item["locator"],
            "source_uri": item["source_uri"],
            "source_kind": "task" if item.get("task_id") else "material" if item.get("metadata", {}).get("material_id") else "",
            "source_id": item.get("task_id") or item.get("metadata", {}).get("material_id") or "",
            "start": item.get("metadata", {}).get("start") if isinstance(item.get("metadata"), dict) and isinstance(item.get("metadata", {}).get("start"), (int, float)) else None,
            "end": item.get("metadata", {}).get("end") if isinstance(item.get("metadata"), dict) and isinstance(item.get("metadata", {}).get("end"), (int, float)) else None,
        })
    return {
        "answer": "根据资料库中的可追溯证据：\n" + "\n".join(snippets),
        "grounded": True,
        "citations": citations,
        "results": hits,
        "retrieval_method": mode,
    }


def extract_import_text_with_metadata(filename: str, content: bytes, content_type: str = "", encoding: str = "") -> tuple[str, str, dict[str, object]]:
    suffix = Path(filename or "").suffix.lower()
    declared_encoding = declared_text_encoding(
        content_type,
        content,
        html_hint=suffix in {".html", ".htm"},
    )
    if suffix == ".pdf" or "pdf" in content_type.lower():
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content))
            if len(reader.pages) > MAX_IMPORTED_PDF_PAGES:
                raise ValueError("pdf_page_limit_exceeded")
            pages = []
            extracted_chars = 0
            replacement_character_count = 0
            for index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                replacement_character_count += page_text.count("\ufffd")
                try:
                    page_text = canonicalize_unicode_text(page_text)
                except TextDecodingError as exc:
                    raise ValueError("text_mojibake_detected") from exc
                extracted_chars += len(page_text)
                if extracted_chars > MAX_EXTRACTED_TEXT_CHARS:
                    raise ValueError("extracted_text_too_large")
                pages.append(f"[第 {index} 页]\n{page_text}")
            return "\n\n".join(pages), "pdf", {
                "encoding": "pdf-text",
                "decoding_source": "pypdf",
                "encoding_source": "pypdf",
                "encoding_confidence": "not_applicable",
                "declared_encoding": "",
                "replacement_character_count": replacement_character_count,
                "normalization_version": TEXT_NORMALIZATION_VERSION,
                "page_count": len(reader.pages),
                "extracted_page_count": len(pages),
                "ocr_required": not any(page.strip() for page in pages),
            }
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("pdf_text_extraction_unavailable") from exc
    try:
        decoded_info = decode_text_bytes(
            content,
            source=Path(filename or "document").name,
            encoding=encoding,
            declared_encoding=declared_encoding,
        )
    except TextDecodingError as exc:
        code = "text_mojibake_detected" if str(exc).startswith("text_mojibake_detected") else "text_encoding_unsupported"
        raise ValueError(code) from exc
    if len(decoded_info.text) > MAX_EXTRACTED_TEXT_CHARS:
        raise ValueError("extracted_text_too_large")
    if suffix in {".html", ".htm"} or "html" in content_type.lower():
        parser = _VisibleTextParser()
        parser.feed(decoded_info.text)
        parser.close()
        return "".join(parser.parts).strip(), "webpage", {
            "encoding": decoded_info.encoding,
            "decoding_source": "strict-lossless",
            "encoding_source": decoded_info.encoding_source,
            "encoding_confidence": decoded_info.encoding_confidence,
            "declared_encoding": declared_encoding,
            "replacement_character_count": decoded_info.replacement_character_count,
            "normalization_version": decoded_info.normalization_version,
            "encoding_repaired": decoded_info.repaired,
            "mojibake_score": decoded_info.mojibake_score,
        }
    return decoded_info.text, "markdown" if suffix in {".md", ".markdown"} else "task", {
        "encoding": decoded_info.encoding,
        "decoding_source": "strict-lossless",
        "encoding_source": decoded_info.encoding_source,
        "encoding_confidence": decoded_info.encoding_confidence,
        "declared_encoding": declared_encoding,
        "replacement_character_count": decoded_info.replacement_character_count,
        "normalization_version": decoded_info.normalization_version,
        "encoding_repaired": decoded_info.repaired,
        "mojibake_score": decoded_info.mojibake_score,
    }


def extract_import_text(filename: str, content: bytes, content_type: str = "", encoding: str = "") -> tuple[str, str]:
    text, source_type, _metadata = extract_import_text_with_metadata(filename, content, content_type, encoding)
    return text, source_type


def redecode_evidence(evidence_id: str, encoding: str = "") -> dict[str, object]:
    """Re-decode an imported text evidence item from its preserved raw bytes."""

    items = evidence_by_ids([evidence_id], limit=1)
    if not items:
        raise ValueError("evidence_not_found")
    item = items[0]
    metadata = dict(item.get("metadata") or {})
    if item.get("source_type") == "pdf":
        raise ValueError("pdf_redecode_not_supported")
    raw_path = _raw_import_path(str(metadata.get("raw_sha256") or ""))
    raw = raw_path.read_bytes()
    filename = str(metadata.get("filename") or raw_path.name)
    content_type = str(metadata.get("content_type") or "")
    text, _source_type, decode_metadata = extract_import_text_with_metadata(filename, raw, content_type, encoding=encoding)
    if not str(text or "").strip():
        raise ValueError("evidence_text_required")
    metadata.update(decode_metadata)
    metadata.update({
        "decoding_hint": str(encoding or "")[:40],
        "source_revision": hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
        "redecoded": True,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_byte_count": len(raw),
    })
    connection = _connect()
    try:
        connection.execute(
            "UPDATE source_evidence SET text=?, metadata_json=? WHERE evidence_id=?",
            (str(text)[:2_000_000], json.dumps(metadata, ensure_ascii=False)[:20_000], str(evidence_id)[:128]),
        )
        if _fts_available(connection):
            connection.execute("DELETE FROM source_evidence_fts WHERE evidence_id=?", (str(evidence_id)[:128],))
            connection.execute(
                "INSERT INTO source_evidence_fts(evidence_id,title,source_uri,locator,text) VALUES (?,?,?,?,?)",
                (str(evidence_id)[:128], item.get("title", ""), item.get("source_uri", ""), item.get("locator", ""), str(text)[:2_000_000]),
            )
        connection.commit()
    finally:
        connection.close()
    refreshed = evidence_by_ids([evidence_id], limit=1)
    if not refreshed:
        raise ValueError("evidence_not_found")
    return refreshed[0]
