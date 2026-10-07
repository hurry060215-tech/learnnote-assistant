from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "backend" / "tests" / "fixtures" / "claim_evidence_public_gold_20260924.json"
sys.path.insert(0, str(ROOT / "backend"))

from app.claims import build_claim_evidence_map  # noqa: E402
from app.models import TranscriptResult  # noqa: E402


LABELS = ("direct", "located_only", "inference", "pending_review")
REVIEW_LABELS = {"located_only", "inference", "pending_review"}


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def evaluate() -> dict[str, object]:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1:
        raise ValueError("unsupported_public_claim_corpus_schema")
    if tuple(corpus.get("label_order") or ()) != LABELS:
        raise ValueError("public_claim_corpus_label_order_mismatch")
    matrix = {gold: {predicted: 0 for predicted in LABELS} for gold in LABELS}
    language_counts: Counter[str] = Counter()
    source_ids: set[str] = set()
    results: list[dict[str, object]] = []
    seen_case_ids: set[str] = set()
    direct_tp = direct_fp = direct_fn = 0
    review_tp = review_fp = review_fn = 0
    pending_tp = pending_fp = pending_fn = 0

    for source in corpus.get("sources") or []:
        source_id = str(source.get("id") or "")
        source_url = str(source.get("url") or "")
        evidence_text = str(source.get("evidence") or "").strip()
        language = str(source.get("language") or "")
        if not source_id or not source_url.startswith("https://") or not evidence_text:
            raise ValueError(f"invalid_public_source:{source_id or 'missing'}")
        source_ids.add(source_id)
        document = {
            "evidence_id": f"public-{source_id}",
            "source_type": "public-document",
            "source_uri": source_url,
            "locator": str(source.get("locator") or "document section"),
            "text": evidence_text,
            "metadata": {"public_corpus_id": corpus.get("corpus_id"), "source_id": source_id},
        }
        for variant in source.get("claims") or []:
            case_id = str(variant.get("id") or "")
            note = str(variant.get("text") or "").strip()
            gold = str(variant.get("gold") or "")
            if not case_id or case_id in seen_case_ids or not note or gold not in LABELS:
                raise ValueError(f"invalid_public_claim_case:{case_id or 'missing'}")
            seen_case_ids.add(case_id)
            language_counts[language] += 1
            projection = build_claim_evidence_map(
                f"public-benchmark-{source_id}",
                str(source.get("title") or source_id),
                note,
                TranscriptResult(),
                document_evidence=[document],
            )
            claims = projection.get("claims") or []
            if len(claims) != 1:
                raise ValueError(f"claim_projection_count:{case_id}:{len(claims)}")
            claim = claims[0]
            predicted = str(claim.get("verification") or "pending_review")
            if predicted not in LABELS:
                raise ValueError(f"unknown_verification_status:{case_id}:{predicted}")
            matrix[gold][predicted] += 1
            predicted_review = bool(claim.get("review_required")) or predicted in REVIEW_LABELS
            gold_review = gold in REVIEW_LABELS
            direct_tp += int(gold == "direct" and predicted == "direct")
            direct_fp += int(gold != "direct" and predicted == "direct")
            direct_fn += int(gold == "direct" and predicted != "direct")
            review_tp += int(gold_review and predicted_review)
            review_fp += int(not gold_review and predicted_review)
            review_fn += int(gold_review and not predicted_review)
            pending_tp += int(gold == "pending_review" and predicted == "pending_review")
            pending_fp += int(gold != "pending_review" and predicted == "pending_review")
            pending_fn += int(gold == "pending_review" and predicted != "pending_review")
            results.append({
                "case_id": case_id,
                "source_id": source_id,
                "language": language,
                "risk_tags": variant.get("risk_tags") or source.get("risk_tags") or [],
                "gold": gold,
                "predicted": predicted,
                "review_required": predicted_review,
                "passed_review_gate": not (gold_review and not predicted_review),
            })

    case_count = len(results)
    status_accuracy = sum(matrix[label][label] for label in LABELS) / case_count if case_count else 0.0
    review_precision = _ratio(review_tp, review_tp + review_fp)
    review_recall = _ratio(review_tp, review_tp + review_fn)
    direct_precision = _ratio(direct_tp, direct_tp + direct_fp)
    direct_recall = _ratio(direct_tp, direct_tp + direct_fn)
    pending_precision = _ratio(pending_tp, pending_tp + pending_fp)
    pending_recall = _ratio(pending_tp, pending_tp + pending_fn)
    false_direct_support = direct_fp
    passed = (
        case_count >= 50
        and {"en", "zh"}.issubset(language_counts)
        and false_direct_support == 0
        and review_recall == 1.0
    )
    return {
        "schema_version": 1,
        "corpus_id": corpus.get("corpus_id"),
        "status": "pass" if passed else "fail",
        "case_count": case_count,
        "source_count": len(source_ids),
        "language_counts": dict(sorted(language_counts.items())),
        "label_order": list(LABELS),
        "confusion_matrix": matrix,
        "fixed_corpus_status_accuracy": status_accuracy,
        "direct_support": {
            "precision": direct_precision,
            "recall": direct_recall,
            "false_direct_support_count": false_direct_support,
            "contract": "fixed-corpus matching only; not general semantic accuracy",
        },
        "review_gate": {
            "precision": review_precision,
            "recall": review_recall,
            "false_negative_count": review_fn,
            "contract": "gold non-direct claims should remain visibly reviewable",
        },
        "pending_review_class": {"precision": pending_precision, "recall": pending_recall},
        "interpretation": "See confusion_matrix and per-case results. A located_only or inference status for a supported paraphrase is a direct-support false negative, not an unsupported-fact false positive.",
        "network_attempted": False,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate claim-evidence status against a manually labeled public-source corpus.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = evaluate()
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    summary = {key: value for key, value in result.items() if key != "results"}
    summary["mismatches"] = [
        {"case_id": item["case_id"], "gold": item["gold"], "predicted": item["predicted"]}
        for item in result["results"]
        if item["gold"] != item["predicted"]
    ]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
