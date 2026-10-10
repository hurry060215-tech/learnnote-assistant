"""CommonMark link spans for the existing, deliberately small export renderer.

The parser supplies syntax and decoded label text, never HTML. Destinations are
still checked by document_exports against its HTTP(S)/owned-anchor policy.
Existing code/math output uses parser tokens; no library-generated HTML is used.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import backtick as commonmark_code
from markdown_it.rules_inline import image as commonmark_image
from markdown_it.rules_inline import link as commonmark_link

_MATH_RE = re.compile(r"(?<!\\)\$(?!\$)([^$\n]+)\$(?!\$)")


def _existing_math(state, silent: bool) -> bool:
    """Keep the established dollar-math subset opaque to CommonMark links."""
    match = _MATH_RE.match(state.src, state.pos, state.posMax)
    if match is None:
        return False
    if not silent:
        token = state.push("learnnote_math", "", 0)
        token.content = match.group(0)
        token.meta["export_span"] = (state.pos, match.end())
    state.pos = match.end()
    return True


@dataclass(frozen=True)
class ExportLink:
    start: int
    end: int
    label: str
    destination: str


@dataclass(frozen=True)
class ExportInline:
    kind: str
    text: str
    destination: str = ""
    bold: bool = False
    italic: bool = False


def _record_span(rule, kind):
    def record(state, silent: bool) -> bool:
        start, previous = state.pos, len(state.tokens)
        if not rule(state, silent):
            return False
        if not silent:
            token = next((item for item in state.tokens[previous:] if item.type == kind), None)
            if token is not None:
                token.meta["export_span"] = (start, state.pos)
        return True
    return record


_PARSER = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
_PARSER.disable(["autolink"])
# Retain Unicode owned anchors and pre-existing URL bytes. This changes only
# URL normalization; the parser's scheme check and the export policy still run.
_PARSER.normalizeLink = lambda value: value
_PARSER.inline.ruler.at("link", _record_span(commonmark_link, "link_open"))
_PARSER.inline.ruler.at("image", _record_span(commonmark_image, "image"))
_PARSER.inline.ruler.at("backticks", _record_span(commonmark_code, "code_inline"))
_PARSER.inline.add_terminator_char("$")
_PARSER.inline.ruler.before("text", "learnnote_math", _existing_math)


def _tokens(value: str):
    return _PARSER.parseInline(str(value or ""), {})[0].children or []


def _label_text(tokens) -> str:
    parts = []
    for token in tokens:
        if token.type in {"text", "text_special", "code_inline", "learnnote_math"}:
            parts.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif token.type == "image":
            parts.append(_label_text(token.children or []))
    return "".join(parts)


def export_protected_spans(value: str) -> list[tuple[int, int]]:
    """Keep existing links, images and code opaque to timecode insertion."""
    spans = sorted(token.meta["export_span"] for token in _tokens(value) if "export_span" in token.meta)
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def export_links(value: str) -> list[ExportLink]:
    tokens = _tokens(value)
    links = []
    for index, token in enumerate(tokens):
        if token.type != "link_open" or "export_span" not in token.meta:
            continue
        label = []
        for child_index in range(index + 1, len(tokens)):
            child = tokens[child_index]
            if child.type == "link_close":
                break
            label.append(child)
        start, end = token.meta["export_span"]
        links.append(ExportLink(start, end, _label_text(label), token.attrGet("href") or ""))
    return links


def export_inline_tokens(value: str):
    source = str(value or "")
    tokens = _tokens(source)
    index = bold = italic = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "link_open":
            children = []
            index += 1
            while index < len(tokens) and tokens[index].type != "link_close":
                children.append(tokens[index])
                index += 1
            yield ExportInline("link", _label_text(children), token.attrGet("href") or "", bool(bold), bool(italic))
        elif token.type in {"text", "text_special"}:
            yield ExportInline("text", token.content, bold=bool(bold), italic=bool(italic))
        elif token.type == "code_inline":
            yield ExportInline("code", token.content, bold=bool(bold), italic=bool(italic))
        elif token.type == "learnnote_math":
            yield ExportInline("math", token.content[1:-1], bold=bool(bold), italic=bool(italic))
        elif token.type in {"softbreak", "hardbreak"}:
            yield ExportInline("text", "\n", bold=bool(bold), italic=bool(italic))
        elif token.type == "strong_open":
            bold += 1
        elif token.type == "strong_close":
            bold -= 1
        elif token.type == "em_open":
            italic += 1
        elif token.type == "em_close":
            italic -= 1
        elif token.type == "image":
            start, end = token.meta["export_span"]
            yield ExportInline("text", source[start:end], bold=bool(bold), italic=bool(italic))
        index += 1
