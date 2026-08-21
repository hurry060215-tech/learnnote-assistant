from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .config import DATA_DIR, ensure_dirs
from .models import SourceEvidence, StudyCard


STUDY_SCHEMA_VERSION = 1


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    connection = sqlite3.connect(DATA_DIR / "study.sqlite3", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS study_cards (
           card_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, front TEXT NOT NULL,
           back TEXT NOT NULL, source_evidence_ids TEXT NOT NULL, status TEXT NOT NULL,
           due_at TEXT NOT NULL, stability REAL NOT NULL, difficulty REAL NOT NULL,
           reps INTEGER NOT NULL, lapses INTEGER NOT NULL, last_reviewed_at TEXT NOT NULL
        )"""
    )
    return connection


def _row_to_card(row: sqlite3.Row) -> StudyCard:
    return StudyCard(
        schema_version=int(row["schema_version"]),
        card_id=row["card_id"], front=row["front"], back=row["back"],
        source_evidence_ids=json.loads(row["source_evidence_ids"] or "[]"),
        status=row["status"], due_at=row["due_at"], stability=float(row["stability"]),
        difficulty=float(row["difficulty"]), reps=int(row["reps"]), lapses=int(row["lapses"]),
        last_reviewed_at=row["last_reviewed_at"],
    )


def propose_cards(evidence: list[SourceEvidence], limit: int = 20) -> list[StudyCard]:
    proposals: list[StudyCard] = []
    for item in evidence:
        paragraphs = [part.strip() for part in item.text.split("\n") if len(part.strip()) >= 20]
        for paragraph in paragraphs[: max(1, limit - len(proposals))]:
            proposals.append(StudyCard(
                card_id=uuid4().hex,
                front=f"{item.title or '这份资料'}：这段内容的核心是什么？",
                back=paragraph[:4000],
                source_evidence_ids=[item.evidence_id] if item.evidence_id else [],
            ))
        if len(proposals) >= limit:
            break
    return proposals


def save_cards(cards: list[StudyCard]) -> list[StudyCard]:
    now = datetime.now(timezone.utc).isoformat()
    stored: list[StudyCard] = []
    connection = _connect()
    try:
        for card in cards:
            item = card.model_copy(update={
                "schema_version": STUDY_SCHEMA_VERSION,
                "card_id": card.card_id or uuid4().hex,
                "status": "active" if card.status == "proposed" else card.status,
                "due_at": card.due_at or now,
            })
            connection.execute(
                """INSERT OR REPLACE INTO study_cards
                   (card_id, schema_version, front, back, source_evidence_ids, status, due_at,
                    stability, difficulty, reps, lapses, last_reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.card_id, item.schema_version, item.front, item.back,
                 json.dumps(item.source_evidence_ids, ensure_ascii=False), item.status, item.due_at,
                 item.stability, item.difficulty, item.reps, item.lapses, item.last_reviewed_at),
            )
            stored.append(item)
        connection.commit()
    finally:
        connection.close()
    return stored


def due_cards(limit: int = 50) -> list[StudyCard]:
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT * FROM study_cards WHERE status = 'active' AND (due_at = '' OR due_at <= ?) ORDER BY due_at ASC LIMIT ?",
            (now, max(1, min(int(limit or 50), 200))),
        ).fetchall()
    finally:
        connection.close()
    return [_row_to_card(row) for row in rows]


def list_cards(status: str = "", limit: int = 200) -> list[StudyCard]:
    connection = _connect()
    try:
        if status in {"active", "suspended", "deleted"}:
            rows = connection.execute("SELECT * FROM study_cards WHERE status = ? ORDER BY due_at ASC LIMIT ?", (status, max(1, min(int(limit or 200), 500)))).fetchall()
        else:
            rows = connection.execute("SELECT * FROM study_cards ORDER BY due_at ASC LIMIT ?", (max(1, min(int(limit or 200), 500)),)).fetchall()
    finally:
        connection.close()
    return [_row_to_card(row) for row in rows]


def set_card_status(card_id: str, status: str) -> StudyCard:
    if status not in {"active", "suspended", "deleted"}:
        raise ValueError("invalid_status")
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone()
        if row is None:
            raise ValueError("card_not_found")
        connection.execute("UPDATE study_cards SET status = ? WHERE card_id = ?", (status, card_id))
        connection.commit()
        return _row_to_card(connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone())
    finally:
        connection.close()


def review_card(card_id: str, rating: int) -> StudyCard:
    if rating not in {1, 2, 3, 4}:
        raise ValueError("invalid_rating")
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone()
        if row is None:
            raise ValueError("card_not_found")
        card = _row_to_card(row)
        now = datetime.now(timezone.utc)
        if rating == 1:
            interval = timedelta(minutes=10)
            stability = max(1.0, card.stability * 0.5)
            lapses = card.lapses + 1
        elif rating == 2:
            interval = timedelta(days=max(1, round(card.stability)))
            stability = max(1.0, card.stability * 1.2)
            lapses = card.lapses
        elif rating == 3:
            interval = timedelta(days=max(1, round(card.stability * 1.8)))
            stability = card.stability * 1.8
            lapses = card.lapses
        else:
            interval = timedelta(days=max(2, round(card.stability * 2.5)))
            stability = card.stability * 2.5
            lapses = card.lapses
        updated = card.model_copy(update={
            "due_at": (now + interval).isoformat(),
            "stability": round(min(stability, 3650.0), 4),
            "difficulty": round(max(1.0, min(10.0, card.difficulty + (0.5 if rating == 1 else -0.15 if rating == 4 else 0))), 4),
            "reps": card.reps + 1,
            "lapses": lapses,
            "last_reviewed_at": now.isoformat(),
        })
        connection.execute(
            "UPDATE study_cards SET due_at=?, stability=?, difficulty=?, reps=?, lapses=?, last_reviewed_at=? WHERE card_id=?",
            (updated.due_at, updated.stability, updated.difficulty, updated.reps, updated.lapses, updated.last_reviewed_at, card_id),
        )
        connection.commit()
        return updated
    finally:
        connection.close()
