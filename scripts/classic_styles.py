"""Flat, ordered legacy CSS contract. No imports or new network destinations.

Keep these sheets beside styles.css so local url() references retain their base.
The browser is the CSS parser; this check audits links, boundaries and resources.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


CLASSIC_STYLE_LIMITS = {
    "styles.css": 12262,
    "classic-workbench.css": 489,
    "classic-interactions.css": 78,
    "classic-study.css": 91,
}
CLASSIC_STYLE_BUDGET = 12920
CLASSIC_STYLE_ORDER = (*CLASSIC_STYLE_LIMITS, "workspace.css", "product.css", "mature.css", "editorial.css", "experience.css")
STRING = r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' '''.strip()
IDENT = r"(?:[\w-]|\\(?:[0-9a-fA-F]{1,6}\s?|[^\n\r]))+"
TOKENS = re.compile(rf"/\*.*?\*/|{STRING}|(?P<ident>@?{IDENT})|(?P<brace>[{{}}])", re.S)
URL_VALUE = re.compile(rf"\(\s*(?P<value>{STRING}|[^\s)'\"]*)\s*\)", re.S)


def css_unescape(value: str) -> str:
    def replace(match):
        hex_value = match.group(1)
        if hex_value:
            code = int(hex_value, 16)
            return chr(code) if 0 < code <= 0x10FFFF else "\ufffd"
        return match.group(2)
    return re.sub(r"\\(?:([0-9a-fA-F]{1,6})\s?|([^\n\r]))", replace, value)


class StylesheetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        values = dict(attrs)
        if tag == "link" and "stylesheet" in (values.get("rel") or "").lower().split():
            self.links.append((values, self.in_head))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def stylesheet_links(path: Path):
    parser = StylesheetLinks()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.links


def css_resource_violations(path: Path, root: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    errors, depth, skip_until = [], 0, 0
    for token in TOKENS.finditer(source):
        if token.start() < skip_until:
            continue
        ident = css_unescape(token.group("ident") or "").lower()
        if ident in {"@import", "@charset", "@namespace"}:
            errors.append(f"{path.name}: {ident} is forbidden in the flat classic CSS group")
        if token.group("brace"):
            depth += 1 if token.group("brace") == "{" else -1
            if depth < 0:
                errors.append(f"{path.name}: rule crosses a stylesheet boundary")
        if ident != "url":
            continue
        value = URL_VALUE.match(source, token.end())
        if not value:
            continue
        skip_until = value.end()
        address = css_unescape(value.group("value").strip('"\''))
        url = urlsplit(address)
        if url.scheme == "data" or address.startswith("#"):
            continue
        if url.scheme or url.netloc:
            errors.append(f"{path.name}: external CSS asset is forbidden: {address}")
            continue
        resource = unquote(url.path)
        target = (root / resource.lstrip("/") if resource.startswith("/") else path.parent / resource).resolve()
        if not resource or not target.is_relative_to((root / "web").resolve()) or not target.is_file():
            errors.append(f"{path.name}: missing or non-web CSS asset: {address}")
    if depth:
        errors.append(f"{path.name}: rule crosses a stylesheet boundary")
    return errors


def classic_style_violations(root: Path) -> list[str]:
    errors = []
    links = stylesheet_links(root / "web/classic.html")
    urls = [urlsplit(attrs.get("href", "")) for attrs, _ in links]
    if [url.path for url in urls] != [f"/web/{name}" for name in CLASSIC_STYLE_ORDER] or any(url.scheme or url.netloc for url in urls):
        errors.append("Classic CSS load order must be: " + ", ".join(CLASSIC_STYLE_ORDER))
    for attrs, in_head in links:
        if not in_head or attrs.get("rel") != "stylesheet" or attrs.get("media", "all") != "all" or any(key in attrs for key in ("disabled", "title", "onload")):
            errors.append("Classic CSS must remain unconditional render-blocking head links")
    versions = {url.query for url in urls[:len(CLASSIC_STYLE_LIMITS)]}
    if len(versions) != 1 or "" in versions:
        errors.append("Classic CSS group must use one nonempty cache version")
    for name in CLASSIC_STYLE_ORDER:
        if not (root / "web" / name).is_file():
            errors.append(f"Missing classic stylesheet: {name}")
    expected = set(CLASSIC_STYLE_LIMITS) - {"styles.css"}
    discovered = {path.relative_to(root / "web").as_posix() for path in (root / "web").rglob("classic-*.css")}
    if discovered != expected:
        errors.append("Classic CSS modules must be explicitly ordered and budgeted")
    total = 0
    for name, limit in CLASSIC_STYLE_LIMITS.items():
        path = root / "web" / name
        if not path.is_file():
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        total += lines
        if lines > limit:
            errors.append(f"web/{name} has {lines} lines; limit is {limit}")
        errors.extend(css_resource_violations(path, root))
    if total > CLASSIC_STYLE_BUDGET:
        errors.append(f"Classic CSS group has {total} lines; combined budget is {CLASSIC_STYLE_BUDGET}")
    if any(urlsplit(attrs.get("href", "")).path in {f"/web/{name}" for name in CLASSIC_STYLE_LIMITS} for attrs, _ in stylesheet_links(root / "web/index.html")):
        errors.append("Classic CSS must not enter the default reader")
    return errors
