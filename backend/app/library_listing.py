"""Bounded standalone-document browsing, independent of task registrations."""
from __future__ import annotations

import base64
import binascii
import json

from . import library


def browse_materials(*, limit: int = 100, query: str = "", cursor: str = "") -> dict:
    query = query.strip()[:200]
    cap = max(1, min(int(limit), 100))
    where = "linked_task_id = '' AND instr(casefold(title), casefold(?)) > 0"
    parameters: list = [query]
    if cursor:
        try:
            if len(cursor) > 2048:
                raise ValueError()
            marker = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if not isinstance(marker, list) or len(marker) != 3 or marker[0] != query or not all(isinstance(value, str) for value in marker):
                raise ValueError()
        except (ValueError, UnicodeError, TypeError, binascii.Error) as exc:
            raise ValueError("material_cursor_invalid") from exc
        where += " AND (updated_at < ? OR (updated_at = ? AND material_id < ?))"
        parameters.extend([marker[1], marker[1], marker[2]])
    with library._lock:
        connection, _ = library._connect()
        try:
            connection.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
            total = connection.execute("SELECT count(*) FROM library_materials WHERE linked_task_id = ''").fetchone()[0]
            matched_total = connection.execute("SELECT count(*) FROM library_materials WHERE linked_task_id = '' AND instr(casefold(title), casefold(?)) > 0", (query,)).fetchone()[0]
            rows = connection.execute(f"SELECT * FROM library_materials WHERE {where} ORDER BY updated_at DESC, material_id DESC LIMIT ?", (*parameters, cap + 1)).fetchall()
        finally:
            connection.close()
    has_more = len(rows) > cap
    rows = rows[:cap]
    next_cursor = base64.urlsafe_b64encode(json.dumps([query, rows[-1]["updated_at"], rows[-1]["material_id"]]).encode()).decode() if has_more else ""
    return {"schema_version": 1, "materials": [library._material_row(row) for row in rows],
            "total": total, "matched_total": matched_total, "has_more": has_more, "next_cursor": next_cursor}
