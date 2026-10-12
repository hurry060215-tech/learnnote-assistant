"""Deterministic keyword cooccurrence; no I/O, inference or semantic claims."""
from __future__ import annotations

import math
import re

from .concept_identity import assignments, identity_groups, identity_key

WARNING = "共同关键词不代表同义、因果或观点一致。含义分组仅是你的整理选择，请核对各自原文。"
DISPLAY_LIMITS = {"nodes": 40, "matches": 100, "edges": 100}


def is_canonical_evidence(item: dict) -> bool:
    metadata = item.get("metadata") or {}
    return not (item.get("source_type") == "community" or item.get("locator") in {"note", "generated-note"}
                or metadata.get("kind") in {"note", "community", "generated-note", "review-draft", "transcript-draft"}
                or metadata.get("review_required") or metadata.get("evidence_quality") == "review_required")


def query_terms(query: str) -> list[str]:
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("invalid_comparison_query")
    # Keep the existing lexical scope, but make its eight-term bound explicit.
    return list(dict.fromkeys(term.casefold() for term in query.split()))[:8]


def normalize_filters(source_id="", source_kind="", start=None, end=None) -> dict:
    if not isinstance(source_id, str) or (source_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source_id)) or source_kind not in {"", "task", "material"}:
        raise ValueError("invalid_comparison_filter")
    if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0) for value in (start, end)) or (start is not None and end is not None and end < start):
        raise ValueError("invalid_comparison_filter")
    return {"source_id": source_id, "source_kind": source_kind, "start": float(start) if start is not None else None, "end": float(end) if end is not None else None}


def time_bounds(item: dict) -> tuple[float, float] | None:
    metadata = item.get("metadata") or {}
    left, right = metadata.get("start"), metadata.get("end")
    if left is None or right is None:
        located = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s", str(item.get("locator") or ""))
        if not located:
            return None
        left, right = map(float, located.groups())
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (left, right)) or left < 0 or right < left:
        return None
    return float(left), float(right)


def build_comparison(evidence: list[dict], history: dict, query: str, *, source_id="", source_kind="", start=None, end=None,
                     complete=False, fingerprints=None, max_edges=20_000) -> dict:
    filters = normalize_filters(source_id, source_kind, start, end)
    terms = query_terms(query)
    chosen = {term: assignments(history, term) for term in terms}
    matches, groups, seen = [], {}, set()
    for item in evidence:
        if item["evidence_id"] in seen:
            continue
        seen.add(item["evidence_id"])
        source = item["course_source"]
        kind = "task" if item.get("task_id") else source["kind"]
        if (source_id and source["id"] != source_id) or (source_kind and kind != source_kind):
            continue
        if start is not None or end is not None:
            bounds = time_bounds(item)
            if bounds is None or (start is not None and bounds[1] < start) or (end is not None and bounds[0] > end):
                continue
        text = str(item.get("text") or "")
        hits = [term for term in terms if term in text.casefold()]
        if not hits:
            continue
        offset = min(text.casefold().find(term) for term in hits)
        key = f"{source['kind']}:{source['id']}"
        node = groups.setdefault(key, {"id": key, "title": source["title"], "evidence_ids": [], "terms": [], "term_evidence": {}})
        node["evidence_ids"].append(item["evidence_id"])
        node["terms"] = sorted(set(node["terms"] + hits))
        for term in hits:
            identity = identity_key(item, chosen[term], fingerprint=fingerprints[item["evidence_id"]] if fingerprints is not None else None)
            if identity is not None:
                node["term_evidence"].setdefault((term, identity), item["evidence_id"])
        matches.append({"evidence_id": item["evidence_id"], "title": source["title"], "locator": item["locator"],
                        "excerpt": text[max(0, offset - 80):offset + 440], "matched_terms": hits, "source": source})
    all_nodes = list(groups.values())
    nodes = all_nodes if complete else all_nodes[:DISPLAY_LIMITS["nodes"]]
    visible = {node["id"] for node in nodes}
    citations = {item["evidence_id"]: item for item in matches}
    edges, total_edges = [], 0
    for index, left in enumerate(all_nodes):
        for right in all_nodes[index + 1:]:
            for term, identity in sorted(set(left["term_evidence"]) & set(right["term_evidence"])):
                ids = [left["term_evidence"][(term, identity)], right["term_evidence"][(term, identity)]]
                if len(set(ids)) != 2:
                    continue
                total_edges += 1
                if complete and total_edges > max_edges:
                    raise ValueError("graph_snapshot_too_large")
                if complete or (left["id"] in visible and right["id"] in visible and len(edges) < DISPLAY_LIMITS["edges"]):
                    edges.append({"from": left["id"], "to": right["id"], "kind": "keyword_cooccurrence", "terms": [term],
                                  "identity_group": identity, "evidence_ids": ids, "citations": [citations[key] for key in ids]})
    for node in all_nodes:
        node.pop("term_evidence")
    shown = matches if complete else matches[:DISPLAY_LIMITS["matches"]]
    counts = {"nodes": len(all_nodes), "matches": len(matches), "edges": total_edges}
    return {"mode": "local_cited_comparison", "query": query, "terms": terms,
            "query_terms_truncated": len(set(query.casefold().split())) > len(terms),
            "matches": shown, "total_matches": len(matches), "nodes": nodes, "edges": edges, "inference": False,
            "identity_revision": len(history["events"]), "concepts": [identity_groups(history, evidence, term, fingerprints=fingerprints) for term in terms],
            "filters": filters, "counts": counts, "truncated": {"nodes": len(nodes) < counts["nodes"], "matches": len(shown) < counts["matches"], "edges": len(edges) < counts["edges"]},
            "warning": WARNING}
