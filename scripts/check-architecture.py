from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
BOUNDARY_MODULES = {"library", "knowledge", "study", "integrations", "observability"}
ROUTER_MODULES = {"knowledge_study", "library", "system"}
FORBIDDEN_FROM_BOUNDARY = {"main", "processor", "downloader"}


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


def main() -> int:
    violations = boundary_violations() + router_violations()
    if violations:
        print("Architecture boundary violations:")
        print("\n".join(violations))
        return 1
    print(f"Architecture boundaries pass: {len(BOUNDARY_MODULES)} projection modules and {len(ROUTER_MODULES)} routers checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
