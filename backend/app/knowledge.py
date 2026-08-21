from __future__ import annotations

import html
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


KNOWLEDGE_SCHEMA_VERSION = 1
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff-]{2,}")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _db_path() -> Path:
    return DATA_DIR / "library.sqlite3"


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
    text = " ".join(str(item.text or "").split()).strip()
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
        })
    return {
        "answer": "根据资料库中的可追溯证据：\n" + "\n".join(snippets),
        "grounded": True,
        "citations": citations,
        "results": hits,
        "retrieval_method": mode,
    }


def extract_import_text(filename: str, content: bytes, content_type: str = "") -> tuple[str, str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf" or "pdf" in content_type.lower():
        try:
            from pypdf import PdfReader

            reader = PdfReader(Path(filename)) if Path(filename).is_file() else PdfReader(BytesIO(content))
            pages = []
            for index, page in enumerate(reader.pages, start=1):
                pages.append(f"[第 {index} 页]\n{page.extract_text() or ''}")
            return "\n\n".join(pages), "pdf"
        except Exception as exc:
            raise ValueError("pdf_text_extraction_unavailable") from exc
    decoded = content.decode("utf-8", errors="replace")
    if suffix in {".html", ".htm"} or "html" in content_type.lower():
        parser = _VisibleTextParser()
        parser.feed(decoded)
        parser.close()
        return " ".join(" ".join(parser.parts).split()), "webpage"
    return decoded, "markdown" if suffix in {".md", ".markdown"} else "task"
