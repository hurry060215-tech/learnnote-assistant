from __future__ import annotations

import re
from pathlib import Path

from architecture_graph import dependency_cycles, python_import_edges
from javascript_graph import javascript_violations


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
BOUNDARY_MODULES = {"library", "knowledge", "study", "integrations", "observability", "media_kinds", "summary_diagnostics", "media_candidate_ranking", "media_transport", "asr_pipeline", "local_video_task", "visual_pipeline", "page_text_pipeline", "transcript_pipeline", "note_pipeline", "task_artifacts", "media_url_parsing", "media_json_discovery", "media_discovery", "media_manifests", "qa_evidence", "qa_history"}
ROUTER_MODULES = {
    path.stem
    for path in (APP / "routers").glob("*.py")
    if path.stem != "__init__"
}
STATE_MODULES = {"downloader_policy", "processor_state"}
FORBIDDEN_FROM_BOUNDARY = {"main", "processor", "downloader"}
MODULE_SIZE_LIMITS = {
    "backend/app/main.py": 4800,
    "backend/app/downloader.py": 2800,
    "backend/app/processor.py": 1450,
    "web/app.js": 9650,
    "web/styles.css": 12920,
    "backend/app/media_url_parsing.py": 270,
    "backend/app/media_json_discovery.py": 440,
    "backend/app/media_discovery.py": 320,
    "backend/app/media_manifests.py": 150,
    "backend/app/qa_evidence.py": 400,
    "backend/app/qa_history.py": 130,
    "extension/page_hook.js": 2850,
    "extension/background.js": 2500,
    "extension/content.js": 2200,
    "extension/content-study-evidence.js": 110,
    "extension/capture-classification.js": 290,
    "extension/capture-ranking.js": 320,
    "web/task-format.js": 210,
    "web/task-display.js": 225,
    "web/learning.js": 600,
    "web/personal-notes.js": 300,
    "web/courses.js": 500,
    "backend/app/courses.py": 400,
    "backend/app/local_ocr.py": 250,
    "backend/app/task_queue.py": 400,
    "backend/app/upload_limits.py": 250,
}


# Existing deferred lifecycle hooks only. Never exempt a whole module or SCC.
# These are migration debt, not permission to introduce new dependency directions.
LEGACY_DEFERRED_EDGES = {
    ("app.library", "app.study"): "Remove review cards when deleting source evidence",
    ("app.storage", "app.task_queue"): "Cancel queued processing before deleting a task",
    ("app.task_queue", "app.range_learning"): "Dispatch a recovered range intent",
}
PURE_MODULE_DEPENDENCIES = {
    "media_url_parsing": set(),
    "media_manifests": set(),
    "media_json_discovery": {"models", "media_kinds", "media_candidate_ranking", "media_url_parsing"},
    "media_discovery": {"models", "media_kinds", "media_candidate_ranking", "media_json_discovery", "media_url_parsing"},
    "qa_evidence": {"models", "transcript_passages"},
    "qa_history": {"models", "qa_evidence"},
    "models": {"app"},
}


def import_violations(app_root: Path = APP) -> list[str]:
    violations = []
    edges = python_import_edges(app_root)
    checked_edges = []
    for edge in edges:
        source = edge.source.removeprefix("app.")
        target = edge.target.removeprefix("app.")
        location = f"{edge.source}:{edge.line}"
        forbidden = FORBIDDEN_FROM_BOUNDARY if source in BOUNDARY_MODULES or source.startswith("routers.") else set()
        if source in STATE_MODULES:
            forbidden = forbidden | {"main"}
        if target in forbidden:
            violations.append(f"{location} imports forbidden {edge.target}")
        if source in PURE_MODULE_DEPENDENCIES and target not in PURE_MODULE_DEPENDENCIES[source]:
            violations.append(f"{location} crosses pure-module boundary into {edge.target}")
        reason = LEGACY_DEFERRED_EDGES.get((edge.source, edge.target))
        if reason and edge.deferred:
            continue
        checked_edges.append(edge)
    for cycle in dependency_cycles(checked_edges):
        violations.append("Python dependency cycle: " + " <-> ".join(cycle))
    return violations


# Keep the complete, explicitly listed extraction group bounded alongside its entry points.
EXTRACTED_BACKEND_BUDGET = 9250
EXTRACTED_BACKEND_MODULES = (
    "main", "downloader", "media_url_parsing", "media_json_discovery",
    "media_discovery", "media_manifests", "qa_evidence", "qa_history",
)
EXTENSION_SCRIPT_BUDGET_BYTES = 335000
EXTENSION_CAPTURE_SCRIPTS = ("background.js", "content.js", "content-study-evidence.js", "page_hook.js", "capture-classification.js", "capture-ranking.js")


def aggregate_size_violations() -> list[str]:
    lines = sum(len((APP / f"{name}.py").read_text(encoding="utf-8").splitlines()) for name in EXTRACTED_BACKEND_MODULES)
    violations = []
    if lines > EXTRACTED_BACKEND_BUDGET:
        violations.append(f"Extracted backend modules have {lines} lines; combined budget is {EXTRACTED_BACKEND_BUDGET}")
    size = sum((ROOT / "extension" / name).stat().st_size for name in EXTENSION_CAPTURE_SCRIPTS)
    if size > EXTENSION_SCRIPT_BUDGET_BYTES:
        violations.append(f"Extension capture scripts have {size} bytes; bundle budget is {EXTENSION_SCRIPT_BUDGET_BYTES}")
    return violations


def module_size_violations() -> list[str]:
    violations: list[str] = []
    for relative, limit in sorted(MODULE_SIZE_LIMITS.items()):
        path = ROOT / relative
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > limit:
            violations.append(f"{relative} has {lines} lines; limit is {limit}")
    # The shipped entry point and historical regression fixtures have separate budgets.
    # Legacy CSS is excluded by the desktop spec and enforced by release-tree audit.
    entry = (ROOT / "web/index.html").read_text(encoding="utf-8")
    active_names = set(re.findall(r'href="/web/([^"?]+\.css)', entry))
    if not active_names:
        violations.append("The runtime entry point must declare its local stylesheet")
    styles = list((ROOT / "web").glob("*.css"))
    runtime_lines = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in styles if path.name in active_names)
    legacy_lines = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in styles if path.name not in active_names)
    # Claim timeline markers and responsive controls add a bounded 20-line allowance.
    if runtime_lines > 2270:
        violations.append(f"Runtime web CSS has {runtime_lines} lines; budget is 2270")
    if legacy_lines > 23000:
        violations.append(f"Historical web CSS has {legacy_lines} lines; budget is 23000")
    return violations


def main() -> int:
    violations = import_violations() + javascript_violations(ROOT, EXTENSION_CAPTURE_SCRIPTS) + module_size_violations() + aggregate_size_violations()
    if violations:
        print("Architecture boundary violations:")
        print("\n".join(violations))
        return 1
    print(f"Architecture boundaries pass: {len(BOUNDARY_MODULES)} boundary modules, {len(ROUTER_MODULES)} routers, {len(STATE_MODULES)} state modules, Python/JavaScript cycle graphs, classic load order, and {len(MODULE_SIZE_LIMITS)} size guards checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
