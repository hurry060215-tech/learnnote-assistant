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
from .models import SourceEvidence, StudyCard, StudyPlan


STUDY_SCHEMA_VERSION = 3
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
        connection.execute("DELETE FROM study_cards")
        connection.execute("DELETE FROM study_plans")
        connection.commit()
        return {"deleted_reviews": review_count, "deleted_cards": card_count, "deleted_plans": plan_count}
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


def review_card(card_id: str, rating: int, idempotency_key: str = "") -> StudyCard:
    if rating not in {1, 2, 3, 4}:
        raise ValueError("invalid_rating")
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM study_cards WHERE card_id = ?", (card_id,)).fetchone()
        if row is None:
            raise ValueError("card_not_found")
        card = _row_to_card(row)
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
            "INSERT INTO study_reviews(card_id, rating, reviewed_at, due_at, stability, difficulty, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (card_id, rating, updated.last_reviewed_at, updated.due_at, updated.stability, updated.difficulty, safe_key),
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


def export_study_data() -> dict[str, object]:
    cards = [card for card in list_cards(limit=1000) if card.status != "deleted"]
    allowed_ids = {card.card_id for card in cards}
    reviews = [item for item in review_history(limit=5000) if str(item.get("card_id") or "") in allowed_ids]
    return {
        "schema_version": STUDY_SCHEMA_VERSION,
        "algorithm": FSRS_ALGORITHM,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "cards": [card.model_dump(mode="json") for card in cards],
        "reviews": reviews,
        "plan": get_study_plan().model_dump(mode="json"),
    }


def get_study_plan() -> StudyPlan:
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM study_plans WHERE plan_id = 'default'").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO study_plans(plan_id, schema_version, title, daily_target, paused, timezone, created_at, updated_at) VALUES ('default', ?, ?, ?, 0, 'UTC', ?, ?)",
                (STUDY_SCHEMA_VERSION, "本地学习计划", 10, now, now),
            )
            connection.commit()
            return StudyPlan(schema_version=STUDY_SCHEMA_VERSION, created_at=now, updated_at=now)
        return StudyPlan(
            schema_version=max(int(row["schema_version"]), STUDY_SCHEMA_VERSION), plan_id=row["plan_id"],
            title=row["title"], daily_target=int(row["daily_target"]), paused=bool(row["paused"]),
            timezone=row["timezone"], created_at=row["created_at"], updated_at=row["updated_at"],
        )
    finally:
        connection.close()


def update_study_plan(title: str, daily_target: int, paused: bool) -> StudyPlan:
    current = get_study_plan()
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        connection.execute(
            "UPDATE study_plans SET schema_version=?, title=?, daily_target=?, paused=?, updated_at=? WHERE plan_id='default'",
            (STUDY_SCHEMA_VERSION, str(title or "本地学习计划")[:120], max(1, min(int(daily_target), 200)), int(bool(paused)), now),
        )
        connection.commit()
        return current.model_copy(update={"schema_version": STUDY_SCHEMA_VERSION, "title": str(title or "本地学习计划")[:120], "daily_target": max(1, min(int(daily_target), 200)), "paused": bool(paused), "updated_at": now})
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
    start_date = (now - timedelta(days=days - 1)).date()
    plan = get_study_plan()
    summary = study_summary()
    due = due_cards(cap)
    cards = list_cards(limit=1000)
    connection = _connect()
    try:
        activity_rows = connection.execute(
            """SELECT substr(reviewed_at, 1, 10) AS day, COUNT(*) AS count
               FROM study_reviews WHERE reviewed_at >= ?
               GROUP BY substr(reviewed_at, 1, 10) ORDER BY day ASC""",
            (datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat(),),
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
    finally:
        connection.close()

    activity_by_day = {str(row["day"]): int(row["count"]) for row in activity_rows}
    activity = []
    for offset in range(days):
        day = (start_date + timedelta(days=offset)).isoformat()
        activity.append({"date": day, "review_count": activity_by_day.get(day, 0)})

    mastery = {"new": 0, "learning": 0, "needs_attention": 0, "retained": 0}
    for card in cards:
        if card.status != "active":
            continue
        if card.reps == 0:
            mastery["new"] += 1
        elif card.lapses > 0:
            mastery["needs_attention"] += 1
        elif card.stability >= 21:
            mastery["retained"] += 1
        else:
            mastery["learning"] += 1

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
            "has_cards": bool(cards),
            "primary_action": "create_evidence_grounded_cards" if not cards else ("resume_plan" if plan.paused else "review_due_cards"),
        },
    }
