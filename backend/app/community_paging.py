"""Bounded read-only pages of saved opinions; cursors bind an immutable snapshot."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3

from . import community

PAGE_SIZE = 500
_PROCESS_NONCE = secrets.token_hex(16)
_SOURCE_FIELDS = {"id", "created_at", "source_type", "mode", "page_url", "source_identity",
                  "control_generation", "retry_count", "source_task_id", "learning_range",
                  "status", "transcript_path", "error_code", "summary_source", "updated_at"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _cursor(value, task_id, limit):
    if not value:
        return None
    try:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError
        decoded = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (not isinstance(decoded, dict) or set(decoded) != {"v", "task", "revision", "offset", "limit"}
                or type(decoded["v"]) is not int or decoded["v"] != 1
                or type(decoded["offset"]) is not int or not 0 <= decoded["offset"] <= community.COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK
                or type(decoded["limit"]) is not int or decoded["limit"] != limit
                or not isinstance(decoded["revision"], str) or len(decoded["revision"]) != 64):
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError):
        raise ValueError("community_page_invalid") from None
    if decoded["task"] != task_id:
        raise ValueError("community_page_changed")
    return decoded


def community_page_source(task):
    return task.model_dump(mode="json", include=_SOURCE_FIELDS)


def list_community_page(task, limit: int = PAGE_SIZE, cursor: str = "") -> dict:
    if type(limit) is not int or not 1 <= limit <= PAGE_SIZE:
        raise ValueError("community_page_invalid")
    after = _cursor(cursor, task.id, limit)
    with community._lock:
        source = community_page_source(task)
        digest = hashlib.sha256(_json([_PROCESS_NONCE, source, community.community_preview_generation()]))
        connection = None
        enabled, total, rows = False, 0, []
        try:
            if community._db_path().is_file():
                connection = sqlite3.connect(community._db_path().resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                setting = connection.execute("SELECT value FROM community_meta WHERE key='enabled'").fetchone()
                enabled = bool(int(setting[0])) if setting else False
                # Stream only bounded identity metadata, never all opinion text.
                metadata = connection.execute(
                    "SELECT item_id, created_at, fingerprint, source_uri, kind, timestamp_seconds, schema_version "
                    "FROM community_context_items WHERE task_id=? ORDER BY created_at, item_id LIMIT ?",
                    (task.id, community.COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK + 1))
                for row in metadata:
                    total += 1
                    if total > community.COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK:
                        raise ValueError("community_page_invalid")
                    digest.update(_json(list(row)))
            digest.update(_json([enabled, total]))
            revision = digest.hexdigest()
            if after and after["revision"] != revision:
                raise ValueError("community_page_changed")
            offset = after["offset"] if after else 0
            if offset > total:
                raise ValueError("community_page_invalid")
            if connection:
                rows = connection.execute(
                    "SELECT * FROM community_context_items WHERE task_id=? ORDER BY created_at, item_id LIMIT ? OFFSET ?",
                    (task.id, limit, offset)).fetchall()
            def token(start):
                return base64.urlsafe_b64encode(_json({"v": 1, "task": task.id, "revision": revision,
                                                      "offset": start, "limit": limit})).decode("ascii")
            end = offset + len(rows)
            return {**community.community_context_projection(task.id, rows, enabled), "groups_scope": "current_page_only",
                    "total_count": total, "returned_count": len(rows), "offset": offset, "limit": limit,
                    "revision": revision, "has_more": end < total, "next_cursor": token(end) if end < total else None,
                    "previous_cursor": token(max(0, offset - limit)) if offset else None}
        except sqlite3.Error:
            raise ValueError("community_page_unavailable") from None
        finally:
            if connection:
                connection.close()
