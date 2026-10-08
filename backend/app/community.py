from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import unicodedata
import sqlite3
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from .config import DATA_DIR, ensure_dirs


COMMUNITY_CONTEXT_SCHEMA_VERSION = 1
COMMUNITY_CONTEXT_MAX_ITEMS_PER_REQUEST = 500
COMMUNITY_CONTEXT_MAX_REQUEST_CHARS = 500_000
COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK = 10_000
COMMUNITY_CONTEXT_MAX_ITEMS_TOTAL = 100_000
_lock = threading.RLock()


def _db_path():
    return DATA_DIR / "community.sqlite3"


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    connection = sqlite3.connect(_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS community_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS community_context_items (
          item_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          task_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          timestamp_seconds REAL,
          author_label TEXT NOT NULL,
          source_uri TEXT NOT NULL,
          fingerprint TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(task_id, fingerprint)
        );
        CREATE INDEX IF NOT EXISTS community_context_task_idx
          ON community_context_items(task_id, created_at);
        INSERT OR IGNORE INTO community_meta(key, value) VALUES ('enabled', '0');
        INSERT OR REPLACE INTO community_meta(key, value) VALUES ('schema_version', '1');
        """
    )
    connection.commit()
    return connection


def _safe_source_uri(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    try:
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return ""
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".localhost", ".local", ".lan", ".internal", ".home", ".corp")):
            return ""
        try:
            if not ipaddress.ip_address(hostname).is_global:
                return ""
        except ValueError:
            pass
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme.lower(), hostname + port, parsed.path[:800], "", ""))[:1000]
    except (TypeError, ValueError):
        return ""


def community_settings() -> dict[str, object]:
    with _lock:
        connection = _connect()
        try:
            row = connection.execute("SELECT value FROM community_meta WHERE key = 'enabled'").fetchone()
            count = int(connection.execute("SELECT COUNT(*) FROM community_context_items").fetchone()[0])
        finally:
            connection.close()
    return {
        "schema_version": COMMUNITY_CONTEXT_SCHEMA_VERSION,
        "enabled": bool(int(row[0])) if row else False,
        "default_enabled": False,
        "stored_item_count": count,
        "storage": "local-only",
        "network_fetch_performed": False,
        "evidence_eligible": False,
        "epistemic_role": "community_perspective_not_source_evidence",
    }


def set_community_enabled(enabled: bool) -> dict[str, object]:
    with _lock:
        connection = _connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO community_meta(key, value) VALUES ('enabled', ?)",
                ("1" if bool(enabled) else "0",),
            )
            connection.commit()
        finally:
            connection.close()
    return community_settings()


def _filter_community_text(value: str) -> str:
    """Conservative local filtering, never used to rewrite transcript evidence."""
    text = " ".join(str(value or "")[:8000].split()).strip()[:2000]
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    if re.fullmatch(r"(?:播放|暂停|全屏|退出全屏|倍速|清晰度|发送弹幕|play|pause|fullscreen|send danmaku|[!！?？。\d ])+", normalized):
        return ""
    if re.search(r"(?:加[微vV]|加群|扫码|代写|刷单|返利|优惠券|推广链接|buy now|promo code|earn money|subscribe to my)", normalized):
        return ""
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱已省略]", text)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", "[联系方式已省略]", text)
    text = re.sub(r"(?i)(?:https?://|www\.)\S+", "[链接已省略]", text)
    text = re.sub(r"(?<!\w)@[\w.\-]{2,}", "[用户已省略]", text)
    return text


def _perspective_groups(items: list[dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"questions": [], "disagreements": [], "perspectives": []}
    for item in items:
        text = str(item.get("text") or "")
        category = "questions" if re.search(r"[?？]|为什么|如何|怎么|what |why |how ", text, re.I) else "disagreements" if re.search(r"不同意|有争议|错误|不正确|disagree|incorrect|not correct", text, re.I) else "perspectives"
        groups[category].append(str(item["item_id"]))
    return groups


def add_community_context(task_id: str, raw_items: list[dict]) -> dict[str, object]:
    settings = community_settings()
    if not settings["enabled"]:
        raise ValueError("community_context_disabled")
    if not str(task_id or "").strip():
        raise ValueError("task_id_required")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("community_items_required")
    if len(raw_items) > COMMUNITY_CONTEXT_MAX_ITEMS_PER_REQUEST:
        raise ValueError("community_items_too_many")
    request_chars = sum(len(str(item.get("text") or "")[:20_001]) for item in raw_items if isinstance(item, dict))
    if request_chars > COMMUNITY_CONTEXT_MAX_REQUEST_CHARS:
        raise ValueError("community_content_too_large")

    now = datetime.now(timezone.utc).isoformat()
    created: list[dict[str, object]] = []
    deduplicated = 0
    filtered = 0
    with _lock:
        connection = _connect()
        try:
            task_count = int(connection.execute("SELECT COUNT(*) FROM community_context_items WHERE task_id = ?", (str(task_id)[:128],)).fetchone()[0])
            total_count = int(connection.execute("SELECT COUNT(*) FROM community_context_items").fetchone()[0])
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                kind = str(raw.get("kind") or "comment")[:32].strip().lower()
                if kind not in {"comment", "danmaku"}:
                    continue
                text = _filter_community_text(raw.get("text"))
                if not text:
                    filtered += 1
                    continue
                timestamp = raw.get("timestamp_seconds")
                try:
                    timestamp_value = float(timestamp) if timestamp is not None else None
                    timestamp_seconds = min(604800.0, max(0.0, timestamp_value)) if timestamp_value is not None and math.isfinite(timestamp_value) else None
                except (TypeError, ValueError):
                    timestamp_seconds = None
                # Author identity is unnecessary for a learning perspective.
                author_label = ""
                source_uri = _safe_source_uri(str(raw.get("source_uri") or "")[:2000])
                fingerprint = hashlib.sha256(
                    f"{kind}\0{unicodedata.normalize('NFKC', text).casefold()}".encode("utf-8")
                ).hexdigest()
                if connection.execute(
                    "SELECT 1 FROM community_context_items WHERE task_id=? AND (fingerprint=? OR (kind=? AND text=?)) LIMIT 1",
                    (str(task_id)[:128], fingerprint, kind, text),
                ).fetchone():
                    deduplicated += 1
                    continue
                if task_count + len(created) >= COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK or total_count + len(created) >= COMMUNITY_CONTEXT_MAX_ITEMS_TOTAL:
                    raise ValueError("community_storage_quota_exceeded")
                item_id = uuid4().hex
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO community_context_items
                       (item_id, schema_version, task_id, kind, text, timestamp_seconds,
                        author_label, source_uri, fingerprint, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item_id,
                        COMMUNITY_CONTEXT_SCHEMA_VERSION,
                        str(task_id)[:128],
                        kind,
                        text,
                        timestamp_seconds,
                        author_label,
                        source_uri,
                        fingerprint,
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    deduplicated += 1
                    continue
                created.append({
                    "item_id": item_id,
                    "schema_version": COMMUNITY_CONTEXT_SCHEMA_VERSION,
                    "task_id": str(task_id)[:128],
                    "kind": kind,
                    "text": text,
                    "timestamp_seconds": timestamp_seconds,
                    "author_label": author_label,
                    "source_uri": source_uri,
                    "created_at": now,
                })
            if not created and deduplicated == 0:
                raise ValueError("community_items_invalid")
            connection.commit()
        finally:
            connection.close()
    return {
        "schema_version": COMMUNITY_CONTEXT_SCHEMA_VERSION,
        "task_id": str(task_id)[:128],
        "items": created,
        "stored_count": len(created),
        "deduplicated_count": deduplicated,
        "filtered_count": filtered,
        "author_identity_stored": False,
        "evidence_eligible": False,
        "epistemic_role": "community_perspective_not_source_evidence",
    }


def list_community_context(task_id: str, limit: int = 500) -> dict[str, object]:
    cap = max(1, min(int(limit or 500), COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK))
    with _lock:
        connection = _connect()
        try:
            rows = connection.execute(
                "SELECT * FROM community_context_items WHERE task_id = ? ORDER BY created_at ASC LIMIT ?",
                (str(task_id or "")[:128], cap),
            ).fetchall()
        finally:
            connection.close()
    groups = _perspective_groups([dict(row) for row in rows])
    return {
        "schema_version": COMMUNITY_CONTEXT_SCHEMA_VERSION,
        "task_id": str(task_id or "")[:128],
        "enabled": bool(community_settings()["enabled"]),
        "groups": groups,
        "grouping": "local_keyword_hints_not_factual_classification",
        "author_identity_exposed": False,
        "items": [
            {
                "item_id": row["item_id"],
                "schema_version": int(row["schema_version"]),
                "task_id": row["task_id"],
                "kind": row["kind"],
                "text": row["text"],
                "timestamp_seconds": row["timestamp_seconds"],
                "author_label": "",
                "source_uri": row["source_uri"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "evidence_eligible": False,
        "epistemic_role": "community_perspective_not_source_evidence",
    }


def clear_community_context(task_id: str) -> int:
    with _lock:
        connection = _connect()
        try:
            cursor = connection.execute(
                "DELETE FROM community_context_items WHERE task_id = ?",
                (str(task_id or "")[:128],),
            )
            connection.commit()
            return max(0, int(cursor.rowcount))
        finally:
            connection.close()


def sample_community_context(task_id: str, limit: int = 20, seed: str = "") -> dict[str, object]:
    cap = max(1, min(int(limit or 20), 200))
    source = list_community_context(task_id, 2000)["items"]
    if seed:
        offset = int(hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:8], 16) % max(1, len(source))
        source = source[offset:] + source[:offset]
    return {
        "schema_version": COMMUNITY_CONTEXT_SCHEMA_VERSION,
        "task_id": str(task_id or "")[:128],
        "items": source[:cap],
        "sampled": True,
        "seed": str(seed or ""),
        "evidence_eligible": False,
        "epistemic_role": "community_perspective_not_source_evidence",
    }


def delete_community_item(task_id: str, item_id: str) -> bool:
    with _lock:
        connection = _connect()
        try:
            cursor = connection.execute(
                "DELETE FROM community_context_items WHERE task_id = ? AND item_id = ?",
                (str(task_id or "")[:128], str(item_id or "")[:128]),
            )
            connection.commit()
            return bool(cursor.rowcount)
        finally:
            connection.close()


def clear_all_community_context() -> int:
    with _lock:
        connection = _connect()
        try:
            count = int(connection.execute("SELECT COUNT(*) FROM community_context_items").fetchone()[0])
            connection.execute("DELETE FROM community_context_items")
            connection.commit()
            return count
        finally:
            connection.close()
