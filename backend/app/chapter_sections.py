"""Source binding for provider-completed topic drafts, never verified evidence."""
from __future__ import annotations

import hashlib
import json
import math
import re

from .reading_notes import SourceBlock, source_block_entries, stamp
from .markdown_structure import structural_lines
from .storage import read_json
from .summary_outcome import safe_summary_text
from .text_cleanup import TextDecodingError, canonicalize_unicode_text, redact_sensitive_url_values


MAX_CHAPTERS = 32


def chapter_markdown_complete(markdown: str) -> bool:
    """The next chapter must remain prose after all current text transforms."""
    return list(structural_lines([*markdown.splitlines(), "", "chapter boundary"]))[-1][1]


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def chapter_payload(chapter: dict, index: int, blocks: list[SourceBlock], generation: str) -> dict:
    indexes = chapter["source_blocks"]
    windows = []
    for position in indexes:
        for window in blocks[position]["source_windows"]:
            if window not in windows:
                windows.append(dict(window))
    return {"kind": "topic_chapter", "generation_revision": generation, "chapter_index": index,
            "source_blocks": indexes, "block_digests": [_digest(blocks[position]) for position in indexes],
            "source_windows": windows, "title": chapter["title"], "markdown": chapter["markdown"]}


def chapter_provenance(source: dict, blocks: list[SourceBlock]) -> str:
    labels = []
    for index in source["source_blocks"]:
        windows = blocks[index]["source_windows"]
        bounds = (f"{stamp(min(window['start'] for window in windows))}–"
                  f"{stamp(max(window['end'] for window in windows))}" if windows else "原文无时间点")
        labels.append(f"来源块 {index + 1}（{bounds}）")
    return "> 来源块范围（粗略定位，具体内容仍需回源核对）：" + "；".join(labels)


def chapter_source(payload: dict, blocks: list[SourceBlock], source_revision: str) -> dict | None:
    """Resolve only request-bound positions; the provider cannot supply times/IDs."""
    index, indexes = payload.get("chapter_index"), payload.get("source_blocks")
    if (type(index) is not int or not 0 <= index < MAX_CHAPTERS
            or not isinstance(indexes, list) or not indexes
            or any(type(position) is not int or not 0 <= position < len(blocks) for position in indexes)
            or indexes != sorted(set(indexes))):
        return None
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 160 or re.search(r"[\r\n\x00-\x1f]", title):
        return None
    expected = chapter_payload({"source_blocks": indexes, "title": title, "markdown": ""}, index, blocks, "")
    if any(payload.get(key) != expected[key] for key in ("block_digests", "source_windows")):
        return None
    windows = expected["source_windows"]
    if any(not math.isfinite(window[key]) for window in windows for key in ("start", "end")) or any(
            window["start"] < 0 or window["end"] < window["start"] for window in windows):
        return None
    result = {key: expected[key] for key in ("kind", "chapter_index", "source_blocks", "block_digests", "source_windows", "title")}
    result["id"] = "chapter-" + _digest([source_revision, index, indexes, expected["block_digests"]])[:24]
    if windows:
        result.update(start=min(window["start"] for window in windows), end=max(window["end"] for window in windows))
    return result


def prepare_topic_source(task_id, transcript, payload, source_revision, expected_source_revision):
    """Prepare a source binding; publication must recheck it under the task lock."""
    if (not re.fullmatch(r"[a-f0-9]{64}", str(payload.get("generation_revision", "")))
            or expected_source_revision is not None and source_revision != expected_source_revision
            or read_json(task_id, "transcript.json", None) != transcript.model_dump(mode="json")):
        return None, []
    blocks = source_block_entries(transcript)
    source = chapter_source(payload, blocks, source_revision)
    if source is not None:
        try:
            source["title"] = safe_summary_text(redact_sensitive_url_values(canonicalize_unicode_text(source["title"])))
        except TextDecodingError:
            return None, blocks
    return source, blocks


def valid_chapter(item: dict, blocks: list[SourceBlock], source_revision: str) -> bool:
    expected = chapter_source(item, blocks, source_revision)
    if expected is None or any(item.get(key) != value for key, value in expected.items()):
        return False
    if not expected["source_windows"]:
        return "start" not in item and "end" not in item
    return all(type(item.get(key)) in (int, float) for key in ("start", "end"))
