"""Source binding for one completed short, non-stream response draft."""
from __future__ import annotations

import hashlib
import json
import math

from .reading_notes import SourceBlock


def full_response_payload(blocks: list[SourceBlock], markdown: str, generation: str) -> dict:
    """One completed request owns all its input blocks, never invented chapters."""
    windows = []
    for block in blocks:
        for window in block["source_windows"]:
            if window not in windows:
                windows.append(dict(window))
    return {"kind": "full_response", "generation_revision": generation,
            "source_blocks": list(range(len(blocks))),
            "block_digests": [hashlib.sha256(block["text"].encode()).hexdigest() for block in blocks],
            "source_windows": windows, "markdown": markdown}


def full_response_source(payload: dict, blocks: list[SourceBlock], source_revision: str) -> dict | None:
    if not 1 <= len(blocks) <= 3:
        return None
    expected = full_response_payload(blocks, "", "")
    if (any(payload.get(key) != expected[key] for key in ("source_blocks", "block_digests", "source_windows"))
            or any(type(index) is not int for index in payload["source_blocks"])):
        return None
    windows = expected["source_windows"]
    if any(not math.isfinite(w[key]) for w in windows for key in ("start", "end")) or any(
            w["start"] < 0 or w["end"] < w["start"] for w in windows):
        return None
    source = {key: expected[key] for key in ("kind", "source_blocks", "block_digests", "source_windows")}
    identity = json.dumps([source_revision, source], ensure_ascii=False, sort_keys=True).encode()
    source["id"] = "response-" + hashlib.sha256(identity).hexdigest()[:24]
    if windows:
        source.update(start=min(w["start"] for w in windows), end=max(w["end"] for w in windows))
    return source


def valid_full_response(item: dict, blocks: list[SourceBlock], source_revision: str) -> bool:
    expected = full_response_source(item, blocks, source_revision)
    if expected is None or any(item.get(key) != value for key, value in expected.items()):
        return False
    if not expected["source_windows"]:
        return "start" not in item and "end" not in item
    return all(type(item.get(key)) in (int, float) for key in ("start", "end"))
