"""Local course manifests and explicitly cited cross-source comparisons."""
from __future__ import annotations

import json
import re
from uuid import uuid4

from .config import DATA_DIR
from .knowledge import answer_from_evidence, evidence_by_ids, evidence_ids_for_task
from .library import get_material, task_material_source_uri
from .source_input import normalize_source_input
from .storage import atomic_write_text, get_task
from .concept_identity import read_history, edit_identity
from .course_comparison import build_comparison, is_canonical_evidence
from . import course_state

def course_transaction():
    """Serialize course writes and final episode admission across processes."""
    return course_state.course_transaction(DATA_DIR)


def course_read_lock():
    return course_state.course_read_lock()


def _path(course_id: str):
    return course_state.course_path(DATA_DIR, course_id)


def get_course(course_id: str) -> dict:
    return course_state.read_course(DATA_DIR, course_id)


def list_courses() -> list[dict]:
    courses = []
    for path in sorted((DATA_DIR / "courses").glob("*.json")):
        try:
            course = get_course(path.stem)
            courses.append({key: course[key] for key in ("id", "title", "paused", "revision")})
        except (ValueError, KeyError, OSError):
            courses.append({"id": path.stem, "title": "课程记录需要修复", "paused": True, "revision": 0})
    return courses


def save_course(title: str, sources: list[dict], paused: bool = False, course_id: str = "", revision: int = 0) -> dict:
    if not title.strip() or len(sources) > 200:
        raise ValueError("invalid_course_content")
    with course_transaction():
        previous_sources = {}
        if course_id:
            previous = get_course(course_id)
            previous_sources = {(item["kind"], item["id"]): item for item in previous["sources"]}
            if previous["revision"] != revision:
                raise ValueError("course_changed_reload_required")
        else:
            if len(list_courses()) >= 1000:
                raise ValueError("course_limit_reached")
            course_id = uuid4().hex
        normalized, seen = [], set()
        for source in sources:
            kind = source["kind"]
            item = {"kind": kind, "id": source.get("id", ""), "url": "", "title": ""}
            if kind == "url":
                value = normalize_source_input(source.get("url", ""))
                item.update(url=value.url, title=value.default_title, id="")
                key = (kind, value.url)
            else:
                try:
                    value = get_task(item["id"]) if kind == "task" else get_material(item["id"])
                    item["title"] = value.title if kind == "task" else value["title"]
                except (FileNotFoundError, ValueError):
                    # Retain explicitly existing orphaned references so a
                    # renamed/deleted source cannot erase the course silently.
                    old = previous_sources.get((kind, item["id"]))
                    if old is None:
                        raise ValueError("course_source_missing")
                    item["title"] = old["title"]
                key = (kind, item["id"])
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        course = {"schema_version": 1, "id": course_id, "title": title.strip(), "sources": normalized, "paused": paused, "revision": revision + 1}
        atomic_write_text(_path(course_id), json.dumps(course, ensure_ascii=False, indent=2))
        # Saving sources is an explicit write workflow. Adopt resolved reuse
        # here so later option changes cannot silently detach a saved course;
        # ordinary reads and deletion previews must remain side-effect free.
        from .course_episodes import course_episodes, bind_course_episode
        for episode in course_episodes(course):
            if episode["source_kind"] == "url" and episode.get("task_id"):
                bind_course_episode(course, episode["episode_id"], episode["task_id"])
        return course


def delete_course(course_id: str) -> None:
    # Removing a collection is not authorization to delete its source files.
    from .assistant_operation_store import source_deletion
    with source_deletion("course", course_id, DATA_DIR), course_transaction():
        path = _path(course_id)
        if not path.exists():
            raise FileNotFoundError(course_id)
        from .course_episodes import clear_course_episode_links
        clear_course_episode_links(course_id)
        path.unlink()


def set_course_paused(course_id: str, revision: int, paused: bool, operation_id: str) -> dict:
    """Commit an explicit pause value without rewriting membership or titles."""
    if type(paused) is not bool or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", operation_id):
        raise ValueError("invalid_course_control")
    with course_transaction():
        course = get_course(course_id)
        marker = course.get("control_operation") or {}
        if marker.get("id") == operation_id:
            if marker.get("before_revision") != revision or marker.get("paused") != paused:
                raise ValueError("course_operation_conflict")
            return course
        if course["revision"] != revision:
            raise ValueError("course_changed_reload_required")
        course["control_operation"] = {"id": operation_id, "before_revision": revision,
                                       "before_paused": course["paused"], "paused": paused}
        course["paused"] = paused
        course["revision"] = revision + 1
        atomic_write_text(_path(course_id), json.dumps(course, ensure_ascii=False, indent=2))
        return get_course(course_id)


def _evidence_sources(course: dict, *, read_only=False) -> list[dict]:
    if not any(source["kind"] == "url" for source in course["sources"]):
        return course["sources"]
    from .course_episodes import course_episodes
    episodes = {item["position"]: item for item in course_episodes(course, read_only=read_only)}
    return [{"kind":"task", "id":episodes[index]["task_id"], "title":source["title"]}
            if source["kind"] == "url" and episodes.get(index, {}).get("task_id") else source
            for index, source in enumerate(course["sources"])]


def course_evidence(course_id: str) -> list[dict]:
    evidence = []
    sources_by_id = {}
    for source in _evidence_sources(get_course(course_id)):
        for evidence_id in sorted(_source_evidence_ids(source)):
            sources_by_id.setdefault(evidence_id, source)
    # Resolve every scoped ID in bounded batches. Generated/review rows cannot
    # starve a valid later citation, and registered videos use live task IDs.
    if len(sources_by_id) > 100_000:
        raise ValueError("comparison_scope_too_large")
    ids = list(sources_by_id)
    for start in range(0, len(ids), 500):
        for item in evidence_by_ids(ids[start:start + 500], limit=500):
            if not is_canonical_evidence(item):
                continue
            evidence_id = str(item.get("evidence_id") or "")
            if evidence_id not in sources_by_id:
                continue
            source = sources_by_id[evidence_id]
            evidence.append({**item, "course_source": {"kind": source["kind"], "id": source["id"], "title": source["title"]}})
    return evidence


def _source_evidence_ids(source: dict) -> set[str]:
    try:
        material = get_material(source["id"]) if source["kind"] == "material" else None
        task_id = source["id"] if source["kind"] == "task" else (material or {}).get("linked_task_id")
        if task_id:
            # Only canonical registered videos can alias a task. Recheck the
            # owner too: older evidence may predate row-level review flags.
            if material and (material.get("source_type") != "video" or material.get("owns_evidence") is not False):
                return set()
            owner = get_task(task_id)
            if owner.id != task_id or owner.summary_source == "transcript-draft" or owner.summary_diagnostics.get("review_required"):
                return set()
            if material and material.get("source_uri") != task_material_source_uri(owner):
                return set()
            return evidence_ids_for_task(task_id)
        return set(material["evidence_ids"]) if material else set()
    except (ValueError, FileNotFoundError):
        return set()


def course_evidence_ids(course_id: str) -> set[str]:
    ids: set[str] = set()
    for source in _evidence_sources(get_course(course_id)):
        ids.update(_source_evidence_ids(source))
    return ids


def ask_course(course_id: str, question: str, revision: int, limit: int = 6, mode: str = "lexical") -> dict:
    # Read the approved revision and its membership under the same transaction
    # as save/delete. A stale client must explicitly reload its chosen scope.
    with course_transaction():
        course = get_course(course_id)
        if course["revision"] != revision:
            raise ValueError("course_changed_reload_required")
        answer = answer_from_evidence(question, limit, mode, evidence_ids=course_evidence_ids(course_id), canonical_only=True)
        answer["scope"] = {"kind": "course", "id": course_id, "title": course["title"], "revision": course["revision"]}
        if not answer["grounded"]:
            answer["answer"] = "本课程中没有找到足够的原始证据，未生成无依据答案。可更换关键词，或检查课程中的资料是否已完成索引。"
        else:
            answer["answer"] = str(answer["answer"]).replace("根据资料库中的可追溯证据：", "本课程中的原文摘录（本地检索，未进行模型综合）：", 1)
        return answer


def compare_course(course_id: str, query: str, *, source_id: str = "", source_kind: str = "", start: float | None = None, end: float | None = None) -> dict:
    return build_comparison(course_evidence(course_id), read_history(course_id), query,
                            source_id=source_id, source_kind=source_kind, start=start, end=end)


def edit_course_identity(course_id: str, request_id: str, request: dict) -> dict:
    with course_transaction():
        course = get_course(course_id)
        return edit_identity(course_id, course["revision"], course_evidence(course_id), request_id, request)
