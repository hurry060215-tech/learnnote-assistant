"""Pure HLS/DASH detection and relative-URI rewriting; no media retrieval.

DRM flags describe the input only. Network validation and fail-closed DRM
handling remain downloader responsibilities.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

def _manifest_kind_from_body(text: str, content_type: str = "") -> tuple[str, str]:
    head = (text or "")[:8192].lstrip("\ufeff\r\n\t ")
    lower_head = head[:256].lower()
    content_type = (content_type or "").lower()
    looks_html = lower_head.startswith(("<!doctype html", "<html"))
    if head.startswith("#EXTM3U") or (not looks_html and ("mpegurl" in content_type or "x-mpegurl" in content_type)):
        return "hls", "application/vnd.apple.mpegurl"
    if re.search(r"<MPD(?:\s|>)", head, re.I) or (not looks_html and "dash+xml" in content_type):
        return "dash", "application/dash+xml"
    return "unknown", ""


def _hls_encryption_flags(text: str) -> tuple[bool, bool]:
    """Return (DRM-like key, AES-128 key) with linear manifest parsing."""
    drm_like = False
    aes_128 = False
    for raw_line in (text or "").splitlines():
        line = raw_line.lstrip()
        if not line.upper().startswith("#EXT-X-KEY:"):
            continue
        attributes = line.split(":", 1)[1]
        upper_attributes = attributes.upper()
        method = ""
        for field in attributes.split(","):
            name, separator, value = field.partition("=")
            if separator and name.strip().upper() == "METHOD":
                method = value.strip().strip("\"'").upper()
                break
        if method.startswith("SAMPLE-AES") or any(
            marker in upper_attributes for marker in ("SKD://", "WIDEVINE", "FAIRPLAY")
        ):
            drm_like = True
        if method == "AES-128":
            aes_128 = True
        if drm_like and aes_128:
            break
    return drm_like, aes_128


def _absolute_manifest_uri(value: str, base_url: str) -> str:
    if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", value or "", re.I):
        return value
    return urljoin(base_url, value)


def _rewrite_hls_manifest_for_local_file(text: str, base_url: str) -> str:
    rewritten: list[str] = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            rewritten.append(line)
            continue
        if stripped.startswith("#"):
            rewritten.append(
                re.sub(
                    r'URI="([^"]+)"',
                    lambda match: f'URI="{_absolute_manifest_uri(match.group(1), base_url)}"',
                    line,
                )
            )
            continue
        rewritten.append(_absolute_manifest_uri(stripped, base_url))
    return "\n".join(rewritten).rstrip() + "\n"


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _rewrite_dash_manifest_text_fallback(text: str, base_url: str) -> str:
    rewritten = re.sub(
        r"(<BaseURL\b[^>]*>)([^<]+)(</BaseURL>)",
        lambda match: f"{match.group(1)}{_absolute_manifest_uri(match.group(2).strip(), base_url)}{match.group(3)}",
        text or "",
        flags=re.I,
    )
    return re.sub(
        r'\b(media|initialization|sourceURL|index|href)="([^"]+)"',
        lambda match: f'{match.group(1)}="{_absolute_manifest_uri(match.group(2), base_url)}"',
        rewritten,
        flags=re.I,
    ).rstrip() + "\n"


def _rewrite_dash_manifest_for_local_file(text: str, base_url: str) -> str:
    raw = text or ""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return _rewrite_dash_manifest_text_fallback(raw, base_url)

    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
        if namespace:
            ET.register_namespace("", namespace)

    rewrite_attrs = {"media", "initialization", "sourceURL", "index", "href"}

    def rewrite_node(node: ET.Element, current_base: str) -> None:
        effective_base = current_base
        base_children = [child for child in list(node) if _xml_local_name(child.tag) == "BaseURL"]
        for child in base_children:
            value = (child.text or "").strip()
            if not value:
                continue
            absolute = _absolute_manifest_uri(value, effective_base)
            child.text = absolute
            if effective_base == current_base:
                effective_base = absolute

        for attr in list(node.attrib):
            if _xml_local_name(attr) in rewrite_attrs:
                value = (node.attrib.get(attr) or "").strip()
                if value:
                    node.attrib[attr] = _absolute_manifest_uri(value, effective_base)

        for child in list(node):
            if _xml_local_name(child.tag) != "BaseURL":
                rewrite_node(child, effective_base)

    rewrite_node(root, base_url)
    return ET.tostring(root, encoding="unicode").rstrip() + "\n"
