"""Source identities for completed text requests, not semantic chapters or a cache."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, NotRequired, TypedDict

from .reading_notes import SourceBlock, SourceWindow


class TextChunkPayload(TypedDict):
    kind: Literal["text_chunk"]
    generation_revision: str
    block_index: int
    block_digest: str
    source_windows: list[SourceWindow]
    markdown: str


class TextChunkSource(TypedDict):
    id: str
    kind: Literal["text_chunk"]
    block_index: int
    block_digest: str
    source_windows: list[SourceWindow]
    start: NotRequired[float]
    end: NotRequired[float]


def text_chunk_payload(block: SourceBlock, index: int, markdown: str, generation: str) -> TextChunkPayload:
    return {"kind": "text_chunk", "generation_revision": generation, "block_index": index,
            "block_digest": hashlib.sha256(block["text"].encode()).hexdigest(),
            "source_windows": block["source_windows"], "markdown": markdown}


def text_chunk_source(payload: dict, blocks: list[SourceBlock], source_revision: str) -> TextChunkSource | None:
    """Reject foreign/stale positions; generated prose never supplies timestamps."""
    index = payload.get("block_index")
    if type(index) is not int or index < 0:
        return None
    if index >= len(blocks):
        return None
    block = blocks[index]
    digest = hashlib.sha256(block["text"].encode()).hexdigest()
    windows = block["source_windows"]
    if payload.get("block_digest") != digest or json.dumps(payload.get("source_windows"), sort_keys=True) != json.dumps(windows, sort_keys=True):
        return None
    if any(not math.isfinite(w[key]) for w in windows for key in ("start", "end")) or any(
            w["start"] < 0 or w["end"] < w["start"] for w in windows):
        return None
    identity = json.dumps([source_revision, index, digest], ensure_ascii=False).encode()
    result: TextChunkSource = {"id": "text-" + hashlib.sha256(identity).hexdigest()[:24], "kind": "text_chunk",
                              "block_index": index, "block_digest": digest, "source_windows": windows}
    if windows:
        result.update(start=min(w["start"] for w in windows), end=max(w["end"] for w in windows))
    return result


def valid_text_chunk(item: dict, blocks: list[SourceBlock], source_revision: str) -> bool:
    expected = text_chunk_source(item, blocks, source_revision)
    if expected is None or any(item.get(key) != value for key, value in expected.items()):
        return False
    if not expected["source_windows"]:
        return "start" not in item and "end" not in item
    return all(type(item.get(key)) in (int, float) for key in ("start", "end"))
