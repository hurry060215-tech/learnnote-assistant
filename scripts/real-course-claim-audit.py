from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.claims import build_claim_evidence_map  # noqa: E402
from app.transcriber import transcript_from_subtitle  # noqa: E402


LABELS = ("direct", "located_only", "inference", "pending_review")
REVIEW = {"located_only", "inference", "pending_review"}
DEFAULT_CLAIMS = ROOT / "backend" / "tests" / "fixtures" / "claim_evidence_stanford_cs224n_lecture1_20260924.json"


def _timecode(seconds: float) -> str:
    value = max(0, int(seconds))
    return f"{value // 60:02d}:{value % 60:02d}"


def audit(captions: Path, claims_path: Path) -> dict[str, object]:
    package = json.loads(claims_path.read_text(encoding="utf-8"))
    if package.get("schema_version") != 1 or tuple(package.get("label_order") or ()) != LABELS:
        raise ValueError("unsupported_real_course_claim_fixture")
    source = package["source"]
    if not str(source.get("video_url") or "").startswith("https://"):
        raise ValueError("real_course_source_url_required")
    transcript = transcript_from_subtitle(captions, source="public-course-captions")
    if not transcript.segments:
        raise ValueError("captions_contain_no_timed_segments")

    matrix = {gold: {predicted: 0 for predicted in LABELS} for gold in LABELS}
    rows = []
    for item in package["cases"]:
        gold = str(item["gold"])
        start, end = float(item["start_seconds"]), float(item["end_seconds"])
        if gold not in LABELS or start < 0 or end < start or not str(item.get("text") or "").strip():
            raise ValueError(f"invalid_real_course_claim:{item.get('id', 'missing')}")
        note = f"[{_timecode(start)}-{_timecode(end)}] {item['text'].strip()}"
        projection = build_claim_evidence_map(
            f"public-course-{item['id']}",
            str(source.get("title") or "Public course lecture"),
            note,
            transcript,
        )
        projected = projection.get("claims") or []
        if len(projected) != 1:
            raise ValueError(f"claim_projection_count:{item['id']}:{len(projected)}")
        claim = projected[0]
        predicted = str(claim.get("verification") or "pending_review")
        if predicted not in LABELS:
            raise ValueError(f"unknown_claim_status:{item['id']}:{predicted}")
        matrix[gold][predicted] += 1
        evidence = {entry["evidence_id"]: entry for entry in projection.get("evidence") or []}
        ids = claim.get("evidence_ids") or claim.get("candidate_evidence_ids") or []
        locators = [str(evidence[value].get("locator") or "") for value in ids[:3] if value in evidence]
        rows.append({
            "case_id": item["id"],
            "start_seconds": start,
            "end_seconds": end,
            "video_timestamp_url": str(source["video_url"]) + "&" + urlencode({"t": f"{int(start)}s"}),
            "gold": gold,
            "predicted": predicted,
            "review_required": bool(claim.get("review_required")) or predicted in REVIEW,
            "evidence_match_count": len(claim.get("evidence_ids") or []),
            "candidate_match_count": len(claim.get("candidate_evidence_ids") or []),
            "candidate_locators": locators,
            "risk_tags": item.get("risk_tags") or [],
        })

    direct_tp = sum(1 for item in rows if item["gold"] == "direct" and item["predicted"] == "direct")
    direct_fp = sum(1 for item in rows if item["gold"] != "direct" and item["predicted"] == "direct")
    direct_gold = sum(1 for item in rows if item["gold"] == "direct")
    review_tp = sum(1 for item in rows if item["gold"] in REVIEW and item["review_required"])
    review_fp = sum(1 for item in rows if item["gold"] not in REVIEW and item["review_required"])
    review_gold = sum(1 for item in rows if item["gold"] in REVIEW)
    return {
        "schema_version": 1,
        "audit_type": "single-public-course-video-manual-claim-audit",
        "corpus_id": package["corpus_id"],
        "source": source,
        "captions_file": captions.name,
        "captions_sha256": __import__("hashlib").sha256(captions.read_bytes()).hexdigest(),
        "caption_segment_count": len(transcript.segments),
        "case_count": len(rows),
        "human_labels": dict(Counter(str(item["gold"]) for item in rows)),
        "confusion_matrix": matrix,
        "direct_support_precision": direct_tp / (direct_tp + direct_fp) if direct_tp + direct_fp else None,
        "direct_support_recall": direct_tp / max(1, direct_gold),
        "review_gate_precision": review_tp / max(1, review_tp + review_fp),
        "review_gate_recall": review_tp / max(1, review_gold),
        "interpretation": "One manually reviewed lecture and platform auto-captions; metrics describe only these fixed claims and do not measure general semantic accuracy or caption correctness.",
        "network_attempted": False,
        "transcript_text_saved": False,
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit manually labeled claims against a local public-course VTT/SRT transcript.")
    parser.add_argument("--captions", type=Path, required=True)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.captions, args.claims)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
