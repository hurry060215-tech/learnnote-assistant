from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
BOUNDARY_MODULES = {"library", "knowledge", "study", "integrations", "observability"}
ROUTER_MODULES = {"knowledge_study", "library", "system"}
STATE_MODULES = {"downloader_policy", "processor_state"}
FORBIDDEN_FROM_BOUNDARY = {"main", "processor", "downloader"}
MODULE_SIZE_LIMITS = {
    "backend/app/main.py": 5200,
    "backend/app/downloader.py": 4200,
    "backend/app/processor.py": 1700,
    "web/app.js": 10000,
    "web/styles.css": 13500,
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
