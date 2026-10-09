"""Deterministic, local evidence cloze questions, separate from FSRS self-ratings."""
from __future__ import annotations

import hashlib
import json
import re


SCORER = "evidence-cloze-exact-v1"


def initialize_tables(connection):
    # Additive migration: old ratings and generic answer events remain unscored.
    connection.execute("""CREATE TABLE IF NOT EXISTS study_quiz_attempts (
        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT NOT NULL,
        question_revision TEXT NOT NULL, question TEXT NOT NULL,
        expected_answer TEXT NOT NULL, submitted_answer TEXT NOT NULL,
        correct INTEGER NOT NULL, source_evidence_ids TEXT NOT NULL,
        attempted_at TEXT NOT NULL, scorer TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, UNIQUE(card_id, idempotency_key)
    )""")


def normalize_answer(value: str) -> str:
    """Ignore case and whitespace only; never infer semantic equivalence."""
    return " ".join(value.split()).casefold()


def build_question(card, quiz_evidence_eligible):
    from .knowledge import evidence_by_ids

    sources = evidence_by_ids(card.source_evidence_ids, limit=8)
    eligible = [item for item in sources if quiz_evidence_eligible(item)]
    # Require the exact card answer to occur in a canonical source. Edited or
    # inferred answers can still be self-reviewed, but cannot become scored facts.
    quote = card.back.strip()
    grounded = [item for item in eligible if quote and quote in str(item.get("text") or "")]
    if not grounded or not 20 <= len(quote) <= 500:
        return None
    match = re.match(
        r"^([A-Za-z][A-Za-z0-9 '\-]{1,60}?)\s+(?:is|are|means|refers to|represents|requires|depends on|causes|allows|contains|includes|controls)\s+[^.!?。！？]{8,400}[.!?。！？]$",
        quote, re.IGNORECASE,
    ) or re.match(r"^([^。！？.!?\n，,：:]{2,24}?)(?:是|指的是|决定|影响|表示|用于|提供|包含|意味着).{8,400}[。！？.!?]$", quote)
    if not match:
        return None
    expected = match.group(1)
    if re.match(r"^(this|that|it|they|we|you|he|she|there)\b", expected, re.IGNORECASE) or expected in {"这", "这个", "它", "他们", "我们"}:
        return None
    # Hide all occurrences of the answer, including a repeated subject.
    prompt = re.sub(re.escape(expected), "____", quote, flags=re.IGNORECASE)
    source_ids = sorted(str(item["evidence_id"]) for item in grounded)
    revision_input = [SCORER, card.card_id, card.front, card.back, source_ids,
                      [str(item.get("text") or "") for item in sorted(grounded, key=lambda item: item["evidence_id"])]]
    revision = hashlib.sha256(json.dumps(revision_input, ensure_ascii=False).encode()).hexdigest()
    return {"kind": "evidence_cloze", "question": prompt, "expected_answer": expected,
            "question_revision": revision, "source_evidence_ids": source_ids, "scorer": SCORER}


def _attempt(row):
    item = dict(row)
    item["correct"] = bool(item["correct"])
    item["source_evidence_ids"] = json.loads(item["source_evidence_ids"])
    return item


def export_attempts(connection):
    return [_attempt(row) for row in connection.execute("SELECT a.* FROM study_quiz_attempts a JOIN study_cards c ON c.card_id=a.card_id WHERE c.status!='deleted' ORDER BY a.attempt_id")]


def validate_attempts(raw_attempts, card_ids, parse_datetime):
    if not isinstance(raw_attempts, list) or len(raw_attempts) > 500_000:
        raise ValueError("study_backup_quiz_invalid")
    attempts = []
    for raw in raw_attempts:
        if not isinstance(raw, dict):
            raise ValueError("study_backup_quiz_invalid")
        item = {key: raw.get(key) for key in ("card_id", "question_revision", "question", "expected_answer", "submitted_answer", "correct", "source_evidence_ids", "attempted_at", "scorer", "idempotency_key")}
        if (not isinstance(item["card_id"], str) or item["card_id"] not in card_ids or item["scorer"] != SCORER
            or not isinstance(item["correct"], bool)
            or any(not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > cap
                   for key, cap in (("question", 500), ("expected_answer", 128), ("submitted_answer", 128), ("question_revision", 64), ("idempotency_key", 128), ("attempted_at", 64)))
            or not re.fullmatch(r"[a-f0-9]{64}", item["question_revision"])
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", item["idempotency_key"])
            or not isinstance(item["source_evidence_ids"], list) or not 1 <= len(item["source_evidence_ids"]) <= 8
            or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in item["source_evidence_ids"])
            or parse_datetime(item["attempted_at"]) is None
            or item["correct"] != (normalize_answer(item["submitted_answer"]) == normalize_answer(item["expected_answer"]))):
            raise ValueError("study_backup_quiz_invalid")
        attempts.append(item)
    return attempts


def restore_attempts(connection, attempts):
    restored = 0
    for item in attempts:
        restored += max(0, connection.execute("""INSERT OR IGNORE INTO study_quiz_attempts
            (card_id,question_revision,question,expected_answer,submitted_answer,correct,
             source_evidence_ids,attempted_at,scorer,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (item["card_id"], item["question_revision"], item["question"], item["expected_answer"], item["submitted_answer"], int(item["correct"]),
             json.dumps(item["source_evidence_ids"]), item["attempted_at"], item["scorer"], item["idempotency_key"])).rowcount)
    return restored


def learning_measures(connection):
    activity = {row["kind"]: int(row["n"]) for row in connection.execute("SELECT kind,COUNT(*) n FROM study_activity GROUP BY kind")}
    attempts = connection.execute("SELECT COUNT(*) n, COALESCE(SUM(a.correct),0) correct FROM study_quiz_attempts a JOIN study_cards c ON c.card_id=a.card_id WHERE c.status!='deleted'").fetchone()
    ratings = connection.execute("SELECT COUNT(*) FROM study_reviews r JOIN study_cards c ON c.card_id=r.card_id WHERE c.status!='deleted'").fetchone()[0]
    return {"scope": "all_sources", "reading_events": activity.get("reading", 0),
            "objective_attempts": int(attempts["n"]), "correct_answers": int(attempts["correct"]),
            "incorrect_answers": int(attempts["n"] - attempts["correct"]),
            "unscored_answer_events": activity.get("answer", 0),
            "self_explanations": activity.get("self_assessment", 0), "self_ratings": int(ratings),
            "correctness_basis": SCORER, "legacy_correctness": "unknown"}


def objective_mistakes(connection, evidence_ids, limit):
    items = []
    for row in connection.execute("SELECT a.* FROM study_quiz_attempts a JOIN study_cards c ON c.card_id=a.card_id WHERE a.correct=0 AND c.status!='deleted' ORDER BY a.attempted_at DESC,a.attempt_id DESC"):
        item = _attempt(row)
        if evidence_ids is not None and not evidence_ids.intersection(item["source_evidence_ids"]):
            continue
        items.append({**item, "answer": item["expected_answer"], "reviewed_at": item["attempted_at"], "basis": "objective_answer"})
        if len(items) >= limit:
            break
    return items
