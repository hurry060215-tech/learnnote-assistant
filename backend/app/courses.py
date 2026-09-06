"""Local course manifests and explicitly cited cross-source comparisons."""
from __future__ import annotations

import json
import re
import threading
from uuid import uuid4

from .config import DATA_DIR
from .knowledge import evidence_for_task, evidence_ids_for_task
from .library import get_material, material_anchors
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


def course_evidence(course_id: str) -> list[dict]:
    evidence = []
    for source in get_course(course_id)["sources"]:
        try:
            items = evidence_for_task(source["id"], limit=500) if source["kind"] == "task" else material_anchors(source["id"], 1000) if source["kind"] == "material" else []
        except (ValueError, FileNotFoundError):
            continue
        for item in items:
            if item.get("metadata", {}).get("kind") in {"note", "community"}:
                continue
            evidence.append({**item, "course_source": {"kind": source["kind"], "id": source["id"], "title": source["title"]}})
    return evidence


def course_evidence_ids(course_id: str) -> set[str]:
    ids: set[str] = set()
    for source in get_course(course_id)["sources"]:
        try:
            if source["kind"] == "task":
                ids.update(evidence_ids_for_task(source["id"]))
            elif source["kind"] == "material":
                ids.update(get_material(source["id"])["evidence_ids"])
        except (ValueError, FileNotFoundError):
            continue
    return ids


def compare_course(course_id: str, query: str) -> dict:
    terms = list(dict.fromkeys(term.casefold() for term in query.split() if term.strip()))[:8]
    matches = []
    groups: dict[str, dict] = {}
    for item in course_evidence(course_id):
        text = str(item.get("text") or "")
        hits = [term for term in terms if term in text.casefold()]
        if not hits:
            continue
        start = min(text.casefold().find(term) for term in hits)
        excerpt = text[max(0, start - 80):start + 440]
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
    return {"mode": "local_cited_comparison", "query": query, "matches": matches[:100], "total_matches": len(matches), "nodes": nodes, "edges": edges[:100], "inference": False, "warning": "共同关键词不代表同义、因果或观点一致，请核对各自原文。"}
