"""Independent learning spaces built on source references and the shared FSRS store.

Spaces intentionally contain IDs, not copies of notes, subtitles or media.  A
legacy course is migrated lazily and idempotently into the same shape; the
old course API remains the compatibility surface for older clients.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import DATA_DIR
from .knowledge import evidence_for_task, evidence_ids_for_task
from .library import get_material, material_anchors
from .source_input import normalize_source_input
from .storage import atomic_write_text, get_task

SPACE_SCHEMA_VERSION = 1
EXISTING_REVIEW_ID = "existing-review"
_lock = threading.RLock()


def _space_root() -> Path:
    return DATA_DIR / "learning-spaces"


def _space_path(space_id: str) -> Path:
    value = str(space_id or "")
    if value != EXISTING_REVIEW_ID and not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("invalid_learning_space_id")
    return _space_root() / f"{value}.json"


def _practice_path(space_id: str) -> Path:
    _space_path(space_id)
    return _space_root() / f"{space_id}.practice.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live_source(kind: str, source_id: str) -> tuple[str, str, str]:
    if kind == "task":
        task = get_task(source_id)
        return task.title, task.updated_at, task.page_url
    if kind == "material":
        material = get_material(source_id)
        return str(material["title"]), str(material.get("updated_at") or ""), str(material.get("source_uri") or "")
    raise ValueError("learning_space_source_missing")


def _normalize_sources(sources: list[dict], previous: dict[tuple[str, str], dict] | None = None) -> list[dict]:
    previous = previous or {}
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in sources[:200]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if kind == "url":
            normalized = normalize_source_input(str(raw.get("url") or ""))
            item = {
                "kind": "url", "id": "", "url": normalized.url,
                "title": str(raw.get("title") or normalized.default_title)[:500],
                "source_revision": "",
            }
            key = (kind, item["url"])
        elif kind in {"task", "material"}:
            source_id = str(raw.get("id") or "")
            try:
                title, revision, source_uri = _live_source(kind, source_id)
            except (FileNotFoundError, ValueError):
                old = previous.get((kind, source_id))
                if old is None:
                    raise ValueError("learning_space_source_missing")
                title, revision, source_uri = str(old.get("title") or source_id), str(old.get("source_revision") or ""), str(old.get("source_uri") or "")
            item = {
                "kind": kind, "id": source_id[:128], "url": "",
                "title": title[:500], "source_revision": revision,
                "source_uri": source_uri[:2000],
            }
            key = (kind, source_id)
        else:
            raise ValueError("learning_space_source_kind_invalid")
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _default_existing_review() -> dict:
    now = _now()
    return {
        "schema_version": SPACE_SCHEMA_VERSION,
        "id": EXISTING_REVIEW_ID,
        "title": "已有复习",
        "goal": "复用已有卡片和评分记录",
        "focus": "",
        "daily_review_limit": 10,
        "question_types": ["short_answer"],
        "sources": [],
        "paused": False,
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "legacy": False,
    }


def migrate_courses_to_learning_spaces() -> dict[str, int]:
    """Copy only legacy manifests; running this repeatedly is a no-op."""
    root = _space_root()
    root.mkdir(parents=True, exist_ok=True)
    migrated = 0
    skipped = 0
    courses_root = DATA_DIR / "courses"
    with _lock:
        for path in sorted(courses_root.glob("*.json")) if courses_root.is_dir() else []:
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            target = _space_path(path.stem)
            if target.exists():
                skipped += 1
                continue
            try:
                course = json.loads(path.read_text(encoding="utf-8"))
                sources = _normalize_sources(course.get("sources") or [])
                now = _now()
                space = {
                    "schema_version": SPACE_SCHEMA_VERSION,
                    "id": path.stem,
                    "title": str(course.get("title") or "未命名学习空间")[:200],
                    "goal": "完成这组资料的理解与复习",
                    "focus": "",
                    "daily_review_limit": 10,
                    "question_types": ["short_answer"],
                    "sources": sources,
                    "paused": bool(course.get("paused")),
                    "revision": int(course.get("revision") or 0) or 1,
                    "created_at": now,
                    "updated_at": now,
                    "legacy": True,
                    "legacy_course_id": path.stem,
                }
                atomic_write_text(target, json.dumps(space, ensure_ascii=False, indent=2))
                try:
                    from .study import assign_cards_to_space
                    evidence_ids = {str(item.get("evidence_id")) for item in space_evidence(path.stem, 2000) if item.get("evidence_id")}
                    assign_cards_to_space(path.stem, evidence_ids=evidence_ids)
                except (OSError, ValueError, RuntimeError):
                    # Membership is additive and can be rebuilt on the next
                    # open; never block reading a legacy course on a study DB.
                    pass
                migrated += 1
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                skipped += 1
    return {"migrated": migrated, "skipped": skipped}


def _ensure_existing_review() -> None:
    path = _space_path(EXISTING_REVIEW_ID)
    if not path.exists():
        atomic_write_text(path, json.dumps(_default_existing_review(), ensure_ascii=False, indent=2))


def get_learning_space(space_id: str) -> dict:
    migrate_courses_to_learning_spaces()
    _ensure_existing_review()
    try:
        return json.loads(_space_path(space_id).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(space_id) from exc


def list_learning_spaces() -> list[dict]:
    migrate_courses_to_learning_spaces()
    _ensure_existing_review()
    items = []
    for path in sorted(_space_root().glob("*.json")):
        if ".practice" in path.name:
            continue
        try:
            space = json.loads(path.read_text(encoding="utf-8"))
            items.append({key: space.get(key) for key in (
                "id", "title", "goal", "focus", "daily_review_limit", "question_types", "paused", "revision", "legacy"
            )})
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            items.append({"id": path.stem, "title": "学习空间需要修复", "paused": True, "revision": 0})
    return items


def save_learning_space(
    title: str,
    sources: list[dict],
    *,
    goal: str = "",
    focus: str = "",
    daily_review_limit: int = 10,
    question_types: list[str] | None = None,
    paused: bool = False,
    space_id: str = "",
    revision: int = 0,
) -> dict:
    if not str(title or "").strip() or len(sources) > 200:
        raise ValueError("invalid_learning_space_content")
    if not 1 <= int(daily_review_limit) <= 200:
        raise ValueError("invalid_daily_review_limit")
    types = [str(item).strip() for item in (question_types or ["short_answer"]) if str(item).strip()][:12]
    if not types:
        types = ["short_answer"]
    with _lock:
        previous: dict = {}
        if space_id:
            previous = get_learning_space(space_id)
            if int(previous.get("revision") or 0) != int(revision):
                raise ValueError("learning_space_changed_reload_required")
        else:
            if len(list_learning_spaces()) >= 1000:
                raise ValueError("learning_space_limit_reached")
            space_id = uuid4().hex
        previous_sources = {(item.get("kind"), item.get("id")): item for item in previous.get("sources", [])}
        normalized = _normalize_sources(sources, previous_sources)
        now = _now()
        space = {
            "schema_version": SPACE_SCHEMA_VERSION,
            "id": space_id,
            "title": str(title).strip()[:200],
            "goal": str(goal or "").strip()[:1000],
            "focus": str(focus or "").strip()[:2000],
            "daily_review_limit": int(daily_review_limit),
            "question_types": types,
            "sources": normalized,
            "paused": bool(paused),
            "revision": int(revision) + 1,
            "created_at": previous.get("created_at") or now,
            "updated_at": now,
            "legacy": bool(previous.get("legacy", False)),
            **({"legacy_course_id": previous["legacy_course_id"]} if previous.get("legacy_course_id") else {}),
        }
        atomic_write_text(_space_path(space_id), json.dumps(space, ensure_ascii=False, indent=2))
        return space


def delete_learning_space(space_id: str) -> None:
    if space_id == EXISTING_REVIEW_ID:
        raise ValueError("existing_review_space_cannot_be_deleted")
    with _lock:
        _space_path(space_id).unlink()
        practice = _practice_path(space_id)
        if practice.exists():
            practice.unlink()


def space_evidence(space_id: str, limit: int = 1000) -> list[dict]:
    space = get_learning_space(space_id)
    evidence: list[dict] = []
    for source in space.get("sources", []):
        try:
            if source["kind"] == "task":
                items = evidence_for_task(source["id"], limit=limit)
            elif source["kind"] == "material":
                items = material_anchors(source["id"], limit)
            else:
                items = []
        except (FileNotFoundError, ValueError, OSError):
            items = []
        for item in items:
            if item.get("metadata", {}).get("kind") in {"note", "community"}:
                continue
            evidence.append({
                **item,
                "space_source": {"kind": source["kind"], "id": source["id"], "title": source.get("title", "")},
            })
            if len(evidence) >= max(1, min(int(limit), 2000)):
                return evidence
    return evidence


def space_evidence_ids(space_id: str) -> set[str]:
    return {str(item.get("evidence_id")) for item in space_evidence(space_id, 2000) if item.get("evidence_id")}


def source_refresh_status(space_id: str) -> list[dict]:
    space = get_learning_space(space_id)
    result = []
    for source in space.get("sources", []):
        if source.get("kind") == "url":
            result.append({**source, "stale": False, "status": "pending"})
            continue
        try:
            title, revision, uri = _live_source(source["kind"], source["id"])
            stale = bool(source.get("source_revision") and revision and source.get("source_revision") != revision)
            result.append({**source, "title": title, "source_uri": uri, "stale": stale, "status": "stale" if stale else "ready"})
        except (FileNotFoundError, ValueError, OSError):
            result.append({**source, "stale": True, "status": "missing"})
    return result


def _read_practice(space_id: str) -> list[dict]:
    path = _practice_path(space_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", []) if isinstance(data, dict) and isinstance(data.get("items"), list) else []
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def propose_space_practice(space_id: str, limit: int = 20) -> list[dict]:
    from .study import propose_cards
    from .models import SourceEvidence

    evidence = [SourceEvidence.model_validate(item) for item in space_evidence(space_id, 1000)]
    proposals = []
    question_types = get_learning_space(space_id).get("question_types") or ["short_answer"]
    for index, card in enumerate(propose_cards(evidence, limit=max(1, min(int(limit), 100)))):
        proposals.append({
            "id": uuid4().hex,
            "question": card.front,
            "answer": card.back,
            "source_evidence_ids": card.source_evidence_ids,
            "question_type": question_types[index % len(question_types)],
            "status": "proposed",
        })
    return proposals


def save_space_practice(space_id: str, items: list[dict]) -> list[dict]:
    get_learning_space(space_id)
    existing = _read_practice(space_id)
    by_key = {(str(item.get("question")), str(item.get("answer"))): item for item in existing}
    saved = []
    valid_ids = space_evidence_ids(space_id)
    for raw in items[:100]:
        if not isinstance(raw, dict):
            continue
        question, answer = str(raw.get("question") or "").strip()[:1000], str(raw.get("answer") or "").strip()[:4000]
        evidence_ids = [str(value)[:128] for value in (raw.get("source_evidence_ids") or [])[:8] if str(value) in valid_ids]
        if not question or not answer or not evidence_ids:
            continue
        item = by_key.get((question, answer)) or {"id": uuid4().hex}
        item.update({"question": question, "answer": answer, "source_evidence_ids": evidence_ids, "status": "active", "saved_at": _now()})
        by_key[(question, answer)] = item
        saved.append(item)
    merged = list(by_key.values())
    atomic_write_text(_practice_path(space_id), json.dumps({"schema_version": 1, "items": merged}, ensure_ascii=False, indent=2))
    return saved


def list_space_practice(space_id: str) -> list[dict]:
    get_learning_space(space_id)
    return _read_practice(space_id)


def space_summary(space_id: str) -> dict:
    from .study import due_cards, list_cards, unassigned_cards

    space = get_learning_space(space_id)
    evidence_ids = space_evidence_ids(space_id)
    cards = unassigned_cards(500) if space_id == EXISTING_REVIEW_ID else list_cards(limit=500)
    scoped = [card for card in cards if space_id == EXISTING_REVIEW_ID or evidence_ids.intersection(card.source_evidence_ids)]
    due = due_cards(200, None if space_id == EXISTING_REVIEW_ID else evidence_ids)
    if space_id == EXISTING_REVIEW_ID:
        unassigned_ids = {card.card_id for card in scoped}
        due = [card for card in due if card.card_id in unassigned_ids]
    return {
        "space_id": space_id,
        "source_count": len(space.get("sources", [])),
        "evidence_count": len(evidence_ids),
        "card_count": len(scoped),
        "due_count": len({card.card_id for card in due}),
        "practice_count": len(list_space_practice(space_id)),
        "sources": source_refresh_status(space_id),
    }
