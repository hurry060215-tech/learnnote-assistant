"""Static local import graph, including deferred imports, without importing apps."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    line: int
    deferred: bool = False


def python_import_edges(package_root: Path, package: str = "app") -> list[ImportEdge]:
    modules = {}
    for path in sorted(package_root.rglob("*.py")):
        parts = list(path.relative_to(package_root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join([package, *parts])] = path
    edges = []
    for module, path in modules.items():
        current_package = module if path.name == "__init__.py" else module.rpartition(".")[0]

        def walk(node: ast.AST, deferred: bool = False) -> None:
            deferred = deferred or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            targets = []
            if isinstance(node, ast.Import):
                targets.extend(alias.name.removeprefix("backend.") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = current_package.split(".")
                    if node.level > len(parts):
                        return
                    base = ".".join(parts[:len(parts) - node.level + 1])
                    if node.module:
                        base += "." + node.module
                else:
                    base = (node.module or "").removeprefix("backend.")
                targets.append(base)
                targets.extend(f"{base}.{alias.name}" for alias in node.names)
            for target in targets:
                if target in modules and target != module:
                    edges.append(ImportEdge(module, target, node.lineno, deferred))
            for child in ast.iter_child_nodes(node):
                walk(child, deferred)

        walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return edges


def dependency_cycles(edges: list[ImportEdge]) -> list[tuple[str, ...]]:
    """Return deterministic strongly connected components with two or more nodes."""
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge.source, set()).add(edge.target)
        graph.setdefault(edge.target, set())
    index = 0
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    stack: list[str] = []
    stacked: set[str] = set()
    cycles = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = lows[node] = index
        index += 1
        stack.append(node)
        stacked.add(node)
        for target in sorted(graph[node]):
            if target not in indexes:
                visit(target)
                lows[node] = min(lows[node], lows[target])
            elif target in stacked:
                lows[node] = min(lows[node], indexes[target])
        if lows[node] == indexes[node]:
            component = []
            while True:
                member = stack.pop()
                stacked.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                cycles.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return sorted(cycles)
