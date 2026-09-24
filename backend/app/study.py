from __future__ import annotations

import json
import hashlib
import sqlite3
import re
import math
from .storage import atomic_write_text
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fsrs import Card as FsrsCard
from fsrs import Rating as FsrsRating
from fsrs import Scheduler as FsrsScheduler
from fsrs import State as FsrsState

from .config import DATA_DIR, ensure_dirs
from .models import SourceEvidence, StudyCard, StudyPlan
from .study_content import review_points


STUDY_SCHEMA_VERSION = 3
FSRS_ALGORITHM = "fsrs-6.3.2"
ACTIVITY_KINDS = {"reading", "answer", "self_assessment", "review"}
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
           fsrs_state TEXT NOT NULL DEFAULT 'Learning', step INTEGER NOT NULL DEFAULT 0,
           position INTEGER NOT NULL DEFAULT 0
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS study_plans (
           plan_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, title TEXT NOT NULL,
           daily_target INTEGER NOT NULL, paused INTEGER NOT NULL, timezone TEXT NOT NULL,
           created_at TEXT NOT NULL, updated_at TEXT NOT NULL
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
           ,idempotency_key TEXT NOT NULL DEFAULT ''
        )"""
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS study_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, source_id TEXT NOT NULL, occurred_at TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS study_card_spaces (card_id TEXT NOT NULL, space_id TEXT NOT NULL, assigned_at TEXT NOT NULL, PRIMARY KEY (card_id, space_id))"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(study_cards)").fetchall()}
    if "fsrs_state" not in columns:
        connection.execute("ALTER TABLE study_cards ADD COLUMN fsrs_state TEXT NOT NULL DEFAULT 'Learning'")
    if "step" not in columns:
        connection.execute("ALTER TABLE study_cards ADD COLUMN step INTEGER NOT NULL DEFAULT 0")
    if "position" not in columns:
        connection.execute("ALTER TABLE study_cards ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
    review_columns = {row[1] for row in connection.execute("PRAGMA table_info(study_reviews)").fetchall()}
    if "idempotency_key" not in review_columns:
        connection.execute("ALTER TABLE study_reviews ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS study_review_idempotency_idx ON study_reviews(card_id, idempotency_key) WHERE idempotency_key != ''"
    )
    plan_columns = {row[1] for row in connection.execute("PRAGMA table_info(study_plans)")}
    if "timezone_initialized" not in plan_columns:
        connection.execute("ALTER TABLE study_plans ADD COLUMN timezone_initialized INTEGER NOT NULL DEFAULT 0")
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
        fsrs_state=str(row["fsrs_state"] or "Learning"), step=int(row["step"] or 0), position=int(row["position"] or 0),
    )


def propose_cards(evidence: list[SourceEvidence], limit: int = 20) -> list[StudyCard]:
    proposals: list[StudyCard] = []
    seen: set[str] = set()
    cap = max(1, min(int(limit), 100))
    # A full generated note repeats its transcript and includes scaffolding.
    # Prefer the underlying source anchors whenever available.
    sources = [item for item in evidence if item.locator not in {"note", "generated-note"}]
    if not sources:
        sources = evidence
    for item in sources:
        if not item.evidence_id or item.metadata.get("kind") == "community":
            continue
        for heading, paragraph in review_points(item.text):
            key = re.sub(r"\s+", "", paragraph).casefold()
            if key in seen:
                continue
            seen.add(key)
            cue = re.split(r"[，,：:]", paragraph, maxsplit=1)[0]
            if len(cue) > 45:
                cue = cue[:42] + "…"
            relation = re.match(r"(.{2,24}?)(决定|影响|表示|用于|提供|包含|意味着)(.+)", paragraph)
            prompt = f"{relation[1]}{relation[2]}什么？" if relation else f"围绕“{heading or item.title or cue[:18]}”，原文在 {item.locator or '这一段'} 说明了什么？"
            proposals.append(StudyCard(
                card_id=uuid4().hex,
                front=f"{heading or item.title or '这份资料'} · {item.locator or '原文'}\n{prompt}",
                back=paragraph,
                source_evidence_ids=[item.evidence_id] if item.evidence_id else [],
            ))
            if len(proposals) >= cap:
                return proposals
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
                """INSERT INTO study_cards
                   (card_id, schema_version, front, back, source_evidence_ids, status, due_at,
                    stability, difficulty, reps, lapses, last_reviewed_at, fsrs_state, step, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.card_id, item.schema_version, item.front, item.back,
                 json.dumps(item.source_evidence_ids, ensure_ascii=False), item.status, item.due_at,
                 item.stability, item.difficulty, item.reps, item.lapses, item.last_reviewed_at,
                 item.fsrs_state, int(item.step or 0), int(item.position)),
            )
            stored.append(item)
        connection.commit()
    finally:
        connection.close()
    return stored


def save_cards_unique(cards: list[StudyCard]) -> list[StudyCard]:
    """Save confirmed cards without duplicating a card shared by spaces.

    The legacy ``save_cards`` function remains append-only for API
    compatibility.  New learning-space flows use this identity check so a
    card referenced by two spaces still has one FSRS schedule and one review
    history.
    """
    if not cards:
        return []
    connection = _connect()
    try:
        existing = connection.execute("SELECT card_id, front, back, source_evidence_ids FROM study_cards WHERE status != 'deleted'").fetchall()
    finally:
        connection.close()
    keys = {
        (str(row["front"]).strip(), str(row["back"]).strip(), tuple(sorted(json.loads(row["source_evidence_ids"] or "[]")))): str(row["card_id"])
        for row in existing
    }
    unique: list[StudyCard] = []
    for card in cards:
        key = (card.front.strip(), card.back.strip(), tuple(sorted(card.source_evidence_ids)))
        if key in keys:
            continue
        keys[key] = card.card_id
        unique.append(card)
    return save_cards(unique)


def assign_cards_to_space(
    space_id: str,
    *,
    cards: list[StudyCard] | None = None,
    card_ids: list[str] | None = None,
    evidence_ids: set[str] | None = None,
) -> list[str]:
    """Record membership without copying or changing FSRS scheduling fields."""
    value = str(space_id or "").strip()[:128]
    if not value or value == "existing-review":
        return []
    connection = _connect()
    try:
        rows = []
        ids = {str(item) for item in (card_ids or []) if str(item)}
        if ids:
            marks = ",".join("?" for _ in ids)
            rows.extend(connection.execute(f"SELECT card_id FROM study_cards WHERE card_id IN ({marks}) AND status != 'deleted'", tuple(ids)).fetchall())
        for card in cards or []:
            row = connection.execute(
                "SELECT card_id FROM study_cards WHERE front = ? AND back = ? AND source_evidence_ids = ? AND status != 'deleted' LIMIT 1",
                (card.front, card.back, json.dumps(card.source_evidence_ids, ensure_ascii=False)),
            ).fetchone()
            if row:
                rows.append(row)
        if evidence_ids:
            for row in connection.execute("SELECT card_id, source_evidence_ids FROM study_cards WHERE status != 'deleted'"):
                try:
                    stored = set(json.loads(row["source_evidence_ids"] or "[]"))
                except (TypeError, ValueError):
                    stored = set()
                if stored.intersection(evidence_ids):
                    rows.append(row)
        now = datetime.now(timezone.utc).isoformat()
        unique = list(dict.fromkeys(str(row["card_id"]) for row in rows))
        connection.executemany("INSERT OR IGNORE INTO study_card_spaces(card_id, space_id, assigned_at) VALUES (?, ?, ?)", [(card_id, value, now) for card_id in unique])
        connection.commit()
        return unique
    finally:
        connection.close()


def card_space_ids(card_id: str) -> set[str]:
    connection = _connect()
    try:
        return {str(row[0]) for row in connection.execute("SELECT space_id FROM study_card_spaces WHERE card_id = ?", (str(card_id),))}
    finally:
        connection.close()


def unassigned_cards(limit: int = 500) -> list[StudyCard]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT c.* FROM study_cards c LEFT JOIN study_card_spaces s ON s.card_id = c.card_id WHERE c.status != 'deleted' AND s.card_id IS NULL ORDER BY c.position ASC, c.due_at ASC LIMIT ?",
            (max(1, min(int(limit or 500), 1000)),),
        ).fetchall()
    finally:
        connection.close()
    return [_row_to_card(row) for row in rows]


def due_cards(limit: int = 50, evidence_ids: set[str] | None = None) -> list[StudyCard]:
    if get_study_plan().paused:
        return []
    if evidence_ids is not None and not evidence_ids:
        return []
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        cap = max(1, min(int(limit or 50), 200))
        query = "SELECT * FROM study_cards WHERE status = 'active' AND (due_at = '' OR due_at <= ?) ORDER BY due_at ASC"
        if evidence_ids is None:
            rows = connection.execute(query + " LIMIT ?", (now, cap)).fetchall()
        else:
            rows = []
            for row in connection.execute(query, (now,)):
                if evidence_ids.intersection(json.loads(row["source_evidence_ids"] or "[]")):
                    rows.append(row)
                    if len(rows) >= cap:
                        break
    finally:
        connection.close()
    return [_row_to_card(row) for row in rows]


def list_cards(status: str = "", limit: int = 200) -> list[StudyCard]:
    connection = _connect()
    try:
        if status in {"active", "suspended", "deleted"}:
            rows = connection.execute("SELECT * FROM study_cards WHERE status = ? ORDER BY position ASC, due_at ASC LIMIT ?", (status, max(1, min(int(limit or 200), 500)))).fetchall()
        else:
            rows = connection.execute("SELECT * FROM study_cards ORDER BY position ASC, due_at ASC LIMIT ?", (max(1, min(int(limit or 200), 500)),)).fetchall()
    finally:
        connection.close()
    return [_row_to_card(row) for row in rows]


def remove_cards_for_evidence(evidence_ids: list[str]) -> dict[str, int]:
    """Permanently remove cards and reviews whose grounding was deleted."""

    targets = {str(value) for value in evidence_ids if str(value)}
    if not targets:
        return {"deleted_cards": 0, "deleted_reviews": 0}
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT card_id, source_evidence_ids FROM study_cards").fetchall()
        card_ids: list[str] = []
        for row in rows:
            try:
                stored = {str(value) for value in json.loads(row["source_evidence_ids"] or "[]")}
            except (TypeError, ValueError):
                stored = set()
            if stored & targets:
                card_ids.append(str(row["card_id"]))
        deleted_reviews = 0
        for card_id in card_ids:
            deleted_reviews += max(0, connection.execute("DELETE FROM study_reviews WHERE card_id = ?", (card_id,)).rowcount)
            connection.execute("DELETE FROM study_cards WHERE card_id = ?", (card_id,))
        connection.commit()
        return {"deleted_cards": len(card_ids), "deleted_reviews": deleted_reviews}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def clear_study_data() -> dict[str, int]:
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        review_count = int(connection.execute("SELECT COUNT(*) FROM study_reviews").fetchone()[0])
        card_count = int(connection.execute("SELECT COUNT(*) FROM study_cards").fetchone()[0])
        plan_count = int(connection.execute("SELECT COUNT(*) FROM study_plans").fetchone()[0])
        connection.execute("DELETE FROM study_reviews")
        connection.execute("DELETE FROM study_activity")
        connection.execute("DELETE FROM study_card_spaces")
        connection.execute("DELETE FROM study_cards")
        connection.execute("DELETE FROM study_plans")
        backup_root = (DATA_DIR / "study-schedule-backups").resolve()
        if not backup_root.is_relative_to(DATA_DIR.resolve()):
            raise ValueError("unsafe_study_backup_path")
        deleted_backups = 0
        for backup in backup_root.glob("schedule-*.json"):
            if re.fullmatch(r"schedule-[a-f0-9]{32}\.json", backup.name):
                backup.unlink()
                deleted_backups += 1
        connection.commit()
        return {"deleted_reviews": review_count, "deleted_cards": card_count, "deleted_plans": plan_count, "deleted_schedule_backups": deleted_backups}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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


def set_card_position(card_id: str, position: int) -> StudyCard:
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone()
        if row is None:
            raise ValueError("card_not_found")
        connection.execute("UPDATE study_cards SET position = ? WHERE card_id = ?", (max(0, min(int(position), 1000000)), card_id))
        connection.commit()
        return _row_to_card(connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone())
    finally:
        connection.close()


def _scheduler_card(card: StudyCard, now: datetime) -> FsrsCard:
    state = getattr(FsrsState, card.fsrs_state, FsrsState.Learning)
    return FsrsCard(
        card_id=int(hashlib.sha256(card.card_id.encode("utf-8")).hexdigest()[:15], 16),
        state=state, step=None if state == FsrsState.Review else card.step,
        stability=card.stability if card.reps else None,
        difficulty=card.difficulty if card.reps else None,
        due=_parse_datetime(card.due_at) or now,
        last_review=_parse_datetime(card.last_reviewed_at),
    )


def review_schedule_preview(card_id: str) -> dict:
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM study_cards WHERE card_id=?", (card_id,)).fetchone()
        if row is None:
            raise ValueError("card_not_found")
        card = _row_to_card(row)
    finally:
        connection.close()
    now = datetime.now(timezone.utc)
    choices = []
    for rating in (1, 2, 3, 4):
        next_card, _ = _SCHEDULER.review_card(_scheduler_card(card, now), FsrsRating(rating), review_datetime=now)
        choices.append({"rating":rating,"due_at":next_card.due.isoformat(),"interval_seconds":max(0,round((next_card.due-now).total_seconds()))})
    return {"card_id":card_id,"algorithm":FSRS_ALGORITHM,"choices":choices}


def review_card(card_id: str, rating: int, idempotency_key: str = "") -> StudyCard:
    if rating not in {1, 2, 3, 4}:
        raise ValueError("invalid_rating")
    get_study_plan()
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT paused FROM study_plans WHERE plan_id='default'").fetchone()[0]:
            raise ValueError("study_plan_paused")
        row = connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone()
        if row is None:
            raise ValueError("card_not_found")
        card = _row_to_card(row)
        if card.status != "active":
            raise ValueError("card_not_active")
        safe_key = str(idempotency_key or "")[:128]
        if safe_key:
            existing = connection.execute(
                "SELECT review_id FROM study_reviews WHERE card_id = ? AND idempotency_key = ?",
                (card_id, safe_key),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return card
        now = datetime.now(timezone.utc)
        fsrs_card = _scheduler_card(card, now)
        next_card, _review_log = _SCHEDULER.review_card(fsrs_card, FsrsRating(rating), review_datetime=now)
        lapses = card.lapses + (1 if rating == 1 else 0)
        updated = card.model_copy(update={
            "schema_version": STUDY_SCHEMA_VERSION,
            "algorithm": FSRS_ALGORITHM,
            "due_at": next_card.due.astimezone(timezone.utc).isoformat(),
            "stability": round(float(next_card.stability or card.stability), 4),
            "difficulty": round(float(next_card.difficulty or card.difficulty), 4),
            "fsrs_state": next_card.state.name,
            "step": int(next_card.step or 0),
            "reps": card.reps + 1,
            "lapses": lapses,
            "last_reviewed_at": now.isoformat(),
        })
        connection.execute(
            "UPDATE study_cards SET schema_version=?, due_at=?, stability=?, difficulty=?, reps=?, lapses=?, last_reviewed_at=?, fsrs_state=?, step=? WHERE card_id=?",
            (updated.schema_version, updated.due_at, updated.stability, updated.difficulty, updated.reps, updated.lapses, updated.last_reviewed_at, updated.fsrs_state, updated.step, card_id),
        )
        connection.execute(
            "INSERT INTO study_reviews(card_id, rating, reviewed_at, due_at, stability, difficulty, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (card_id, rating, updated.last_reviewed_at, updated.due_at, updated.stability, updated.difficulty, safe_key),
        )
        connection.execute(
            "INSERT INTO study_activity(kind, source_id, occurred_at) VALUES ('review', ?, ?)",
            (card_id, updated.last_reviewed_at),
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


def rebuild_study_schedules() -> dict:
    connection = _connect()
    updated = skipped = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT * FROM study_cards WHERE status!='deleted' AND reps>0").fetchall()
        fields = ("card_id", "due_at", "stability", "difficulty", "fsrs_state", "step", "last_reviewed_at")
        backup = DATA_DIR / "study-schedule-backups" / f"schedule-{uuid4().hex}.json"
        atomic_write_text(backup, json.dumps({"schema_version": 1, "algorithm": FSRS_ALGORITHM, "cards": [{key: row[key] for key in fields} for row in rows]}, ensure_ascii=False))
        for row in rows:
            reviews = connection.execute("SELECT rating,reviewed_at FROM study_reviews WHERE card_id=? ORDER BY review_id", (row["card_id"],)).fetchall()
            if len(reviews) != row["reps"] or not reviews:
                skipped += 1
                continue
            try:
                first = _parse_datetime(reviews[0]["reviewed_at"])
                if first is None:
                    raise ValueError("invalid_review_time")
                card = FsrsCard(card_id=int(hashlib.sha256(row["card_id"].encode()).hexdigest()[:15],16), due=first)
                for review in reviews:
                    when = _parse_datetime(review["reviewed_at"])
                    if when is None or card.last_review and when < card.last_review:
                        raise ValueError("invalid_review_time")
                    card, _ = _SCHEDULER.review_card(card, FsrsRating(review["rating"]), review_datetime=when)
            except (ValueError, TypeError, ArithmeticError):
                skipped += 1
                continue
            connection.execute("UPDATE study_cards SET due_at=?,stability=?,difficulty=?,fsrs_state=?,step=?,last_reviewed_at=? WHERE card_id=?", (card.due.isoformat(),float(card.stability),float(card.difficulty),card.state.name,int(card.step or 0),card.last_review.isoformat(),row["card_id"]))
            updated += 1
        connection.commit()
        return {"updated": updated, "skipped_incomplete_history": skipped, "backup_name": backup.name}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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
    plan = get_study_plan()
    zone = study_timezone(plan.timezone)
    today = now.astimezone(zone).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    connection = _connect()
    try:
        counts = {
            str(row["status"]): int(row["count"])
            for row in connection.execute("SELECT status, COUNT(*) AS count FROM study_cards GROUP BY status")
        }
        due = int(connection.execute("SELECT COUNT(*) FROM study_cards WHERE status = 'active' AND (due_at = '' OR due_at <= ?)", (now.isoformat(),)).fetchone()[0])
        reviewed_today = int(connection.execute("SELECT COUNT(*) FROM study_reviews WHERE reviewed_at >= ? AND reviewed_at < ?", (start.isoformat(), end.isoformat())).fetchone()[0])
        activity_today = {
            str(row["kind"]): int(row["count"])
            for row in connection.execute(
                "SELECT kind, COUNT(*) AS count FROM study_activity WHERE kind != 'review' AND occurred_at >= ? AND occurred_at < ? GROUP BY kind",
                (start.isoformat(), end.isoformat()),
            )
        }
        review_count = int(connection.execute(
            "SELECT COUNT(*) FROM study_reviews WHERE reviewed_at >= ? AND reviewed_at < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()[0])
        if review_count:
            activity_today["review"] = review_count
    finally:
        connection.close()
    return {"schema_version": STUDY_SCHEMA_VERSION, "algorithm": FSRS_ALGORITHM, "counts": counts, "due_count": 0 if plan.paused else due, "reviewed_today": reviewed_today, "activity_today": activity_today, "timezone": plan.timezone, "paused": plan.paused}


def record_activity(kind: str, source_id: str = "", occurred_at: str | None = None) -> dict[str, object]:
    normalized = str(kind or "").strip().lower()
    if normalized not in ACTIVITY_KINDS:
        raise ValueError("invalid_activity_kind")
    when = _parse_datetime(occurred_at or "") or datetime.now(timezone.utc)
    connection = _connect()
    try:
        cursor = connection.execute(
            "INSERT INTO study_activity(kind, source_id, occurred_at) VALUES (?, ?, ?)",
            (normalized, str(source_id or "")[:128], when.astimezone(timezone.utc).isoformat()),
        )
        connection.commit()
        return {"activity_id": int(cursor.lastrowid), "kind": normalized, "source_id": str(source_id or "")[:128], "occurred_at": when.astimezone(timezone.utc).isoformat()}
    finally:
        connection.close()


def activity_summary(days: int = 30) -> dict[str, object]:
    cap = max(1, min(int(days or 30), 365))
    now = datetime.now(timezone.utc)
    plan = get_study_plan()
    zone = study_timezone(plan.timezone)
    start_date = now.astimezone(zone).date() - timedelta(days=cap - 1)
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    connection = _connect()
    try:
        rows = connection.execute("SELECT kind, source_id, occurred_at FROM study_activity WHERE kind != 'review' AND occurred_at >= ? ORDER BY occurred_at DESC", (start.isoformat(),)).fetchall()
        review_rows = connection.execute("SELECT card_id, reviewed_at FROM study_reviews WHERE reviewed_at >= ? ORDER BY reviewed_at DESC", (start.isoformat(),)).fetchall()
    finally:
        connection.close()
    by_kind = {kind: 0 for kind in sorted(ACTIVITY_KINDS)}
    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        kind = str(row["kind"])
        when = _parse_datetime(row["occurred_at"])
        if kind not in by_kind or when is None:
            continue
        by_kind[kind] += 1
        day = when.astimezone(zone).date().isoformat()
        by_day.setdefault(day, {item: 0 for item in sorted(ACTIVITY_KINDS)})[kind] += 1
    for row in review_rows:
        when = _parse_datetime(row["reviewed_at"])
        if when is None:
            continue
        by_kind["review"] += 1
        day = when.astimezone(zone).date().isoformat()
        by_day.setdefault(day, {item: 0 for item in sorted(ACTIVITY_KINDS)})["review"] += 1
    activity = []
    for offset in range(cap):
        day = (start_date + timedelta(days=offset)).isoformat()
        activity.append({"date": day, **by_day.get(day, {item: 0 for item in sorted(ACTIVITY_KINDS)})})
    return {"schema_version": 1, "timezone": plan.timezone, "days": activity, "by_kind": by_kind}


def export_study_data() -> dict[str, object]:
    # UI pagination must not silently truncate a user's portable backup.
    connection = _connect()
    try:
        cards = [_row_to_card(row) for row in connection.execute("SELECT * FROM study_cards WHERE status!='deleted' ORDER BY position,card_id")]
        reviews = [dict(row) for row in connection.execute("SELECT r.review_id,r.card_id,r.rating,r.reviewed_at,r.due_at,r.stability,r.difficulty,r.idempotency_key FROM study_reviews r JOIN study_cards c ON c.card_id=r.card_id WHERE c.status!='deleted' ORDER BY r.review_id")]
        activity_events = [dict(row) for row in connection.execute("SELECT kind,source_id,occurred_at FROM study_activity ORDER BY activity_id")]
    finally:
        connection.close()
    return {
        "schema_version": STUDY_SCHEMA_VERSION,
        "algorithm": FSRS_ALGORITHM,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "cards": [card.model_dump(mode="json") for card in cards],
        "reviews": reviews,
        "activity": activity_summary(365)["days"],
        "activity_events": activity_events,
        "plan": get_study_plan().model_dump(mode="json"),
    }


def validate_study_backup(payload: dict) -> dict[str, object]:
    """Validate a portable study snapshot before any local merge is written."""

    if not isinstance(payload, dict) or payload.get("algorithm") != FSRS_ALGORITHM:
        raise ValueError("study_backup_algorithm_unsupported")
    if int(payload.get("schema_version") or 0) != STUDY_SCHEMA_VERSION:
        raise ValueError("study_backup_schema_unsupported")
    raw_cards = payload.get("cards")
    raw_reviews = payload.get("reviews")
    raw_events = payload.get("activity_events", [])
    if not isinstance(raw_cards, list) or not isinstance(raw_reviews, list) or not isinstance(raw_events, list):
        raise ValueError("study_backup_shape_invalid")
    if len(raw_cards) > 100_000 or len(raw_reviews) > 500_000 or len(raw_events) > 1_000_000:
        raise ValueError("study_backup_limit_exceeded")

    cards: list[dict[str, object]] = []
    card_ids: set[str] = set()
    for raw in raw_cards:
        if not isinstance(raw, dict):
            raise ValueError("study_backup_card_invalid")
        card = StudyCard.model_validate(raw)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", card.card_id) or card.status not in {"active", "suspended"}:
            raise ValueError("study_backup_card_invalid")
        if card.card_id in card_ids or _parse_datetime(card.due_at) is None:
            raise ValueError("study_backup_card_invalid")
        card_ids.add(card.card_id)
        cards.append(card.model_dump(mode="json"))

    reviews: list[dict[str, object]] = []
    for raw in raw_reviews:
        if not isinstance(raw, dict):
            raise ValueError("study_backup_review_invalid")
        card_id = str(raw.get("card_id") or "")
        raw_rating = raw.get("rating")
        rating = int(raw_rating) if isinstance(raw_rating, int) and not isinstance(raw_rating, bool) else 0
        reviewed_at = _parse_datetime(raw.get("reviewed_at"))
        due_at = _parse_datetime(raw.get("due_at"))
        stability = float(raw.get("stability") or 0)
        difficulty = float(raw.get("difficulty") or 0)
        idempotency_key = str(raw.get("idempotency_key") or "")
        if (
            card_id not in card_ids or rating not in {1, 2, 3, 4}
            or reviewed_at is None or due_at is None
            or not math.isfinite(stability) or stability < 0 or stability > 36500
            or not math.isfinite(difficulty) or not 1 <= difficulty <= 10
            or len(idempotency_key) > 128 or idempotency_key and not re.fullmatch(r"[A-Za-z0-9._:-]+", idempotency_key)
        ):
            raise ValueError("study_backup_review_invalid")
        reviews.append({
            "card_id": card_id,
            "rating": rating,
            "reviewed_at": reviewed_at.isoformat(),
            "due_at": due_at.isoformat(),
            "stability": stability,
            "difficulty": difficulty,
            "idempotency_key": idempotency_key,
        })

    events: list[dict[str, str]] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise ValueError("study_backup_activity_invalid")
        kind = str(raw.get("kind") or "")
        source_id = str(raw.get("source_id") or "")[:128]
        occurred_at = _parse_datetime(raw.get("occurred_at"))
        if kind not in ACTIVITY_KINDS or occurred_at is None:
            raise ValueError("study_backup_activity_invalid")
        events.append({"kind": kind, "source_id": source_id, "occurred_at": occurred_at.isoformat()})

    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("study_backup_plan_invalid")
    validated_plan = StudyPlan.model_validate(plan)
    study_timezone(validated_plan.timezone)
    return {
        "schema_version": STUDY_SCHEMA_VERSION,
        "algorithm": FSRS_ALGORITHM,
        "cards": cards,
        "reviews": reviews,
        "activity_events": events,
        "plan": validated_plan.model_dump(mode="json"),
    }


def restore_study_data(payload: dict) -> dict[str, int]:
    """Idempotently merge validated cards, review history, activity and plan."""

    snapshot = validate_study_backup(payload)
    connection = _connect()
    restored_cards = restored_reviews = restored_activity = 0
    plan_restored = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_cards = {str(row[0]) for row in connection.execute("SELECT card_id FROM study_cards")}
        for raw in snapshot["cards"]:
            card = StudyCard.model_validate(raw)
            if card.card_id in existing_cards:
                continue
            connection.execute(
                """INSERT INTO study_cards
                   (card_id, schema_version, front, back, source_evidence_ids, status, due_at,
                    stability, difficulty, reps, lapses, last_reviewed_at, fsrs_state, step, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (card.card_id, STUDY_SCHEMA_VERSION, card.front, card.back,
                 json.dumps(card.source_evidence_ids, ensure_ascii=False), card.status, card.due_at,
                 card.stability, card.difficulty, card.reps, card.lapses, card.last_reviewed_at,
                 card.fsrs_state, int(card.step or 0), int(card.position)),
            )
            existing_cards.add(card.card_id)
            restored_cards += 1

        for item in snapshot["reviews"]:
            identity = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            key = str(item["idempotency_key"] or "restore-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40])
            duplicate = connection.execute(
                """SELECT 1 FROM study_reviews WHERE card_id=? AND (
                     (idempotency_key!='' AND idempotency_key=?) OR
                     (rating=? AND reviewed_at=? AND due_at=? AND stability=? AND difficulty=?)) LIMIT 1""",
                (item["card_id"], key, item["rating"], item["reviewed_at"], item["due_at"], item["stability"], item["difficulty"]),
            ).fetchone()
            if duplicate:
                continue
            connection.execute(
                "INSERT INTO study_reviews(card_id,rating,reviewed_at,due_at,stability,difficulty,idempotency_key) VALUES (?,?,?,?,?,?,?)",
                (item["card_id"], item["rating"], item["reviewed_at"], item["due_at"], item["stability"], item["difficulty"], key),
            )
            restored_reviews += 1

        for item in snapshot["activity_events"]:
            duplicate = connection.execute(
                "SELECT 1 FROM study_activity WHERE kind=? AND source_id=? AND occurred_at=? LIMIT 1",
                (item["kind"], item["source_id"], item["occurred_at"]),
            ).fetchone()
            if duplicate:
                continue
            connection.execute(
                "INSERT INTO study_activity(kind,source_id,occurred_at) VALUES (?,?,?)",
                (item["kind"], item["source_id"], item["occurred_at"]),
            )
            restored_activity += 1

        imported_plan = StudyPlan.model_validate(snapshot["plan"])
        current_plan = connection.execute("SELECT * FROM study_plans WHERE plan_id='default'").fetchone()
        current_is_uninitialized = current_plan is None or (
            not bool(current_plan["timezone_initialized"])
            and current_plan["title"] == "本地学习计划"
            and int(current_plan["daily_target"]) == 10
            and not bool(current_plan["paused"])
        )
        imported_time = _parse_datetime(imported_plan.updated_at)
        current_time = _parse_datetime(current_plan["updated_at"]) if current_plan else None
        if current_is_uninitialized or imported_time and (current_time is None or imported_time > current_time):
            connection.execute(
                """INSERT INTO study_plans(plan_id,schema_version,title,daily_target,paused,timezone,created_at,updated_at,timezone_initialized)
                   VALUES ('default',?,?,?,?,?,?,?,?)
                   ON CONFLICT(plan_id) DO UPDATE SET schema_version=excluded.schema_version,title=excluded.title,
                   daily_target=excluded.daily_target,paused=excluded.paused,timezone=excluded.timezone,
                   created_at=excluded.created_at,updated_at=excluded.updated_at,timezone_initialized=excluded.timezone_initialized""",
                (STUDY_SCHEMA_VERSION, imported_plan.title, imported_plan.daily_target, int(imported_plan.paused),
                 imported_plan.timezone, imported_plan.created_at, imported_plan.updated_at, int(imported_plan.timezone_initialized)),
            )
            plan_restored = 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"restored_cards": restored_cards, "restored_reviews": restored_reviews, "restored_activity": restored_activity, "restored_plan": plan_restored}


def get_study_plan() -> StudyPlan:
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM study_plans WHERE plan_id = 'default'").fetchone()
        if row is None:
            connection.execute(
                "INSERT OR IGNORE INTO study_plans(plan_id, schema_version, title, daily_target, paused, timezone, created_at, updated_at) VALUES ('default', ?, ?, ?, 0, 'UTC', ?, ?)",
                (STUDY_SCHEMA_VERSION, "本地学习计划", 10, now, now),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM study_plans WHERE plan_id = 'default'").fetchone()
        return StudyPlan(
            schema_version=max(int(row["schema_version"]), STUDY_SCHEMA_VERSION), plan_id=row["plan_id"],
            title=row["title"], daily_target=int(row["daily_target"]), paused=bool(row["paused"]),
            timezone=row["timezone"], created_at=row["created_at"], updated_at=row["updated_at"],
            timezone_initialized=bool(row["timezone_initialized"]),
        )
    finally:
        connection.close()


def study_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid_study_timezone") from exc


def initialize_study_timezone(name: str) -> StudyPlan:
    study_timezone(name)
    get_study_plan()
    connection = _connect()
    try:
        connection.execute("UPDATE study_plans SET timezone=?, timezone_initialized=1 WHERE plan_id='default' AND timezone_initialized=0", (name,))
        connection.commit()
    finally:
        connection.close()
    return get_study_plan()


def update_study_plan(title: str, daily_target: int, paused: bool, timezone_name: str | None = None) -> StudyPlan:
    current = get_study_plan()
    selected_timezone = timezone_name if timezone_name is not None else current.timezone
    study_timezone(selected_timezone)
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        connection.execute(
            "UPDATE study_plans SET schema_version=?, title=?, daily_target=?, paused=?, timezone=?, updated_at=? WHERE plan_id='default'",
            (STUDY_SCHEMA_VERSION, str(title or "本地学习计划")[:120], max(1, min(int(daily_target), 200)), int(bool(paused)), selected_timezone, now),
        )
        if timezone_name is not None:
            connection.execute("UPDATE study_plans SET timezone_initialized=1 WHERE plan_id='default'")
        connection.commit()
        return current.model_copy(update={"schema_version": STUDY_SCHEMA_VERSION, "title": str(title or "本地学习计划")[:120], "daily_target": max(1, min(int(daily_target), 200)), "paused": bool(paused), "timezone": selected_timezone, "updated_at": now})
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def study_dashboard(limit: int = 12, activity_days: int = 14) -> dict[str, object]:
    """Build one local-only learning workspace from the existing FSRS data.

    Quiz prompts are projections of due evidence-grounded cards; answers stay
    out of the queue payload so the client can reveal them deliberately. A
    rating of 1 is treated as a review mistake for the recovery queue.
    """
    cap = max(1, min(int(limit or 12), 50))
    days = max(7, min(int(activity_days or 14), 90))
    now = datetime.now(timezone.utc)
    plan = get_study_plan()
    zone = study_timezone(plan.timezone)
    start_date = now.astimezone(zone).date() - timedelta(days=days - 1)
    summary = study_summary()
    due = due_cards(cap)
    has_cards = any(value for key, value in (summary.get("counts") or {}).items() if key != "deleted")
    connection = _connect()
    try:
        range_start = datetime.combine(start_date, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        range_end = datetime.combine(start_date + timedelta(days=days), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        activity_rows = connection.execute(
            "SELECT kind, occurred_at FROM study_activity WHERE kind != 'review' AND occurred_at >= ? AND occurred_at < ?",
            (range_start.isoformat(), range_end.isoformat()),
        ).fetchall()
        review_rows = connection.execute(
            "SELECT reviewed_at FROM study_reviews WHERE reviewed_at >= ? AND reviewed_at < ?",
            (range_start.isoformat(), range_end.isoformat()),
        ).fetchall()
        mistake_rows = connection.execute(
            """SELECT r.review_id, r.card_id, r.rating, r.reviewed_at, r.due_at,
                      c.front, c.back, c.source_evidence_ids
               FROM study_reviews r JOIN study_cards c ON c.card_id = r.card_id
               WHERE r.rating = 1 AND c.status != 'deleted'
               ORDER BY r.reviewed_at DESC LIMIT ?""",
            (cap,),
        ).fetchall()
        recent_rows = connection.execute(
            """SELECT review_id, card_id, rating, reviewed_at, due_at, stability, difficulty
               FROM study_reviews ORDER BY reviewed_at DESC LIMIT ?""",
            (cap,),
        ).fetchall()
        mastery_rows = connection.execute(
            """SELECT CASE WHEN c.reps=0 THEN 'new'
                      WHEN latest.rating=1 OR c.fsrs_state='Relearning' THEN 'needs_attention'
                      WHEN c.stability>=21 THEN 'retained' ELSE 'learning' END AS bucket,
                      COUNT(*) AS count
               FROM study_cards c LEFT JOIN study_reviews latest ON latest.review_id=(
                 SELECT r.review_id FROM study_reviews r WHERE r.card_id=c.card_id
                 ORDER BY r.reviewed_at DESC, r.review_id DESC LIMIT 1
               )
               WHERE c.status='active' GROUP BY bucket"""
        ).fetchall()
    finally:
        connection.close()

    activity_by_day: dict[str, dict[str, int]] = {}
    for row in activity_rows:
        occurred_at = _parse_datetime(row["occurred_at"])
        kind = str(row["kind"])
        if occurred_at and kind in ACTIVITY_KINDS:
            day = occurred_at.astimezone(zone).date().isoformat()
            activity_by_day.setdefault(day, {item: 0 for item in ACTIVITY_KINDS})[kind] += 1
    for row in review_rows:
        reviewed_at = _parse_datetime(row["reviewed_at"])
        if reviewed_at:
            day = reviewed_at.astimezone(zone).date().isoformat()
            activity_by_day.setdefault(day, {item: 0 for item in ACTIVITY_KINDS})["review"] += 1
    activity = []
    for offset in range(days):
        day = (start_date + timedelta(days=offset)).isoformat()
        daily = activity_by_day.get(day, {item: 0 for item in ACTIVITY_KINDS})
        activity.append({"date": day, "review_count": daily["review"], "reading_count": daily["reading"], "answer_count": daily["answer"], "self_assessment_count": daily["self_assessment"]})

    mastery = {"new": 0, "learning": 0, "needs_attention": 0, "retained": 0}
    mastery.update({row["bucket"]: int(row["count"]) for row in mastery_rows})

    reviewed_today = int(summary.get("reviewed_today") or 0)
    daily_target = int(plan.daily_target)
    remaining = max(0, daily_target - reviewed_today)
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "privacy": {
            "storage": "local-only",
            "accounts_required": False,
            "telemetry": False,
            "course_platform_progress_read": False,
        },
        "plan": plan.model_dump(mode="json"),
        "today": {
            "due_count": int(summary.get("due_count") or 0),
            "reviewed_count": reviewed_today,
            "daily_target": daily_target,
            "remaining_target": remaining,
            "completion_ratio": round(min(1.0, reviewed_today / max(1, daily_target)), 4),
            "paused": bool(plan.paused),
        },
        "due_cards": [
            {**card.model_dump(mode="json", exclude={"back"}), "answer_included": False}
            for card in due
        ],
        "quiz_queue": [
            {
                "quiz_id": f"card-{card.card_id}",
                "kind": "evidence_card_recall",
                "question": card.front,
                "answer_included": False,
                "source_evidence_ids": card.source_evidence_ids,
                "review_endpoint": f"/api/study/cards/{card.card_id}/review",
            }
            for card in due
        ],
        "mistakes": [
            {
                "review_id": int(row["review_id"]),
                "card_id": row["card_id"],
                "question": row["front"],
                "answer": row["back"],
                "source_evidence_ids": json.loads(row["source_evidence_ids"] or "[]"),
                "reviewed_at": row["reviewed_at"],
                "retry_endpoint": f"/api/study/cards/{row['card_id']}/review",
            }
            for row in mistake_rows
        ],
        "progress": {
            "activity": activity,
            "mastery": mastery,
            "card_counts": summary.get("counts") or {},
            "algorithm": FSRS_ALGORITHM,
        },
        "recent_reviews": [dict(row) for row in recent_rows],
        "empty_state": {
            "has_cards": has_cards,
            "primary_action": "create_evidence_grounded_cards" if not has_cards else ("resume_plan" if plan.paused else "review_due_cards"),
        },
    }
