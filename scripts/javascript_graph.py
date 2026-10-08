"""Static local JavaScript dependency and classic-script load-order contracts.

Node checks syntax separately. This lexer recognizes literal ESM imports,
re-exports, importScripts and explicit executeScript file lists. Computed module
addresses are rejected; runtime UI callback globals are not import edges.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit

from architecture_graph import ImportEdge, dependency_cycles

IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int


def js_tokens(source: str) -> list[Token]:
    tokens = []
    index, line = 0, 1
    expression_prefix = {"=", "(", "[", "{", ",", ":", ";", "!", "?", "return", "=>", "&&", "||"}
    while index < len(source):
        char = source[index]
        if char.isspace():
            line += char == "\n"
            index += 1
            continue
        if source.startswith("//", index) or source.startswith("/*", index):
            end = source.find("\n", index) if source.startswith("//", index) else source.find("*/", index + 2)
            end = len(source) if end < 0 else end + (0 if source.startswith("//", index) else 2)
            line += source[index:end].count("\n")
            index = end
            continue
        if char in "\"'\x60":
            start, token_line, quote = index, line, char
            index += 1
            value = []
            while index < len(source) and source[index] != quote:
                if source[index] == "\\" and index + 1 < len(source):
                    index += 1
                    value.append(source[index])
                else:
                    value.append(source[index])
                index += 1
            index = min(index + 1, len(source))
            line += source[start:index].count("\n")
            text = "".join(value)
            tokens.append(Token("template" if quote == "\x60" and "\u0024{" in text else "string", text, token_line))
            continue
        if char == "/" and (not tokens or tokens[-1].value in expression_prefix):
            start = index
            index += 1
            character_class = False
            while index < len(source):
                current = source[index]
                if current == "\\":
                    index += 2
                    continue
                if current == "[":
                    character_class = True
                elif current == "]":
                    character_class = False
                elif current == "/" and not character_class:
                    index += 1
                    while index < len(source) and source[index].isalpha():
                        index += 1
                    break
                index += 1
            line += source[start:index].count("\n")
            tokens.append(Token("regex", "", line))
            continue
        match = IDENTIFIER.match(source, index)
        if match:
            text = match.group(0)
            tokens.append(Token("identifier", text, line))
            index += len(text)
            continue
        value = source[index:index + 2] if source[index:index + 2] in {"=>", "&&", "||", "?."} else char
        tokens.append(Token("punctuation", value, line))
        index += len(value)
    return tokens


def literal_list(tokens, start, closing, label):
    values = []
    cursor = start
    while cursor < len(tokens):
        if tokens[cursor].value == closing:
            return values, None
        if tokens[cursor].kind != "string":
            return [], f"line {tokens[cursor].line}: computed {label} path is not auditable"
        values.append(tokens[cursor].value)
        cursor += 1
        if cursor < len(tokens) and tokens[cursor].value == closing:
            return values, None
        if cursor >= len(tokens) or tokens[cursor].value != ",":
            return [], f"computed {label} path is not auditable"
        cursor += 1
    return [], f"unterminated {label} list"


def local_specifiers(tokens):
    dependencies, errors, injections = [], [], []
    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        if token.value == "executeScript" and index + 2 < len(tokens) and tokens[index + 1].value == "(" and tokens[index + 2].value == "{":
            depth = 1
            cursor = index + 3
            while cursor < len(tokens) and depth:
                item = tokens[cursor]
                if depth == 1 and item.value == "files" and cursor + 2 < len(tokens) and tokens[cursor + 1].value == ":":
                    if tokens[cursor + 2].value != "[":
                        errors.append(f"line {item.line}: computed executeScript files are not auditable")
                    else:
                        names, error = literal_list(tokens, cursor + 3, "]", "executeScript")
                        if error:
                            errors.append(error)
                        else:
                            injections.append(names)
                if item.kind == "punctuation" and item.value in {"{", "}"}:
                    depth += 1 if item.value == "{" else -1
                cursor += 1
            continue
        if token.value not in {"import", "export", "importScripts"}:
            continue
        if index and tokens[index - 1].value in {".", "?."}:
            continue
        rest = tokens[index + 1:]
        if not rest or (token.value == "import" and rest[0].value == "."):
            continue
        if rest[0].value == "(" and token.value != "export":
            names, error = literal_list(rest, 1, ")", token.value)
            if error or (token.value == "import" and len(names) != 1):
                errors.append(error or f"line {token.line}: import requires one literal path")
            else:
                dependencies.extend((name, token.line, token.value) for name in names)
            continue
        if token.value == "import" and rest[0].kind == "string":
            dependencies.append((rest[0].value, token.line, "import"))
            continue
        if token.value == "export" and rest[0].value not in {"{", "*"}:
            continue
        for position, item in enumerate(rest):
            if item.value == ";" or item.line > token.line + 30:
                break
            if item.value == "from" and position + 1 < len(rest):
                specifier = rest[position + 1]
                if specifier.kind == "string":
                    dependencies.append((specifier.value, token.line, token.value))
                else:
                    errors.append(f"line {token.line}: computed module path is not auditable")
                break
    return dependencies, injections, errors


# Explicit pure classic contracts only; deferred UI globals are not eager imports.
CLASSIC_PROVIDERS = {
    "LearnNoteCaptureClassification": "extension/capture-classification.js",
    "LearnNoteCaptureRanking": "extension/capture-ranking.js",
    # Chapter-only API in PR #241 retains this filename and namespace.
    "LearnNoteStudyEvidence": "extension/content-study-evidence.js",
    "LearnNoteTaskFormat": "web/task-format.js",
    "LearnNoteTaskDisplay": "web/task-display.js",
}
PURE_ALLOWED = {
    "extension/capture-classification.js": set(),
    "extension/capture-ranking.js": {"extension/capture-classification.js"},
    "extension/content-study-evidence.js": set(),
    "web/task-format.js": set(),
    "web/task-display.js": {"web/task-format.js"},
}


class ScriptTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])


def javascript_analysis(root: Path):
    paths = sorted(
        path for surface in ("web", "extension") for pattern in ("*.js", "*.mjs")
        for path in (root / surface).rglob(pattern)
        if not {"tests", "node_modules"}.intersection(path.relative_to(root).parts)
    )
    modules = {path.relative_to(root).as_posix(): path for path in paths}
    edges, errors, imports, injections, namespaces = [], [], {}, {}, {}
    for source, path in modules.items():
        tokens = js_tokens(path.read_text(encoding="utf-8"))
        specs, raw_injections, lexer_errors = local_specifiers(tokens)
        errors.extend(f"{source}: {error}" for error in lexer_errors)
        imports[source], injections[source] = [], []
        namespaces[source] = {
            CLASSIC_PROVIDERS[token.value]
            for index, token in enumerate(tokens)
            if token.kind == "identifier" and token.value in CLASSIC_PROVIDERS
            and CLASSIC_PROVIDERS[token.value] != source and index
            and tokens[index - 1].value in {".", "?."}
        }

        def resolve(specifier):
            url = urlsplit(specifier)
            if url.scheme or url.netloc:
                errors.append(f"{source} imports non-local script {specifier}")
                return None
            target_path = root / url.path.lstrip("/") if url.path.startswith("/") else path.parent / url.path
            try:
                return target_path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                errors.append(f"{source} import escapes repository: {specifier}")
                return None

        targets = set(namespaces[source])
        for specifier, _line, kind in specs:
            target = resolve(specifier)
            if target:
                targets.add(target)
                if kind == "importScripts":
                    imports[source].append(target)
        for sequence in raw_injections:
            resolved = [target for specifier in sequence if (target := resolve(specifier))]
            injections[source].append(resolved)
            targets.update(resolved)
        for target in sorted(targets):
            if target not in modules:
                errors.append(f"{source} imports missing local script {target}")
                continue
            edges.append(ImportEdge(source, target, 0))
            if source.split("/")[0] != target.split("/")[0]:
                errors.append(f"{source} crosses web/extension boundary into {target}")
            if source in PURE_ALLOWED and target not in PURE_ALLOWED[source]:
                errors.append(f"{source} crosses pure-module boundary into {target}")
    for cycle in dependency_cycles(edges):
        errors.append("JavaScript dependency cycle: " + " <-> ".join(cycle))
    return edges, errors, imports, injections, namespaces


def javascript_violations(root: Path, capture_scripts=None) -> list[str]:
    edges, errors, imports, injections, namespaces = javascript_analysis(root)
    if capture_scripts is not None:
        required = {"extension/background.js", "extension/content.js", "extension/page_hook.js"}
        while True:
            expanded = required | {edge.target for edge in edges if edge.source in required}
            if expanded == required:
                break
            required = expanded
        declared = {f"extension/{name}" for name in capture_scripts}
        for missing in sorted(required - declared):
            if (root / missing).is_file():
                errors.append(f"Capture bundle budget omits dependency {missing}")

    def load(source, loaded, visiting):
        if source in visiting:
            return  # graph already reports the cycle
        visiting.add(source)
        for dependency in imports.get(source, []):
            load(dependency, loaded, visiting)
        for dependency in sorted(namespaces.get(source, set())):
            if dependency not in loaded:
                errors.append(f"{source} reads {dependency} before its classic script is loaded")
        loaded.add(source)
        visiting.remove(source)

    if (root / "extension/background.js").is_file():
        load("extension/background.js", set(), set())
    for sequences in injections.values():
        for sequence in sequences:
            loaded = set()  # injected content runs in another realm
            for source in sequence:
                load(source, loaded, set())
    for html in (root / "web").glob("*.html"):
        parser = ScriptTags()
        parser.feed(html.read_text(encoding="utf-8"))
        loaded = set()
        for source in parser.scripts:
            path = urlsplit(source).path
            if path.startswith("/web/"):
                load(path.lstrip("/"), loaded, set())
    return errors
