from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
BOUNDARY_MODULES = {"library", "knowledge", "study", "integrations", "observability", "media_kinds", "summary_diagnostics", "media_candidate_ranking", "media_transport", "asr_pipeline", "local_video_task", "visual_pipeline", "page_text_pipeline", "transcript_pipeline", "note_pipeline", "task_artifacts"}
ROUTER_MODULES = {
    path.stem
    for path in (APP / "routers").glob("*.py")
    if path.stem != "__init__"
}
STATE_MODULES = {"downloader_policy", "processor_state"}
FORBIDDEN_FROM_BOUNDARY = {"main", "processor", "downloader"}
MODULE_SIZE_LIMITS = {
    "backend/app/main.py": 5200,
    "backend/app/downloader.py": 4200,
    "backend/app/processor.py": 1700,
    "web/app.js": 10000,
    "web/styles.css": 13500,
    "web/learning.js": 600,
    "web/personal-notes.js": 300,
    "web/courses.js": 500,
    "backend/app/courses.py": 400,
    "backend/app/local_ocr.py": 250,
    "backend/app/task_queue.py": 400,
    "backend/app/upload_limits.py": 250,
}


def boundary_violations() -> list[str]:
    violations: list[str] = []
    for module in sorted(BOUNDARY_MODULES):
        path = APP / f"{module}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module.rsplit(".", 1)[-1]
                if imported in FORBIDDEN_FROM_BOUNDARY:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports forbidden {imported}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.") and alias.name.split(".")[-1] in FORBIDDEN_FROM_BOUNDARY:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports forbidden {alias.name}")
    return violations


def router_violations() -> list[str]:
    violations: list[str] = []
    router_root = APP / "routers"
    for module in sorted(ROUTER_MODULES):
        path = router_root / f"{module}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module.rsplit(".", 1)[-1]
                if imported in {"main", "downloader", "processor"}:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports forbidden {imported}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.") and alias.name.split(".")[-1] in {"main", "downloader", "processor"}:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports forbidden {alias.name}")
    return violations


def state_violations() -> list[str]:
    violations: list[str] = []
    for module in sorted(STATE_MODULES):
        path = APP / f"{module}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.rsplit(".", 1)[-1] == "main":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports forbidden main")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"app.main", "backend.app.main"}:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports forbidden {alias.name}")
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
    if runtime_lines > 2250:
        violations.append(f"Runtime web CSS has {runtime_lines} lines; budget is 2250")
    if legacy_lines > 23000:
        violations.append(f"Historical web CSS has {legacy_lines} lines; budget is 23000")
    return violations


def main() -> int:
    violations = boundary_violations() + router_violations() + state_violations() + module_size_violations()
    if violations:
        print("Architecture boundary violations:")
        print("\n".join(violations))
        return 1
    print(f"Architecture boundaries pass: {len(BOUNDARY_MODULES)} projection modules, {len(ROUTER_MODULES)} routers, {len(STATE_MODULES)} state modules, and {len(MODULE_SIZE_LIMITS)} size guards checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
