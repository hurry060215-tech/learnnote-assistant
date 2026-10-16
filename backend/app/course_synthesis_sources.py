"""Read-only, bounded original evidence for one explicitly reviewed synthesis."""
from contextlib import closing
import json
import math
import sqlite3

from . import courses
from .course_comparison import is_canonical_evidence, time_bounds
from .course_episodes import course_episodes
from .course_graph_export import _belongs, _task_revision
from .graph_snapshot import digest
from .knowledge import _tokens

MAX_ANCHORS = 6
MAX_SOURCE_CHARACTERS = 24000
MAX_SCAN_ROWS = 10000
MAX_METADATA_CHARACTERS = 16384


def _json_value(text, limit):
    if not isinstance(text, str) or len(text) > limit:
        return None
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_metadata_key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")))
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 16 or type(item) in (int, float) and (abs(item) > 2**53 - 1 or not math.isfinite(item)):
                return None
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except (ValueError, TypeError, RecursionError):
        return None


def _valid_time_fields(metadata):
    if "start" not in metadata and "end" not in metadata:
        return True
    start, end = metadata.get("start"), metadata.get("end")
    return (type(start) in (int, float) and type(end) in (int, float)
            and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end)


def _owner(source, db, observed):
    if source["kind"] == "url":
        return None, "unindexed", None, []
    try:
        if source["kind"] == "material":
            sizes = db.execute("SELECT length(metadata_json), length(evidence_ids_json), instr(metadata_json,char(0)), instr(evidence_ids_json,char(0)) FROM library_materials WHERE material_id=?", (source["id"],)).fetchone()
            if sizes is None:
                return None, "missing", None, []
            if sizes[0] is None or sizes[0] > MAX_METADATA_CHARACTERS or sizes[2]:
                return None, "excluded", None, []
            if sizes[1] is None or sizes[1] > MAX_SCAN_ROWS * 132 or sizes[3]:
                return None, "scan_incomplete", None, []
            row = db.execute("SELECT * FROM library_materials WHERE material_id=?", (source["id"],)).fetchone()
            if row is None:
                return None, "missing", None, []
            material = dict(row)
            metadata = _json_value(material["metadata_json"] or "{}", MAX_METADATA_CHARACTERS)
            if (not isinstance(metadata, dict) or metadata.get("review_required")
                    or metadata.get("evidence_quality") == "review_required"):
                return None, "excluded", None, []
            task_id = material.get("linked_task_id")
            if not task_id:
                if not material.get("owns_evidence") or material.get("source_type") == "video" or material.get("source_uri") != f"local://materials/{source['id']}":
                    return None, "excluded", None, []
                if len(material["evidence_ids_json"]) > MAX_SCAN_ROWS * 132:
                    return None, "scan_incomplete", None, []
                ids = _json_value(material["evidence_ids_json"], MAX_SCAN_ROWS * 132)
                if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
                    raise ValueError("course_evidence_unavailable")
                if len(ids) > MAX_SCAN_ROWS:
                    return None, "scan_incomplete", None, []
                return {"kind": "material", "id": source["id"]}, "ready", digest(material), sorted(set(ids))
            if material.get("source_type") != "video" or material.get("owns_evidence") != 0:
                return None, "excluded", None, []
        else:
            task_id, material = source["id"], None
        task = courses.get_task(task_id)
        revision = _task_revision(task)
        if observed.setdefault(task_id, revision) != revision:
            raise ValueError("course_changed_reload_required")
        if (task.id != task_id or task.summary_source == "transcript-draft" or task.summary_diagnostics.get("review_required")
                or material and material.get("source_uri") != courses.task_material_source_uri(task)):
            return None, "excluded", revision, []
        return {"kind": "task", "id": task_id}, "ready", revision, []
    except FileNotFoundError:
        return None, "missing", None, []


def _rows(db, owner, ids, remaining, terms):
    rank = " + ".join("CASE WHEN instr(lower(substr(text,1,24001)),?) > 0 THEN 1 ELSE 0 END" for _ in terms) or "0"
    fields = f"evidence_id, source_type, title, source_uri, locator, task_id, substr(metadata_json,1,{MAX_METADATA_CHARACTERS + 1}) AS metadata_json, length(text) AS text_length, substr(text,1,24001) AS bounded_text, instr(text,char(0)) AS text_has_nul, instr(metadata_json,char(0)) AS metadata_has_nul"
    fields += f", ({rank}) AS lexical_rank"
    if owner["kind"] == "task":
        # The existing task_id index supports a bounded read. Sorting all of a
        # task's rows before LIMIT would defeat the scan ceiling. Rank/sort only
        # the bounded candidate set in Python below; overflow refuses consent.
        yield from db.execute(f"SELECT {fields} FROM source_evidence WHERE task_id=? LIMIT ?", (*terms, owner["id"], remaining + 1))
    else:
        for start in range(0, len(ids), 100):
            batch = ids[start:start + 100]
            yield from db.execute(f"SELECT {fields} FROM source_evidence WHERE evidence_id IN ({','.join('?' for _ in batch)}) ORDER BY evidence_id", (*terms, *batch))


def capture(course_id, revision, question, mode):
    with courses.course_read_lock():
        course = courses.get_course(course_id)
        if course["revision"] != revision:
            raise ValueError("course_changed_reload_required")
        resolved = courses._evidence_sources(course, read_only=True)
        episodes = {item["position"]: item for item in course_episodes(course, read_only=True)}
        observed, members, selected, canonical = {}, [], {}, {}
        terms = list(dict.fromkeys(_tokens(question)))[:16] or [question.strip().casefold()]
        scan = {"rows": 0, "row_limit": MAX_SCAN_ROWS, "complete": True}
        path = courses.DATA_DIR / "library.sqlite3"
        if not path.exists():
            return {"scope": {"kind": "course", "id": course_id, "title": course["title"], "revision": revision},
                    "evidence": [], "members": [{"position": i, "title": s["title"], "status": "unindexed", "eligible": 0, "excluded": 0, "missing": 0} for i, s in enumerate(course["sources"])],
                    "eligible_anchors": 0, "eligible_characters": 0, "oversized_anchors": 0, "scan": scan, "fingerprint": digest(course)}
        catalog_stat = path.stat()
        catalog_identity = (catalog_stat.st_dev, catalog_stat.st_ino)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            data_version = db.execute("PRAGMA data_version").fetchone()[0]
            db.execute("BEGIN")
            for position, source in enumerate(resolved):
                if scan["complete"]:
                    owner, status, owner_revision, ids = _owner(source, db, observed)
                else:
                    owner, status, owner_revision, ids = None, "not_scanned", None, []
                if status == "scan_incomplete":
                    scan["complete"] = False
                member = {"position": position, "title": source["title"], "status": status,
                          "eligible": 0, "excluded": 0, "missing": 0, "owner": owner, "owner_revision": owner_revision}
                if status in {"scan_incomplete", "not_scanned"}:
                    member.update(eligible=None, excluded=None, missing=None)
                members.append(member)
                if not owner:
                    continue
                episode_ids = []
                if owner["kind"] == "task":
                    # A registered material alone is not a course episode. Only
                    # use real episode identities already returned for this owner.
                    episode_ids = sorted({episode["episode_id"] for episode in episodes.values()
                                          if episode.get("task_id") == owner["id"] or any(child["task_id"] == owner["id"] for child in episode.get("upgrades", []))})
                member_found = set()
                for row in _rows(db, owner, ids, MAX_SCAN_ROWS - scan["rows"], terms if mode == "question" else []):
                    if scan["rows"] >= MAX_SCAN_ROWS:
                        scan["complete"] = False
                        break
                    scan["rows"] += 1
                    item = dict(row)
                    key = item["evidence_id"]
                    member_found.add(key)
                    metadata = _json_value(item["metadata_json"], MAX_METADATA_CHARACTERS)
                    item["metadata"] = metadata
                    bounds = time_bounds(item) if isinstance(metadata, dict) and owner["kind"] == "task" and _valid_time_fields(metadata) else None
                    if (item["text_has_nul"] or item["metadata_has_nul"] or not isinstance(metadata, dict) or not is_canonical_evidence(item)
                            or metadata.get("kind", "") not in {"", "transcript", "subtitle", "frame", "visual", "ocr", "material"}
                            or not _belongs(item, owner)
                            or owner["kind"] == "task" and bounds is None or not item["bounded_text"].strip()):
                        member["excluded"] += 1
                        continue
                    member["eligible"] += 1
                    canonical[key] = item["text_length"]
                    # Alias memberships are merged, never counted as another anchor.
                    if key in selected:
                        selected[key]["episode_ids"] = sorted(set(selected[key]["episode_ids"] + episode_ids))
                        selected[key]["member_positions"].append(position)
                        continue
                    text = item["bounded_text"]
                    rank = item["lexical_rank"]
                    if mode == "question" and not rank:
                        continue
                    citation = {"evidence_id": key, "source_kind": owner["kind"], "source_id": owner["id"],
                                "title": source["title"], "locator": item["locator"], "episode_ids": episode_ids,
                                "member_positions": [position], "text": text, "characters": item["text_length"],
                                "source_fingerprint": digest({"row": item, "owner": owner, "revision": owner_revision}), "rank": rank}
                    if bounds:
                        citation.update(start=bounds[0], end=bounds[1])
                    selected[key] = citation
                    if len(selected) > MAX_ANCHORS:
                        loser = sorted(selected, key=lambda value: (-selected[value]["rank"] if mode == "question" else 0, value))[-1]
                        selected.pop(loser)
                member["missing"] = len(set(ids) - member_found)
                if not scan["complete"]:
                    member.update(status="scan_incomplete", eligible=None, excluded=None, missing=None)
                elif not member["eligible"]:
                    member["status"] = "unindexed" if not member["excluded"] else "excluded"
            db.rollback()
            try:
                stable = all(_task_revision(courses.get_task(key)) == value for key, value in observed.items())
            except FileNotFoundError:
                stable = False
            if not stable or courses.get_course(course_id) != course or courses._evidence_sources(course, read_only=True) != resolved:
                raise ValueError("course_changed_reload_required")
            evidence = sorted(selected.values(), key=lambda item: (-item["rank"] if mode == "question" else 0, item["evidence_id"]))
            for index, item in enumerate(evidence, 1):
                item["source_alias"] = f"E{index}"
                item.pop("rank")
            value = {"scope": {"kind": "course", "id": course_id, "title": course["title"], "revision": revision},
                     "evidence": evidence, "members": members, "eligible_anchors": len(canonical) if scan["complete"] else None,
                     "eligible_characters": sum(canonical.values()) if scan["complete"] else None,
                     "oversized_anchors": sum(length > MAX_SOURCE_CHARACTERS for length in canonical.values()), "scan": scan}
            value["fingerprint"] = digest({"course": course, **value})
            final_stat = path.stat()
            if db.execute("PRAGMA data_version").fetchone()[0] != data_version or (final_stat.st_dev, final_stat.st_ino) != catalog_identity:
                raise ValueError("course_changed_reload_required")
            return value
