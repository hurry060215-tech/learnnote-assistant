from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fsrs import Card as FsrsCard
from fsrs import Rating as FsrsRating
from fsrs import Scheduler as FsrsScheduler
from fsrs import State as FsrsState

from .config import DATA_DIR, ensure_dirs
from .models import SourceEvidence, StudyCard


STUDY_SCHEMA_VERSION = 2
FSRS_ALGORITHM = "fsrs-6.3.2"
_SCHEDULER = FsrsScheduler(enable_fuzzing=False)


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
           reps INTEGER NOT NULL, lapses INTEGER NOT NULL, last_reviewed_at TEXT NOT NULL,
           fsrs_state TEXT NOT NULL DEFAULT 'Learning', step INTEGER NOT NULL DEFAULT 0
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS study_reviews (
           review_id INTEGER PRIMARY KEY AUTOINCREMENT,
           card_id TEXT NOT NULL,
           rating INTEGER NOT NULL,
           reviewed_at TEXT NOT NULL,
           due_at TEXT NOT NULL,
           stability REAL NOT NULL,
           difficulty REAL NOT NULL
        )"""
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(study_cards)").fetchall()}
    if "fsrs_state" not in columns:
        connection.execute("ALTER TABLE study_cards ADD COLUMN fsrs_state TEXT NOT NULL DEFAULT 'Learning'")
    if "step" not in columns:
        connection.execute("ALTER TABLE study_cards ADD COLUMN step INTEGER NOT NULL DEFAULT 0")
    connection.commit()
    return connection


def _row_to_card(row: sqlite3.Row) -> StudyCard:
    return StudyCard(
        schema_version=max(int(row["schema_version"]), STUDY_SCHEMA_VERSION), algorithm=FSRS_ALGORITHM,
        card_id=row["card_id"], front=row["front"], back=row["back"],
        source_evidence_ids=json.loads(row["source_evidence_ids"] or "[]"),
        status=row["status"], due_at=row["due_at"], stability=float(row["stability"]),
        difficulty=float(row["difficulty"]), reps=int(row["reps"]), lapses=int(row["lapses"]),
        last_reviewed_at=row["last_reviewed_at"],
        fsrs_state=str(row["fsrs_state"] or "Learning"), step=int(row["step"] or 0),
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
                "algorithm": FSRS_ALGORITHM,
                "card_id": card.card_id or uuid4().hex,
                "status": "active" if card.status == "proposed" else card.status,
                "due_at": card.due_at or now,
            })
            connection.execute(
                """INSERT OR REPLACE INTO study_cards
                   (card_id, schema_version, front, back, source_evidence_ids, status, due_at,
                    stability, difficulty, reps, lapses, last_reviewed_at, fsrs_state, step)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.card_id, item.schema_version, item.front, item.back,
                 json.dumps(item.source_evidence_ids, ensure_ascii=False), item.status, item.due_at,
                 item.stability, item.difficulty, item.reps, item.lapses, item.last_reviewed_at,
                 item.fsrs_state, int(item.step or 0)),
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
        state = getattr(FsrsState, card.fsrs_state, FsrsState.Learning)
        due = _parse_datetime(card.due_at) or now
        last_review = _parse_datetime(card.last_reviewed_at)
        fsrs_card = FsrsCard(
            card_id=int(hashlib.sha256(card.card_id.encode("utf-8")).hexdigest()[:15], 16),
            state=state,
            step=card.step,
            stability=card.stability,
            difficulty=card.difficulty,
            due=due,
            last_review=last_review,
        )
        next_card, _review_log = _SCHEDULER.review_card(fsrs_card, FsrsRating(rating), review_datetime=now)
        lapses = card.lapses + (1 if rating == 1 else 0)
        updated = card.model_copy(update={
            "schema_version": STUDY_SCHEMA_VERSION,
            "algorithm": FSRS_ALGORITHM,
            "due_at": next_card.due.astimezone(timezone.utc).isoformat(),
            "stability": round(float(next_card.stability or card.stability), 4),
            "difficulty": round(float(next_card.difficulty or card.difficulty), 4),
            "fsrs_state": next_card.state.name,
            "step": next_card.step,
            "reps": card.reps + 1,
            "lapses": lapses,
            "last_reviewed_at": now.isoformat(),
        })
        connection.execute(
            "UPDATE study_cards SET schema_version=?, due_at=?, stability=?, difficulty=?, reps=?, lapses=?, last_reviewed_at=?, fsrs_state=?, step=? WHERE card_id=?",
            (updated.schema_version, updated.due_at, updated.stability, updated.difficulty, updated.reps, updated.lapses, updated.last_reviewed_at, updated.fsrs_state, updated.step, card_id),
        )
        connection.execute(
            "INSERT INTO study_reviews(card_id, rating, reviewed_at, due_at, stability, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
            (card_id, rating, updated.last_reviewed_at, updated.due_at, updated.stability, updated.difficulty),
        )
        connection.commit()
        return updated
    finally:
        connection.close()


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def review_history(card_id: str = "", limit: int = 200) -> list[dict[str, object]]:
    connection = _connect()
    try:
        cap = max(1, min(int(limit or 200), 1000))
        if card_id:
            rows = connection.execute("SELECT * FROM study_reviews WHERE card_id = ? ORDER BY reviewed_at DESC LIMIT ?", (card_id, cap)).fetchall()
        else:
            rows = connection.execute("SELECT * FROM study_reviews ORDER BY reviewed_at DESC LIMIT ?", (cap,)).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def study_summary() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    connection = _connect()
    try:
        counts = {
            str(row["status"]): int(row["count"])
            for row in connection.execute("SELECT status, COUNT(*) AS count FROM study_cards GROUP BY status")
        }
        due = int(connection.execute("SELECT COUNT(*) FROM study_cards WHERE status = 'active' AND (due_at = '' OR due_at <= ?)", (now.isoformat(),)).fetchone()[0])
        reviewed_today = int(connection.execute("SELECT COUNT(*) FROM study_reviews WHERE reviewed_at LIKE ?", (f"{today}%",)).fetchone()[0])
    finally:
        connection.close()
    return {"schema_version": STUDY_SCHEMA_VERSION, "algorithm": FSRS_ALGORITHM, "counts": counts, "due_count": due, "reviewed_today": reviewed_today}
