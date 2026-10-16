"""Bounded, local relation candidates with verbatim evidence, never model facts.

Normalization is spelling-only. A repeated assertion proves only that sources
contain that assertion; a negation difference is a review candidate, not a
verified contradiction. Unsupported grammar is intentionally left unclassified.
"""
from __future__ import annotations

from collections import defaultdict
import re
import unicodedata

from .concept_identity import assignments, identity_key
from .course_comparison import is_canonical_evidence, normalize_filters, time_bounds
from .graph_snapshot import digest

MAX_ROWS = 10_000
MAX_TEXT = 24_000
MAX_CHARACTERS = 2_000_000
MAX_RELATIONS = 10_000
WARNING = "原文陈述仅证明出处含有这些文字，不证明内容真实。否定差异是待核对推断，不等于已证实冲突；不同来源也不保证作者独立。词形归一不证明同义。"
# Match an entire simple sentence, not a substring inside a conditional,
# attribution, question, quotation, conjunction or hedged claim.
MARKERS = (
    ("is part of", "is not part of", "is part of"),
    ("is", "is not", "is"), ("are", "are not", "are"),
    ("causes", "does not cause", "causes"),
    ("requires", "does not require", "requires"),
    ("contains", "does not contain", "contains"),
    ("属于", "不属于", "属于"), ("包含", "不包含", "包含"),
    ("需要", "不需要", "需要"), ("导致", "不导致", "导致"), ("是", "不是", "是"),
)
QUALIFIERS = re.compile(r"\b(?:if|when|unless|except|under|with|without|because|since|while|during|after|before|according|says?|said|states?|believes?|claims?|may|might|can|could|should|would|sometimes|usually|often|possibly|probably|not|never|no|nor|neither|and|or|but|only|always|all|every)\b|如果|若|当|除非|除了|因为|因此|据|认为|表示|说|可能|也许|通常|有时|未必|并非|不|无|没有|和|或者|但是|仅|只|总是", re.I)
# A punctuation boundary is retained in the quote; decimals and abbreviations
# are never shortened into a supported simple sentence.
SENTENCES = re.compile(r"[^\n。！？.!?]+(?:[。！？.!?]+|$)")


def normalize_label(value: str) -> str:
    """NFC, whitespace and case only; no stemming, aliases or translation."""
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _entity(value: str) -> bool:
    return (normalize_label(value) not in {"it", "this", "that", "these", "those", "they", "them", "he", "she", "we", "you", "us", "它", "这个", "那个", "这些", "那些"} and 2 <= len(value) <= 100 and len(value.split()) <= 12 and not QUALIFIERS.search(value)
            and all(char.isalnum() or unicodedata.category(char).startswith("M") or char in " -" for char in value)
            and any(char.isalpha() for char in value))


def assertions(text: str):
    """Yield narrow syntactic parses and exact Python-codepoint quote offsets."""
    for match in SENTENCES.finditer(text):
        raw = match.group()
        quote = raw.strip()
        left = match.start() + len(raw) - len(raw.lstrip())
        # Fragments adjacent to punctuation or a conditional/attribution in the
        # same line are not freestanding assertions. Keep the full line intact.
        line_start = text.rfind("\n", 0, left) + 1
        line_end = text.find("\n", match.end())
        line = text[line_start:line_end if line_end >= 0 else len(text)].strip()
        if line != quote or quote.endswith(("?", "？", "!", "！")):
            continue
        body = (quote[:-1] if quote.endswith(("。", ".")) else quote).strip()
        for positive, negative, predicate in MARKERS:
            for marker, polarity in ((negative, "negative"), (positive, "positive")):
                english = marker[0].isascii()
                pattern = rf"(.+?)\s+{re.escape(marker)}\s+(.+)" if english else rf"(.+?){re.escape(marker)}(.+)"
                parsed = re.fullmatch(pattern, body, re.I)
                if parsed and all(_entity(part.strip()) for part in parsed.groups()):
                    subject, obj = (part.strip() for part in parsed.groups())
                    yield {"subject": subject, "predicate": predicate, "object": obj, "polarity": polarity,
                           "quote": quote, "quote_start": left, "quote_end": left + len(quote)}
                    break
            else:
                continue
            break


def _selected_identity(history: dict, item: dict, label: str):
    # Existing course split/merge decisions take precedence, including stale
    # citations. Do not apply one course's choices to the rest of the library.
    relevant = {event["request"]["term"] for event in history["events"]
                if normalize_label(event["request"]["term"]) in normalize_label(label)}
    groups = []
    for term in sorted(relevant):
        group = identity_key(item, assignments(history, term), fingerprint=item["original_fingerprint"])
        if group is None:
            return None
        groups.append((term, group))
    return groups


def build_relations(evidence: list[dict], history: dict, *, query="", source_id="", source_kind="", start=None, end=None, _legacy_source_filter=False) -> dict:
    filters = normalize_filters(source_id, source_kind, start, end)
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("invalid_comparison_query")
    if len(evidence) > MAX_ROWS or sum(len(row["text"]) for row in evidence) > MAX_CHARACTERS or any(len(row["text"]) > MAX_TEXT for row in evidence):
        raise ValueError("concept_relations_too_large")
    query_key = normalize_label(query)
    nodes, groups, seen, considered = {}, defaultdict(lambda: defaultdict(list)), set(), 0
    for item in sorted(evidence, key=lambda row: row["evidence_id"]):
        if item["evidence_id"] in seen or not is_canonical_evidence(item):
            continue
        seen.add(item["evidence_id"])
        owner = item["canonical_owner"]
        if (_legacy_source_filter and source_id and owner["id"] != source_id) or (source_kind and owner["kind"] != source_kind):
            continue
        bounds = time_bounds(item)
        if start is not None or end is not None:
            if bounds is None or start is not None and bounds[1] < start or end is not None and bounds[0] > end:
                continue
        considered += 1
        for assertion in assertions(item["text"]):
            if query_key and query_key not in normalize_label(assertion["quote"]):
                continue
            endpoints = []
            for field in ("subject", "object"):
                label = assertion[field]
                identity = _selected_identity(history, item, label)
                if identity is None:
                    break
                normalized = normalize_label(label)
                key = "concept-" + digest([normalized, identity])[:24]
                node = nodes.setdefault(key, {"id": key, "label": normalized, "spellings": set(), "evidence_ids": set(),
                                              "normalization": "NFC_whitespace_casefold_only", "meaning_verified": False, "identity_groups": identity})
                node["spellings"].add(label)
                node["evidence_ids"].add(item["evidence_id"])
                endpoints.append(key)
            if len(endpoints) != 2 or endpoints[0] == endpoints[1]:
                continue
            citation = {"evidence_id": item["evidence_id"], "title": item["title"], "locator": item["locator"],
                        "source": owner, "source_identity": item["source_identity"], "source_type": item["source_type"],
                        "source_uri": item["source_uri"], "anchors": item["metadata"],
                        "standalone": item["text"].strip() == assertion["quote"],
                        **{key: assertion[key] for key in ("quote", "quote_start", "quote_end", "polarity")}}
            groups[(endpoints[0], assertion["predicate"], endpoints[1])][assertion["polarity"]].append(citation)
    edges = []
    def append(key, kind, relation, citations):
        # A selected source chooses incident relations, never removes their
        # counterpart evidence. Prefer its citation when a known alias repeats it.
        if source_id and not _legacy_source_filter:
            citations = sorted(citations, key=lambda row: row["source"]["id"] != source_id)
        # One canonical source contributes at most one vote, even with many
        # segments, repeated evidence or separately registered copies.
        unique, owners = {}, set()
        for citation in citations:
            owner = (citation["source"]["kind"], citation["source"]["id"])
            if owner in owners:
                continue
            owners.add(owner)
            unique.setdefault(citation["source_identity"], citation)
        citations = list(unique.values())
        if len(citations) < 2 or (source_id and not any(row["source"]["id"] == source_id for row in citations)):
            return
        if len(edges) >= MAX_RELATIONS:
            raise ValueError("concept_relations_too_large")
        edges.append({"id": "relation-" + digest([key, relation, citations])[:24], "from": key[0], "to": key[2],
                      "predicate": key[1], "kind": kind, "relation": relation, "truth_verified": False,
                      "evidence_ids": [row["evidence_id"] for row in citations], "citations": citations})
    for key, polarities in sorted(groups.items()):
        for polarity, citations in sorted(polarities.items()):
            # Do not equate paraphrases. Only the same entire quoted sentence,
            # after disclosed spelling normalization, is a source-occurrence fact.
            quotes = defaultdict(list)
            for citation in citations:
                if citation["standalone"]:
                    quotes[normalize_label(citation["quote"])].append(citation)
            for same in quotes.values():
                append(key, "source_assertion", "same_quoted_assertion", same)
        positives, negatives = polarities.get("positive", []), polarities.get("negative", [])
        # Choose two truly different canonical sources, not two statements from
        # one video. Do not compare a document against its registered alias.
        positive_sources = {row["source_identity"]: row for row in positives if row["standalone"]}
        negative_sources = {row["source_identity"]: row for row in negatives if row["standalone"]}
        pair = None
        if source_id and not _legacy_source_filter:
            # The default two-source pair might omit the selected third source.
            # Keep its exact assertion and one distinct opposing source instead.
            for selected, opposite in ((positives, negative_sources), (negatives, positive_sources)):
                chosen = next((row for row in selected if row["standalone"] and row["source"]["id"] == source_id), None)
                if chosen:
                    other = next((row for row in opposite.values() if row["source_identity"] != chosen["source_identity"] and row["source"] != chosen["source"]), None)
                    if other:
                        pair = [chosen, other] if chosen["polarity"] == "positive" else [other, chosen]
                        break
        elif positive_sources and negative_sources:
            a, b = next(iter(positive_sources.values())), next(iter(negative_sources.values()))
            if a["source_identity"] == b["source_identity"]:
                a = next((row for key, row in positive_sources.items() if key != b["source_identity"]), a)
                b = next((row for key, row in negative_sources.items() if key != a["source_identity"]), b)
            if a["source_identity"] != b["source_identity"]:
                pair = [a, b]
        if pair:
            append(key, "inferred", "possible_negation_difference", pair)
    used = {key for edge in edges for key in (edge["from"], edge["to"])}
    normalized_nodes = [{**nodes[key], "spellings": sorted(nodes[key]["spellings"]), "evidence_ids": sorted(nodes[key]["evidence_ids"])} for key in sorted(used)]
    return {"mode": "local_cited_relations", "query": query, "filters": filters, "nodes": normalized_nodes, "edges": edges,
            "counts": {"scanned_evidence": len(evidence), "filtered_evidence": considered, "nodes": len(normalized_nodes), "edges": len(edges)},
            "coverage": "supported_simple_sentences_only", "inference": any(edge["kind"] == "inferred" for edge in edges),
            "normalization": "NFC_whitespace_casefold_only", "warning": WARNING}
