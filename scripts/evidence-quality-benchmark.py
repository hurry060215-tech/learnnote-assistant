from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import FrameGrid, TranscriptResult, TranscriptSegment  # noqa: E402
from app.summarizer import note_grounding_issues  # noqa: E402


def fixture_transcript() -> TranscriptResult:
    return TranscriptResult(
        language="zh",
        source="fixture",
        segments=[TranscriptSegment(start=0, end=96, text="梯度决定方向，学习率决定步长。")],
        full_text="梯度决定方向，学习率决定步长。",
    )


def fixture_grids() -> list[FrameGrid]:
    return [FrameGrid(path="grid.jpg", start=0, end=96, frame_count=2, frame_timestamps=[0, 90], url="/grid.jpg")]


BASE_CASES = (
    {
        "id": "supported_note_passes",
        "note": "# 梯度下降\n\n- 梯度决定方向。\n- 学习率决定步长。\n\n## 自测题\n\n学习率控制什么？",
        "required": (),
    },
    {
        "id": "wrong_duration_is_blocked",
        "note": "这节微课共 6 分钟。\n\n## 核心概念\n\n梯度决定方向。",
        "required": ("duration_mismatch:",),
    },
    {
        "id": "unsupported_example_is_blocked",
        "note": "## 例题\n\n使用 Adam、Kaggle 和 NumPy 完成练习。",
        "required": ("unsupported_terms:", "unsupported_example_section"),
    },
)

CASES = BASE_CASES + tuple(
    [
        {
            "id": f"supported_chinese_{index:02d}",
            "note": f"# 课程 {index}\n\n梯度决定方向，学习率决定步长。",
            "required": (),
        }
        for index in range(25)
    ]
    + [
        {
            "id": f"unsupported_external_{index:02d}",
            "note": f"# 课程 {index}\n\n本节使用 ExternalTool{index} and QuantumLib{index}.",
            "required": ("unsupported_terms:",),
        }
        for index in range(25)
    ]
)


def run_benchmark() -> dict[str, object]:
    transcript = fixture_transcript()
    grids = fixture_grids()
    results = []
    for case in CASES:
        issues = note_grounding_issues(case["note"], transcript, grids)
        required = tuple(case["required"])
        passed = (not required and not issues) or all(any(issue.startswith(prefix) for issue in issues) for prefix in required)
        results.append({"id": case["id"], "passed": passed, "issues": issues})
    passed_count = sum(bool(item["passed"]) for item in results)
    expected_positive = sum(bool(case["required"]) for case in CASES)
    predicted_positive = sum(bool(item["issues"]) for item in results)
    true_positive = sum(bool(item["issues"]) and bool(CASES[index]["required"]) for index, item in enumerate(results))
    return {
        "status": "pass" if passed_count == len(results) else "fail",
        "mode": "offline-grounding-fixtures",
        "case_count": len(results),
        "passed_count": passed_count,
        "quality_metrics": {
            "expected_issue_cases": expected_positive,
            "predicted_issue_cases": predicted_positive,
            "true_positive_cases": true_positive,
            "precision": true_positive / predicted_positive if predicted_positive else 1.0,
            "recall": true_positive / expected_positive if expected_positive else 1.0,
        },
        "results": results,
        "network_attempted": False,
    }


if __name__ == "__main__":
    report = run_benchmark()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)
