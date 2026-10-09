"""Local course manifests and explicitly cited cross-source comparisons."""
from __future__ import annotations

import json
import re
import math
import threading
from uuid import uuid4

from .config import DATA_DIR
from .knowledge import answer_from_evidence, evidence_for_task, evidence_ids_for_task
from .library import get_material, material_anchors, task_material_source_uri
from .source_input import normalize_source_input
from .storage import atomic_write_text, get_task

_lock = threading.RLock()


def _path(course_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", course_id):
        raise ValueError("invalid_course_id")
    return DATA_DIR / "courses" / f"{course_id}.json"


def get_course(course_id: str) -> dict:
    return json.loads(_path(course_id).read_text(encoding="utf-8"))


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
    with _lock:
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
        return course


def delete_course(course_id: str) -> None:
    # Removing a collection is not authorization to delete its source files.
    with _lock:
        _path(course_id).unlink()
        from .course_episodes import clear_course_episode_links
        clear_course_episode_links(course_id)


def _evidence_sources(course: dict) -> list[dict]:
    if not any(source["kind"] == "url" for source in course["sources"]):
        return course["sources"]
    from .course_episodes import course_episodes
    episodes = {item["position"]: item for item in course_episodes(course)}
    return [{"kind":"task", "id":episodes[index]["task_id"], "title":source["title"]}
            if source["kind"] == "url" and episodes.get(index, {}).get("task_id") else source
            for index, source in enumerate(course["sources"])]


def course_evidence(course_id: str) -> list[dict]:
    evidence = []
    seen_ids: set[str] = set()
    for source in _evidence_sources(get_course(course_id)):
        try:
            items = evidence_for_task(source["id"], limit=500) if source["kind"] == "task" else material_anchors(source["id"], 1000) if source["kind"] == "material" else []
        except (ValueError, FileNotFoundError):
            continue
        for item in items:
            if item.get("metadata", {}).get("kind") in {"note", "community"}:
                continue
            evidence_id = str(item.get("evidence_id") or "")
            if not evidence_id or evidence_id in seen_ids:
                continue
            seen_ids.add(evidence_id)
            evidence.append({**item, "course_source": {"kind": source["kind"], "id": source["id"], "title": source["title"]}})
    return evidence


def course_evidence_ids(course_id: str) -> set[str]:
    ids: set[str] = set()
    for source in _evidence_sources(get_course(course_id)):
        try:
            material = get_material(source["id"]) if source["kind"] == "material" else None
            task_id = source["id"] if source["kind"] == "task" else (material or {}).get("linked_task_id")
            if task_id:
                # Only the canonical registered-video relation can alias a
                # task. Free-form document metadata cannot broaden membership.
                if material and (material.get("source_type") != "video" or material.get("owns_evidence") is not False):
                    continue
                # Recheck the owner as well as row metadata: older projections
                # may predate review flags, or survive a missing source file.
                owner = get_task(task_id)
                if owner.id != task_id or owner.summary_source == "transcript-draft" or owner.summary_diagnostics.get("review_required"):
                    continue
                if material and material.get("source_uri") != task_material_source_uri(owner):
                    continue
            if task_id:
                # A registered video is an alias for this task, not a frozen
                # first-page snapshot of the task's evidence at registration.
                ids.update(evidence_ids_for_task(task_id))
            elif material:
                ids.update(material["evidence_ids"])
        except (ValueError, FileNotFoundError):
            continue
    return ids


def ask_course(course_id: str, question: str, revision: int, limit: int = 6, mode: str = "lexical") -> dict:
    # Keep the course revision and its membership consistent with save/delete
    # in this process. A stale client must explicitly reload its chosen scope.
    with _lock:
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
    if source_kind not in {"", "task", "material"} or any(value is not None and (not math.isfinite(value) or value < 0) for value in (start, end)) or (start is not None and end is not None and end < start):
        raise ValueError("invalid_comparison_filter")
    terms = list(dict.fromkeys(term.casefold() for term in query.split() if term.strip()))[:8]
    matches = []
    groups: dict[str, dict] = {}
    for item in course_evidence(course_id):
        source = item["course_source"]
        if (source_id and source["id"] != source_id) or (source_kind and source["kind"] != source_kind):
            continue
        if start is not None or end is not None:
            metadata = item.get("metadata") or {}
            located = re.match(r"^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s$", str(item.get("locator") or ""))
            left, right = metadata.get("start"), metadata.get("end")
            if left is None or right is None:
                if not located:
                    continue
                left, right = map(float, located.groups())
            try:
                left, right = float(left), float(right)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(left) or not math.isfinite(right) or (start is not None and right < start) or (end is not None and left > end):
                continue
        text = str(item.get("text") or "")
        hits = [term for term in terms if term in text.casefold()]
        if not hits:
            continue
        match_offset = min(text.casefold().find(term) for term in hits)
        excerpt = text[max(0, match_offset - 80):match_offset + 440]
        source = item["course_source"]
        key = f"{source['kind']}:{source['id']}"
        groups.setdefault(key, {"id": key, "title": source["title"], "evidence_ids": [], "terms": [], "term_evidence": {}})
        groups[key]["evidence_ids"].append(item["evidence_id"])
        groups[key]["terms"] = sorted(set(groups[key]["terms"] + hits))
        for term in hits:
            groups[key]["term_evidence"].setdefault(term, item["evidence_id"])
        matches.append({"evidence_id": item["evidence_id"], "title": source["title"], "locator": item["locator"], "excerpt": excerpt, "matched_terms": hits, "source": source})
    nodes = list(groups.values())[:40]
    edges = []
    for index, left in enumerate(nodes):
        for right in nodes[index + 1:]:
            shared = sorted(set(left["terms"]) & set(right["terms"]))
            if shared:
                edges.append({"from": left["id"], "to": right["id"], "kind": "keyword_cooccurrence", "terms": shared, "evidence_ids": [left["term_evidence"][shared[0]], right["term_evidence"][shared[0]]]})
    return {"mode": "local_cited_comparison", "query": query, "matches": matches[:100], "total_matches": len(matches), "nodes": nodes, "edges": edges[:100], "inference": False, "filters": {"source_id": source_id, "source_kind": source_kind, "start": start, "end": end}, "warning": "共同关键词不代表同义、因果或观点一致，请核对各自原文。"}
