"""Offline verification of local relation exports; imported claims stay untrusted."""
from __future__ import annotations

import re

from .concept_identity import validate_history
from .concept_relations import MAX_ROWS, MAX_TEXT, build_relations
from .course_graph_export import _belongs
from .graph_snapshot import HASH, ID, digest, encoded, safe_locator, safe_metadata, safe_uri

MAX_BYTES = 20_000_000
FORMAT = "learnnote.cited-relations"


def verify_relation_snapshot(snapshot):
    try:
        if len(encoded(snapshot)) > MAX_BYTES:
            raise ValueError("concept_relations_too_large")
        if set(snapshot) != {"format", "schema_version", "scope", "members", "evidence", "history", "graph", "provenance", "digest"} or snapshot["format"] != FORMAT or type(snapshot["schema_version"]) is not int or snapshot["schema_version"] not in {1, 2}:
            raise ValueError
        scope = snapshot["scope"]
        if scope == {"kind": "library"}:
            history = validate_history(snapshot["history"], "0" * 32)
            if history["events"]:
                raise ValueError
        elif set(scope) == {"kind", "id", "revision", "title"} and scope["kind"] == "course" and isinstance(scope["id"], str) and re.fullmatch(r"[a-f0-9]{32}", scope["id"]) and type(scope["revision"]) is int and scope["revision"] >= 1 and isinstance(scope["title"], str) and len(scope["title"]) <= 200:
            history = validate_history(snapshot["history"], scope["id"])
        else:
            raise ValueError
        if not isinstance(snapshot["members"], list) or len(snapshot["members"]) > 1000:
            raise ValueError
        owners = set()
        for member in snapshot["members"]:
            owner = member["canonical_owner"]
            if owner is not None:
                if set(owner) != {"kind", "id"} or owner["kind"] not in {"task", "material"} or not ID.fullmatch(owner["id"]):
                    raise ValueError
                owners.add((owner["kind"], owner["id"]))
        evidence = snapshot["evidence"]
        if not isinstance(evidence, list) or len(evidence) > MAX_ROWS:
            raise ValueError("concept_relations_too_large")
        seen, owner_identities = set(), {}
        fields = {"evidence_id", "schema_version", "source_type", "title", "source_uri", "locator", "text", "task_id", "metadata", "course_source", "canonical_owner", "source_identity", "original_fingerprint", "snapshot_fingerprint", "redacted_fields"}
        for row in evidence:
            if set(row) != fields or type(row["schema_version"]) is not int or row["schema_version"] != 1 or row["source_type"] not in {"video", "task", "pdf", "markdown", "webpage"}:
                raise ValueError
            for field, limit in (("evidence_id", 128), ("task_id", 128), ("title", 500), ("locator", 300), ("source_uri", 4096), ("text", MAX_TEXT)):
                if not isinstance(row[field], str) or len(row[field]) > limit:
                    raise ValueError
            if not ID.fullmatch(row["evidence_id"]) or row["evidence_id"] in seen:
                raise ValueError
            seen.add(row["evidence_id"])
            owner = row["canonical_owner"]
            if set(owner) != {"kind", "id"}:
                raise ValueError
            owner_key = (owner["kind"], owner["id"])
            if owner_identities.setdefault(owner_key, row["source_identity"]) != row["source_identity"]:
                raise ValueError
            if owner_key not in owners or not _belongs(row, owner):
                raise ValueError
            if row["course_source"] != {"kind": owner["kind"], "id": owner["id"], "title": row["title"]}:
                raise ValueError
            if row["redacted_fields"] != sorted(set(row["redacted_fields"])) or not set(row["redacted_fields"]) <= {"metadata", "source_uri", "locator"}:
                raise ValueError
            if safe_uri(row["source_uri"]) != row["source_uri"] or safe_locator(row["locator"]) != row["locator"] or safe_metadata(row["metadata"]) != row["metadata"]:
                raise ValueError
            if any(not HASH.fullmatch(row[field]) for field in ("source_identity", "original_fingerprint", "snapshot_fingerprint")):
                raise ValueError
            if digest({key: value for key, value in row.items() if key != "snapshot_fingerprint"}) != row["snapshot_fingerprint"]:
                raise ValueError
        graph = snapshot["graph"]
        # V1 filtered evidence before constructing edges; its selected-source
        # graphs were empty. Preserve those exact exports instead of upgrading.
        rebuilt = build_relations(evidence, history, query=graph["query"], **graph["filters"], _legacy_source_filter=snapshot["schema_version"] == 1)
        if encoded(rebuilt) != encoded(graph) or digest({key: value for key, value in snapshot.items() if key != "digest"}) != snapshot["digest"]:
            raise ValueError
        return {"snapshot": snapshot, "graph": rebuilt, "read_only": True,
                "warning": "文件仅通过内部一致性校验，原文身份与内容真实性未验证；没有修改本机资料。"}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
        raise ValueError("concept_relations_too_large" if str(exc) == "concept_relations_too_large" else "concept_relation_snapshot_invalid") from exc
