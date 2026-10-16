"""Offline evaluation of recorded chapter-review judgments, never a model caller.

Export a gold-free request packet, then score separately authorized recorded
responses. Missing/invalid judgments remain unassessed; exact attribution and
semantic agreement are reported separately. No API keys are read or accepted.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "backend/tests/fixtures/claim_semantic_independent_20261016.json"
sys.path.insert(0, str(ROOT / "backend"))

from app.claims import build_claim_evidence_map  # noqa: E402
from app.models import TranscriptResult  # noqa: E402
from app.section_review_model import Review, messages, parse_response, MAX_OUTPUT_TOKENS  # noqa: E402
from app.course_synthesis_model import _unique_object  # noqa: E402

LABELS = ("supported", "contradicted", "insufficient")
PREDICTIONS = (*LABELS, "unassessed")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("benchmark_file_too_large")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json_number")))


def load_corpus(path=CORPUS):
    corpus = read_json(path)
    if (not isinstance(corpus, dict) or corpus.get("schema_version") != 1
            or not isinstance(corpus.get("corpus_id"), str) or not corpus["corpus_id"]
            or not corpus.get("provenance") or not isinstance(corpus.get("cases"), list)
            or not 1 <= len(corpus["cases"]) <= 500):
        raise ValueError("invalid_semantic_corpus")
    seen = set()
    for case in corpus["cases"]:
        if (not isinstance(case, dict) or not isinstance(case.get("case_id"), str)
                or not case["case_id"] or case["case_id"] in seen
                or case.get("language") not in {"en", "zh"} or case.get("gold") not in LABELS
                or not isinstance(case.get("claim"), str) or not 1 <= len(case["claim"]) <= 6000
                or not isinstance(case.get("rationale"), str) or not case["rationale"]
                or not isinstance(case.get("risk_tags"), list) or not case["risk_tags"]
                or any(not isinstance(tag, str) or not tag for tag in case["risk_tags"])
                or not isinstance(case.get("evidence"), list) or not 1 <= len(case["evidence"]) <= 24):
            raise ValueError("invalid_semantic_case")
        seen.add(case["case_id"])
        for index, item in enumerate(case["evidence"]):
            if (not isinstance(item, dict) or item.get("source_alias") != f"E{index + 1}"
                    or not isinstance(item.get("text"), str) or not item["text"].strip()
                    or not isinstance(item.get("locator"), str) or not item["locator"].strip()):
                raise ValueError("invalid_semantic_evidence")
        if sum(len(item["text"]) for item in case["evidence"]) > 12000:
            raise ValueError("semantic_source_budget_exceeded")
        required = case.get("required_support_aliases")
        if (not isinstance(required, list) or any(not isinstance(alias, str) for alias in required)
                or len(required) != len(set(required))
                or not set(required) <= {item["source_alias"] for item in case["evidence"]}
                or (case["gold"] != "insufficient" and not required)):
            raise ValueError("invalid_semantic_attribution_gold")
    return corpus


def inputs_for(case):
    return {"claims": [{"claim_alias": "C1", "text": case["claim"]}],
            "evidence": [{key: item[key] for key in ("source_alias", "text", "locator")} for item in case["evidence"]],
            "coverage": {"source_scope": "selected_fixture_text_not_full_course", "source_truncated": False}}


def request_for(case):
    return {"messages": messages(inputs_for(case)), "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "section_review", "strict": True, "schema": Review.model_json_schema()}}}


def export_requests(corpus):
    return {"schema_version": 1, "corpus_id": corpus["corpus_id"], "corpus_sha256": digest(corpus),
            "scope": "Gold-free inputs only; exporting does not authorize or perform model calls.",
            "requests": [{"case_id": case["case_id"], "input_sha256": digest(request_for(case)),
                          "request": request_for(case)} for case in corpus["cases"]]}


def read_recordings(path, corpus):
    value = read_json(path)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "corpus_sha256", "run", "results"}
            or value["schema_version"] != 1 or value["corpus_sha256"] != digest(corpus)
            or not isinstance(value["run"], dict)
            or set(value["run"]) != {"kind", "model", "recorded_at"}
            or value["run"].get("kind") not in {"recorded_model", "synthetic_protocol_test"}
            or any(not isinstance(value["run"].get(key), str) or not value["run"][key].strip()
                   for key in ("model", "recorded_at"))
            or not isinstance(value["results"], list)):
        raise ValueError("invalid_semantic_recordings")
    expected = {case["case_id"]: digest(request_for(case)) for case in corpus["cases"]}
    seen = set()
    for row in value["results"]:
        if (not isinstance(row, dict) or set(row) != {"case_id", "input_sha256", "response"}
                or not isinstance(row["case_id"], str) or row["case_id"] not in expected
                or row["case_id"] in seen or row["input_sha256"] != expected[row["case_id"]]):
            raise ValueError("semantic_recording_identity_mismatch")
        seen.add(row["case_id"])
    return value


def parse_recording(value, case):
    # Reuse the production attribution/schema validator, including refusals,
    # truncation, missing/duplicate claims and exact quotation requirements.
    if not isinstance(value, dict) or not isinstance(value.get("choices"), list):
        raise ValueError("invalid_recorded_response")
    choices = []
    for item in value["choices"]:
        if not isinstance(item, dict) or not isinstance(item.get("message"), dict):
            raise ValueError("invalid_recorded_response")
        choices.append(SimpleNamespace(finish_reason=item.get("finish_reason"),
                                       message=SimpleNamespace(**item["message"])))
    return parse_response(SimpleNamespace(choices=choices), inputs_for(case), "")["judgments"][0]


def ratio(top, bottom):
    return top / bottom if bottom else None


def summarize(rows):
    matrix = {gold: {label: 0 for label in PREDICTIONS} for gold in LABELS}
    for row in rows:
        matrix[row["gold"]][row["predicted"]] += 1
    def binary(gold_labels, predicted_labels):
        tp = sum(row["gold"] in gold_labels and row["predicted"] in predicted_labels for row in rows)
        fp = sum(row["gold"] not in gold_labels and row["predicted"] in predicted_labels for row in rows)
        fn = sum(row["gold"] in gold_labels and row["predicted"] not in predicted_labels for row in rows)
        return {"precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
                "true_positive": tp, "false_positive": fp, "false_negative": fn}
    return {"case_count": len(rows), "assessed_count": sum(row["predicted"] != "unassessed" for row in rows),
            "confusion_matrix": matrix,
            "supported": binary({"supported"}, {"supported"}),
            "unsupported": binary({"contradicted", "insufficient"}, {"contradicted", "insufficient"}),
            "contradicted": binary({"contradicted"}, {"contradicted"}),
            "insufficient": binary({"insufficient"}, {"insufficient"}),
            "required_attribution": {"eligible_count": sum(row["gold"] != "insufficient" for row in rows),
                "complete_count": sum(row["attribution_complete"] is True for row in rows)}}


def evaluate(corpus, recordings=None, *, literal_baseline=False):
    if recordings is not None and literal_baseline:
        raise ValueError("choose_one_evaluation_method")
    recorded = {row["case_id"]: row for row in recordings["results"]} if recordings else {}
    rows = []
    for case in corpus["cases"]:
        predicted, outcome, cited = "unassessed", "missing_response", set()
        if literal_baseline:
            mapped = build_claim_evidence_map("semantic-benchmark", "", case["claim"], TranscriptResult(),
                document_evidence=[{"evidence_id": item["source_alias"], "text": item["text"],
                                    "locator": item["locator"]} for item in case["evidence"]])
            claims = mapped["claims"]
            if claims and all(item["verification"] == "direct" for item in claims):
                predicted = "supported"
                cited = {alias for item in claims for alias in item["evidence_ids"]}
            outcome = "literal_match" if predicted == "supported" else "literal_abstention"
        elif case["case_id"] in recorded:
            try:
                judgment = parse_recording(recorded[case["case_id"]]["response"], case)
                predicted, outcome = judgment["verdict"], "accepted_protocol"
                cited = {item["source_alias"] for item in judgment["citations"]}
            except (ValueError, TypeError, AttributeError, KeyError):
                outcome = "rejected_protocol"
        rows.append({"case_id": case["case_id"], "language": case["language"], "risk_tags": case["risk_tags"],
                     "gold": case["gold"], "predicted": predicted, "outcome": outcome,
                     "attribution_complete": set(case["required_support_aliases"]) <= cited
                        if case["gold"] != "insufficient" else None})
    kind = "literal_baseline" if literal_baseline else recordings["run"]["kind"] if recordings else "not_run"
    return {"schema_version": 1, "corpus_id": corpus["corpus_id"], "corpus_sha256": digest(corpus),
            "evaluation_kind": kind, "run_metadata_self_reported": recordings["run"] if recordings else None,
            "status": "not_run" if kind == "not_run" else "measured_fixture_only",
            "network_attempted": False, "model_calls_performed": 0, "general_semantic_quality_verified": False,
            "interpretation": "Literal matches and valid quotations are not semantic proof. Synthetic protocol results are not model-quality evidence. Missing or rejected responses are unassessed, not unsupported predictions. Precision is null when nothing is predicted; recall includes unassessed cases. Recorded model provenance is supplied by the caller, not independently verified. Fictional visual-description text does not test pixels.",
            "overall": summarize(rows), "outcomes": dict(Counter(row["outcome"] for row in rows)),
            "by_language": {language: summarize([row for row in rows if row["language"] == language])
                            for language in sorted({row["language"] for row in rows})},
            "by_risk_tag": {tag: summarize([row for row in rows if tag in row["risk_tags"]])
                            for tag in sorted({tag for row in rows for tag in row["risk_tags"]})},
            "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--export-requests", type=Path)
    method = parser.add_mutually_exclusive_group()
    method.add_argument("--recordings", type=Path)
    method.add_argument("--literal-baseline", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    corpus = load_corpus(args.corpus)
    if args.export_requests:
        args.export_requests.parent.mkdir(parents=True, exist_ok=True)
        args.export_requests.write_text(json.dumps(export_requests(corpus), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    recordings = read_recordings(args.recordings, corpus) if args.recordings else None
    result = evaluate(corpus, recordings, literal_baseline=args.literal_baseline)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"results", "by_risk_tag", "by_language"}}, ensure_ascii=False, indent=2))
    # An unrun evaluation cannot silently pass a CI acceptance gate. A completed
    # report is still not an acceptance verdict; consumers must inspect metrics.
    return 2 if result["status"] == "not_run" else 0


if __name__ == "__main__":
    raise SystemExit(main())
