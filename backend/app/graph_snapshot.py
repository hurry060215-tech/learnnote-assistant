"""Portable, bounded comparison snapshots. Verification performs no storage I/O.

Digests prove internal consistency, not the authenticity of imported sources.
Original fingerprints preserve grouping decisions across explicit URI/metadata
redaction; exported record fingerprints independently cover the portable data.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit

from .concept_identity import assignments, evidence_fingerprint, identity_groups, validate_history
from .course_comparison import build_comparison, normalize_filters, query_terms

FORMAT = "learnnote.filtered-comparison"
MAX_BYTES = 20_000_000
MAX_EVIDENCE = 10_000
MAX_SOURCES = 200
MAX_EDGES = 20_000
MAX_GROUP_SCAN = 100_000_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991
LIMITS = {"bytes": MAX_BYTES, "evidence": MAX_EVIDENCE, "sources": MAX_SOURCES, "edges": MAX_EDGES, "grouping_scan_bytes": MAX_GROUP_SCAN}
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
ANCHORS = {"start", "end", "frame_timestamp", "page", "page_index"}
KINDS = {"transcript", "material", "frame", "visual", "subtitle", "ocr"}


def _portable_numbers(value):
    # JSON.stringify turns 12.0 into 12 and cannot preserve integers beyond
    # 2**53-1. Hash mathematical numbers consistently across the browser hop.
    if type(value) in (int, float):
        if not math.isfinite(value) or abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("graph_snapshot_invalid")
        return int(value) if value == int(value) else value
    if isinstance(value, dict):
        return {key: _portable_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_numbers(item) for item in value]
    return value


def encoded(value) -> bytes:
    return json.dumps(_portable_numbers(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def safe_uri(value: str) -> str:
    try:
        uri = urlsplit(value)
        if uri.scheme == "local" and uri.netloc in {"tasks", "materials"} and ID.fullmatch(uri.path.lstrip("/")):
            return f"local://{uri.netloc}/{uri.path.lstrip('/')}"
        if uri.scheme in {"http", "https"} and uri.hostname and not any(char.isspace() for char in uri.netloc):
            host = uri.hostname
            if ":" in host:
                host = f"[{host}]"
            if uri.port:
                host += f":{uri.port}"
            return urlunsplit((uri.scheme, host, uri.path, "", ""))
    except (ValueError, TypeError):
        pass
    return ""


def safe_locator(value: str) -> str:
    # Headings and other user-authored labels remain literal. Filesystem and
    # URL locators are not portable anchors and must never leak export paths.
    checked = value.strip()
    if re.match(r"^(?:[/\\]|[A-Za-z]:(?:[/\\]|\S*[/\\]|\S+\.[A-Za-z0-9]{1,12}$)|~[^/\\]*[/\\]|\.{1,2}[/\\]|(?:file|https?|ftp|smb|sftp|ssh|data|javascript):)", checked, re.I) or "://" in checked:
        return "unlocated (redacted)"
    return value


def safe_metadata(value: dict) -> dict:
    result = {}
    for key, item in value.items():
        if key in {"start", "end", "frame_timestamp"} and item is not None and (type(item) not in (int, float) or not math.isfinite(item) or not 0 <= item <= MAX_SAFE_INTEGER):
            # Dropping an invalid explicit time could make locator fallback
            # change the filter result. Refuse instead of inventing an anchor.
            raise ValueError("graph_snapshot_invalid")
        if key in ANCHORS and type(item) in (int, float) and math.isfinite(item) and 0 <= item <= MAX_SAFE_INTEGER:
            result[key] = item
        elif key in {"window_id", "material_id"} and isinstance(item, str) and ID.fullmatch(item):
            result[key] = item
        elif key == "source_revision" and isinstance(item, str) and HASH.fullmatch(item):
            result[key] = item
        elif key == "kind" and isinstance(item, str) and item in KINDS:
            result[key] = item
    return result


def portable_evidence(item: dict, owner: dict) -> dict:
    result = {key: item.get(key, "") for key in ("evidence_id", "source_type", "title", "source_uri", "locator", "text", "task_id")}
    result["schema_version"] = item.get("schema_version", 1)
    result["metadata"] = safe_metadata(item.get("metadata") or {})
    result["source_uri"] = safe_uri(result["source_uri"])
    result["locator"] = safe_locator(result["locator"])
    result["course_source"] = item["course_source"]
    result["canonical_owner"] = owner
    result["original_fingerprint"] = evidence_fingerprint(item)
    result["redacted_fields"] = sorted(key for key in ("metadata", "source_uri", "locator") if result[key] != item.get(key, {} if key == "metadata" else ""))
    result["snapshot_fingerprint"] = digest(result)
    return result


def grouping_state(evidence: list[dict], history: dict, terms: list[str]) -> tuple[list, list]:
    fingerprints = {row["evidence_id"]: row["original_fingerprint"] for row in evidence}
    by_id = {row["evidence_id"]: row for row in evidence}
    groups, unresolved = [], []
    for term in dict.fromkeys([*terms, *(event["request"]["term"] for event in history["events"])]):
        view = identity_groups(history, evidence, term, fingerprints=fingerprints)
        groups.append(view)
        chosen = assignments(history, term)
        for group in view["groups"]:
            for key in group["unresolved_ids"]:
                row = by_id.get(key)
                unresolved.append({"term": term, "evidence_id": key, "status": "stale" if row else "missing",
                                   "expected_fingerprint": chosen[key]["fingerprint"], "current_fingerprint": fingerprints.get(key)})
    return groups, unresolved


def assemble_snapshot(course: dict, sources: list[dict], evidence: list[dict], history: dict, query: str, filters: dict) -> dict:
    if len(evidence) > MAX_EVIDENCE or len(sources) > MAX_SOURCES:
        raise ValueError("graph_snapshot_too_large")
    terms = set(query_terms(query)) | {event["request"]["term"] for event in history["events"]}
    if sum(len(row["text"].encode("utf-8")) for row in evidence) * len(terms) > MAX_GROUP_SCAN:
        raise ValueError("graph_snapshot_too_large")
    fingerprints = {row["evidence_id"]: row["original_fingerprint"] for row in evidence}
    graph = build_comparison(evidence, history, query, **filters, complete=True, fingerprints=fingerprints, max_edges=MAX_EDGES)
    groups, unresolved = grouping_state(evidence, history, graph["terms"])
    snapshot = {"format": FORMAT, "schema_version": 1, "course": course, "sources": sources,
                "scope": {"query": query, "terms": graph["terms"], "filters": graph["filters"]},
                "evidence": evidence, "history": history, "group_state": groups, "unresolved": unresolved, "graph": graph,
                "limits": LIMITS, "completeness": "complete_within_exported_scope",
                "provenance": "Imported source claims and original fingerprints are unverified. URI userinfo/query/fragment, path-like locators and non-allowlisted metadata are omitted explicitly; titles, original text and HTTP(S) URL paths are retained and are not automatically scrubbed for secrets."}
    snapshot["digest"] = digest(snapshot)
    if len(encoded(snapshot)) > MAX_BYTES:
        raise ValueError("graph_snapshot_too_large")
    return snapshot


def _identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError


def _reference(value, *, url=False):
    expected = {"kind", "id", "title", "url"} if url else {"kind", "id", "title"}
    if not isinstance(value, dict) or set(value) != expected or value["kind"] not in ({"task", "material", "url"} if url else {"task", "material"}):
        raise ValueError
    if not isinstance(value["title"], str) or len(value["title"]) > 500:
        raise ValueError
    if value["kind"] == "url":
        if value["id"] != "":
            raise ValueError
    else:
        _identifier(value["id"])
    if url and (not isinstance(value["url"], str) or len(value["url"]) > 4096 or safe_uri(value["url"]) != value["url"]):
        raise ValueError


def _validate_sources(course, sources):
    if set(course) != {"schema_version", "id", "title", "sources", "paused", "revision"} or type(course["schema_version"]) is not int or course["schema_version"] != 1 or not re.fullmatch(r"[a-f0-9]{32}", course["id"]):
        raise ValueError
    if not isinstance(course["title"], str) or not 1 <= len(course["title"]) <= 200 or type(course["paused"]) is not bool or type(course["revision"]) is not int or course["revision"] < 1:
        raise ValueError
    if not isinstance(sources, list) or not isinstance(course["sources"], list) or len(sources) > MAX_SOURCES or len(course["sources"]) != len(sources):
        raise ValueError
    references, owners, candidates = set(), {}, set()
    for position, entry in enumerate(sources):
        if set(entry) != {"position", "reference", "resolved_source", "canonical_owner", "owner_revision", "status", "evidence_ids", "missing_evidence_ids", "excluded_evidence_ids", "reference_fingerprint", "redacted_fields"} or type(entry["position"]) is not int or entry["position"] != position:
            raise ValueError
        ref = entry["reference"]
        _reference(ref, url=True)
        if course["sources"][position] != ref or not HASH.fullmatch(entry["reference_fingerprint"]):
            raise ValueError
        reference_key = (ref["kind"], entry["reference_fingerprint"] if ref["kind"] == "url" else ref["id"])
        if reference_key in references:
            raise ValueError
        references.add(reference_key)
        if entry["redacted_fields"] not in ([], ["url"]):
            raise ValueError
        if entry["resolved_source"] is not None:
            _reference(entry["resolved_source"])
            if ref["kind"] != "url" and entry["resolved_source"] != {key: ref[key] for key in ("kind", "id", "title")}:
                raise ValueError
        owner = entry["canonical_owner"]
        if owner is not None:
            if set(owner) != {"kind", "id"} or owner["kind"] not in {"task", "material"}:
                raise ValueError
            _identifier(owner["id"])
            resolved = entry["resolved_source"]
            if resolved is None or (resolved["kind"] == "task" and owner != {"kind": "task", "id": resolved["id"]}) or (owner["kind"] == "material" and owner["id"] != resolved["id"]):
                raise ValueError
        if entry["status"] not in {"ready", "alias", "missing", "excluded", "unindexed", "unresolved_url"}:
            raise ValueError
        if owner is None:
            if entry["owner_revision"] is not None or entry["status"] not in {"missing", "excluded", "unresolved_url"}:
                raise ValueError
        else:
            if not isinstance(entry["owner_revision"], str) or not HASH.fullmatch(entry["owner_revision"]):
                raise ValueError
            expected = "alias" if entry["resolved_source"]["kind"] != owner["kind"] else "ready"
            if entry["status"] != (expected if entry["evidence_ids"] else "unindexed"):
                raise ValueError
        if entry["status"] == "unresolved_url" and (ref["kind"] != "url" or entry["resolved_source"] is not None):
            raise ValueError
        seen = set()
        for key in ("evidence_ids", "missing_evidence_ids", "excluded_evidence_ids"):
            ids = entry[key]
            if not isinstance(ids, list) or len(ids) > MAX_EVIDENCE:
                raise ValueError
            for evidence_id in ids:
                _identifier(evidence_id)
                if evidence_id in seen:
                    raise ValueError
                seen.add(evidence_id)
                candidates.add(evidence_id)
        if len(candidates) > MAX_EVIDENCE:
            raise ValueError("graph_snapshot_too_large")
        if owner is None and entry["evidence_ids"]:
            raise ValueError
        if owner is not None:
            key = (owner["kind"], owner["id"])
            state = (entry["owner_revision"], *(frozenset(entry[name]) for name in ("evidence_ids", "missing_evidence_ids", "excluded_evidence_ids")))
            if owners.setdefault(key, state) != state:
                raise ValueError


def verify_snapshot(value: dict) -> dict:
    """Validate and reconstruct using only this object, never the live catalog."""
    try:
        if len(encoded(value)) > MAX_BYTES:
            raise ValueError("graph_snapshot_too_large")
        if value["format"] != FORMAT or value["schema_version"] != 1:
            raise ValueError
        course, sources, evidence = value["course"], value["sources"], value["evidence"]
        _validate_sources(course, sources)
        history = validate_history(value["history"], course["id"])
        if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE:
            raise ValueError("graph_snapshot_too_large")
        seen = set()
        fields = {"evidence_id", "source_type", "title", "source_uri", "locator", "text", "task_id", "schema_version", "metadata", "course_source", "canonical_owner", "original_fingerprint", "redacted_fields", "snapshot_fingerprint"}
        for row in evidence:
            if set(row) != fields or type(row["schema_version"]) is not int or row["schema_version"] != 1 or row["source_type"] not in {"video", "pdf", "markdown", "webpage", "task"}:
                raise ValueError
            _identifier(row["evidence_id"])
            if row["evidence_id"] in seen:
                raise ValueError
            seen.add(row["evidence_id"])
            for key, limit in (("title", 500), ("text", 2_000_000), ("locator", 300), ("source_uri", 4096), ("task_id", 128)):
                if not isinstance(row[key], str) or len(row[key]) > limit:
                    raise ValueError
            if safe_uri(row["source_uri"]) != row["source_uri"] or safe_locator(row["locator"]) != row["locator"] or safe_metadata(row["metadata"]) != row["metadata"]:
                raise ValueError
            if not HASH.fullmatch(row["original_fingerprint"]) or row["redacted_fields"] != sorted(set(row["redacted_fields"])) or not set(row["redacted_fields"]) <= {"metadata", "source_uri", "locator"}:
                raise ValueError
            if digest({key: item for key, item in row.items() if key != "snapshot_fingerprint"}) != row["snapshot_fingerprint"]:
                raise ValueError
            _reference(row["course_source"])
            entry = next((entry for entry in sources if entry["resolved_source"] == row["course_source"] and row["evidence_id"] in entry["evidence_ids"]), None)
            if entry is None or entry["canonical_owner"] != row["canonical_owner"]:
                raise ValueError
            owner = row["canonical_owner"]
            if owner["kind"] == "task":
                if row["task_id"] != owner["id"]:
                    raise ValueError
            elif row["task_id"] or row["metadata"].get("material_id") != owner["id"] or row["source_uri"] != f"local://materials/{owner['id']}":
                raise ValueError
            if row["locator"] in {"note", "generated-note"}:
                raise ValueError
        if set().union(*(set(entry["evidence_ids"]) for entry in sources)) != seen:
            raise ValueError
        by_id = {row["evidence_id"]: row for row in evidence}
        for entry in sources:
            if any(by_id[key]["canonical_owner"] != entry["canonical_owner"] for key in entry["evidence_ids"]):
                raise ValueError
        if any(seen.intersection(entry["missing_evidence_ids"]) for entry in sources):
            raise ValueError
        scope = value["scope"]
        filters = normalize_filters(**scope["filters"])
        if scope != {"query": scope["query"], "terms": query_terms(scope["query"]), "filters": filters}:
            raise ValueError
        rebuilt = assemble_snapshot(course, sources, evidence, history, scope["query"], filters)
        if encoded(rebuilt) != encoded(value):
            raise ValueError
        return {"snapshot": value, "graph": rebuilt["graph"], "read_only": True}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
        code = "graph_snapshot_too_large" if str(exc) == "graph_snapshot_too_large" else "graph_snapshot_invalid"
        raise ValueError(code) from exc
