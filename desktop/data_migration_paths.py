"""Explicit, destination-only mapping for the desktop data-directory transaction.

This is deliberately separate from task_paths: ordinary reads never acquire a
migration fallback. Paths in metadata are inspected lexically, never opened.
Only inventoried files in the selected snapshot are read. Plans are inert JSON;
applying a plan requires a disjoint, byte-identical disposable staging tree.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
from typing import Any


class ReferenceMappingError(ValueError):
    """An unsupported or changed migration must leave activation to the caller."""

    def __init__(self, code: str, location: str = ""):
        self.code = code
        self.location = location
        super().__init__(code + (f": {location}" if location else ""))


TASK_FIELDS = frozenset("source_media_path media_path audio_path subtitle_path transcript_path visual_index_path media_integrity_path evidence_coverage_path note_path summary_diagnostics_path resource_inventory_path resource_usage_path page_preflight_report_path".split())
DIAGNOSTIC_FIELDS = frozenset("note_quality_path note_document_path claim_evidence_map_path transcript_quality_path".split())
_MEDIA_FIELDS = {"source_media_path", "media_path"}
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_FIXED = {
    "transcript_path": {"transcript.json"}, "visual_index_path": {"visual_index.json"},
    "media_integrity_path": {"media_integrity.json"}, "evidence_coverage_path": {"evidence_coverage.json"},
    "summary_diagnostics_path": {"summary_diagnostics.json"}, "resource_inventory_path": {"resource_inventory.json"},
    "resource_usage_path": {"resource_usage.json"}, "page_preflight_report_path": {"page_preflight_report.json"},
    "note_path": {"note.md", "draft.md", "draft.partial.md", "draft.review.md", "captions.md", "screen_subtitles.md"},
    **{key: {key.removesuffix("_path") + ".json"} for key in DIAGNOSTIC_FIELDS},
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}
_MAX_JSON = 32 * 1024 * 1024


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plain(value: str):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReferenceMappingError("invalid_reference")
    windows = bool("\\" in value or re.match(r"^[A-Za-z]:", value))
    if windows:
        if "/" in value or not re.match(r"^[A-Za-z]:\\", value) or ":" in value[2:]:
            raise ReferenceMappingError("ambiguous_reference")
        parsed = PureWindowsPath(value)
    else:
        if ":" in value or value.startswith("//"):
            raise ReferenceMappingError("ambiguous_reference")
        parsed = PurePosixPath(value)
    if any(part in {".", ".."} for part in re.split(r"[\\/]", value)):
        raise ReferenceMappingError("reference_traversal")
    for part in parsed.parts[1:] if parsed.is_absolute() else parsed.parts:
        if part.endswith((".", " ")) or PureWindowsPath(part).is_reserved() or any(ord(c) < 32 for c in part):
            raise ReferenceMappingError("ambiguous_reference")
    return parsed, windows


def _lexically_under_source(value: str, source) -> bool:
    """Recognize complete selected-root pointers without probing the filesystem.

    This is a rejection check for unknown schemas, so Windows' alternate slash
    spellings must not bypass it even though approved slots reject mixed syntax.
    Absolute traversal and double-leading separators are conservatively rejected
    even outside the source prefix: their interpretation cannot authorize a
    rewrite. Pure paths supply case rules and segment-aware containment only.
    """
    root, windows = _plain(str(source))
    if windows:
        if value.startswith(("\\\\", "//")):
            return True  # UNC/device roots are ambiguous in an unknown slot.
        if not re.match(r"^[A-Za-z]:[\\/]", value):
            return False
        if any(part in {".", ".."} for part in re.split(r"[\\/]", value)):
            return True
        candidate = PureWindowsPath(value)
    else:
        if not value.startswith("/"):
            return False
        if value.startswith("//") or any(part in {".", ".."} for part in value.split("/")):
            return True
        candidate = PurePosixPath(value)
    if not candidate.is_absolute():
        return False
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_name(value: str) -> str:
    parsed, windows = _plain(value)
    if windows or parsed.is_absolute() or str(parsed) != value or "\\" in value:
        raise ReferenceMappingError("invalid_inventory_path", value)
    return value


def _native_root(value: Path | str) -> Path:
    parsed, windows = _plain(str(value))
    if not parsed.is_absolute() or windows != (os.name == "nt"):
        raise ReferenceMappingError("native_absolute_root_required")
    return Path(str(parsed))


def _id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ReferenceMappingError("invalid_task_identity")
    return value


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _node(path: Path, *, file: bool) -> os.stat_result:
    try:
        item = path.lstat()
    except OSError as exc:
        raise ReferenceMappingError("missing_snapshot_file", str(path)) from exc
    if stat.S_ISLNK(item.st_mode) or getattr(item, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ReferenceMappingError("linked_snapshot", str(path))
    if not (stat.S_ISREG(item.st_mode) if file else stat.S_ISDIR(item.st_mode)):
        raise ReferenceMappingError("invalid_snapshot_type", str(path))
    return item


def _checked_file(root: Path, relative: str) -> Path:
    # Include ancestors of the snapshot itself, so a linked parent is not trusted.
    current = Path(root.anchor)
    _node(current, file=False)
    for part in root.parts[1:]:
        current /= part
        _node(current, file=False)
    parts = PurePosixPath(_relative_name(relative)).parts
    for index, part in enumerate(parts):
        current /= part
        _node(current, file=index == len(parts) - 1)
    return current


def _read_checked(root: Path, relative: str, expected: dict, *, limit: int | None = None, keep=True) -> bytes:
    path = _checked_file(root, relative)
    before = path.lstat()
    if before.st_size != expected["size"] or (limit is not None and before.st_size > limit):
        raise ReferenceMappingError("snapshot_changed_or_too_large", relative)
    # O_NOFOLLOW closes the final-node symlink race on supported platforms.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ReferenceMappingError("snapshot_changed", relative)
        chunks, digest, size = [], hashlib.sha256(), 0
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if keep:
                chunks.append(chunk)
        raw = b"".join(chunks) if keep else b""
        after = os.fstat(handle.fileno())
    current = path.lstat()
    if ((before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_dev, after.st_ino)
            or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            or size != expected["size"] or digest.hexdigest() != expected["sha256"]):
        raise ReferenceMappingError("snapshot_changed", relative)
    return raw


class JsonDocument:
    """Parse strictly and remember string spans, preserving all unedited bytes."""

    def __init__(self, raw: bytes):
        try:
            self.text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ReferenceMappingError("invalid_json_encoding") from exc
        self.spans: dict[tuple, tuple[int, int]] = {}
        decoder = json.JSONDecoder(parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        text = self.text

        def whitespace(index):
            while index < len(text) and text[index] in " \r\n\t":
                index += 1
            return index

        def value(index, pointer, depth):
            if depth > 64:
                raise ValueError("depth")
            index = whitespace(index)
            if index >= len(text):
                raise ValueError("end")
            if text[index] == "{":
                result = {}
                index = whitespace(index + 1)
                if index < len(text) and text[index] == "}":
                    return result, index + 1
                while True:
                    key, end = decoder.raw_decode(text, index)
                    if not isinstance(key, str) or key in result:
                        raise ValueError("duplicate or invalid key")
                    index = whitespace(end)
                    if text[index] != ":":
                        raise ValueError("colon")
                    result[key], index = value(index + 1, pointer + (key,), depth + 1)
                    index = whitespace(index)
                    if text[index] == "}":
                        return result, index + 1
                    if text[index] != ",":
                        raise ValueError("comma")
                    index = whitespace(index + 1)
            if text[index] == "[":
                result = []
                index = whitespace(index + 1)
                if index < len(text) and text[index] == "]":
                    return result, index + 1
                while True:
                    item, index = value(index, pointer + (len(result),), depth + 1)
                    result.append(item)
                    index = whitespace(index)
                    if text[index] == "]":
                        return result, index + 1
                    if text[index] != ",":
                        raise ValueError("comma")
                    index = whitespace(index + 1)
            result, end = decoder.raw_decode(text, index)
            if isinstance(result, str):
                self.spans[pointer] = (index, end)
            if isinstance(result, float) and not math.isfinite(result):
                raise ValueError("nonfinite")
            return result, end

        try:
            self.value, end = value(0, (), 0)
            if whitespace(end) != len(text):
                raise ValueError("trailing data")
        except (ValueError, TypeError, IndexError, RecursionError) as exc:
            raise ReferenceMappingError("invalid_json") from exc

    def replace(self, replacements: dict[tuple, str]) -> bytes:
        text = self.text
        for pointer in sorted(replacements, key=lambda item: self.spans[item][0], reverse=True):
            start, end = self.spans[pointer]
            text = text[:start] + json.dumps(replacements[pointer], ensure_ascii=False) + text[end:]
        return text.encode("utf-8")


def _pointer(parts: tuple) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _path_key(key: str) -> bool:
    key = key.casefold()
    return key in {"path", "paths"} or key.endswith(("_path", "_paths"))


def _path_values(value: Any, pointer=()):
    if isinstance(value, dict):
        for key, child in value.items():
            next_pointer = pointer + (key,)
            if _path_key(key):
                if isinstance(child, list):
                    if not child:
                        yield next_pointer, child
                    for index, item in enumerate(child):
                        yield next_pointer + (index,), item
                else:
                    yield next_pointer, child
            else:
                yield from _path_values(child, next_pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _path_values(child, pointer + (index,))


def _slot(kind: str, pointer: tuple) -> str | None:
    if kind == "task.json":
        if len(pointer) == 1 and pointer[0] in TASK_FIELDS:
            return pointer[0]
        if len(pointer) == 2 and pointer[0] == "summary_diagnostics" and pointer[1] in DIAGNOSTIC_FIELDS:
            return pointer[1]
        if len(pointer) == 3 and isinstance(pointer[1], int):
            if pointer[0] == "download_attempts" and pointer[2] == "output_path":
                return "output_path"
            if pointer[0] == "frame_grids" and pointer[2] == "path":
                return "grid_path"
            if pointer[0] == "visual_windows" and pointer[2] == "grid_path":
                return "grid_path"
        if (len(pointer) == 4 and pointer[0] == "frame_grids" and isinstance(pointer[1], int)
                and pointer[2] in {"frame_paths", "important_frame_paths"} and isinstance(pointer[3], int)):
            return "frame_path"
    elif kind == "visual_index.json":
        if len(pointer) == 3 and isinstance(pointer[1], int):
            if pointer[0] in {"frames", "important_frames"} and pointer[2] == "path":
                return "frame_path"
            if pointer[0] == "windows" and pointer[2] == "grid_path":
                return "grid_path"
    elif kind == "summary_diagnostics.json" and len(pointer) == 1 and pointer[0] in DIAGNOSTIC_FIELDS:
        return pointer[0]
    return None


def _validate_shape(kind: str, payload: dict):
    collections = {"task.json": {"download_attempts", "frame_grids", "visual_windows"},
                   "visual_index.json": {"frames", "important_frames", "windows"}}.get(kind, set())
    for key in collections:
        if key in payload:
            items = payload[key]
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ReferenceMappingError("unknown_reference_shape", key)
            if key == "frame_grids":
                for item in items:
                    for field in ("frame_paths", "important_frame_paths"):
                        if field in item and not isinstance(item[field], list):
                            raise ReferenceMappingError("unknown_reference_shape", field)
    if "summary_diagnostics" in payload and not isinstance(payload["summary_diagnostics"], dict):
        raise ReferenceMappingError("unknown_reference_shape", "summary_diagnostics")


class MappingContext:
    def __init__(self, source_root, snapshot_root, destination_root, inventory):
        self.source = _native_root(source_root)
        self.snapshot = _native_root(snapshot_root)
        self.destination = _native_root(destination_root)
        if _overlap(self.source, self.destination) or _overlap(self.snapshot, self.destination) or _overlap(self.source, self.snapshot):
            raise ReferenceMappingError("overlapping_roots")
        if not isinstance(inventory, dict):
            raise ReferenceMappingError("invalid_inventory")
        self.inventory = {}
        cases = set()
        for relative, item in inventory.items():
            _relative_name(relative)
            if relative.casefold() in cases:
                raise ReferenceMappingError("colliding_snapshot_paths", relative)
            cases.add(relative.casefold())
            if (not isinstance(item, dict) or type(item.get("size")) is not int or item["size"] < 0
                    or not isinstance(item.get("sha256"), str) or not _SHA256.fullmatch(item["sha256"])):
                raise ReferenceMappingError("invalid_inventory", relative)
            self.inventory[relative] = {"size": item["size"], "sha256": item["sha256"]}
        self.tasks: dict[str, dict] = {}
        self.documents: dict[str, JsonDocument] = {}
        self.external: list[dict] = []
        self.changes: list[dict] = []
        self.outputs: dict[str, bytes] = {}
        self.files: list[dict] = []

    def read(self, relative, *, json_file=False):
        if relative not in self.inventory:
            raise ReferenceMappingError("missing_inventory_file", relative)
        return _read_checked(self.snapshot, relative, self.inventory[relative], limit=_MAX_JSON if json_file else None)

    def verify(self, relative):
        if relative not in self.inventory:
            raise ReferenceMappingError("missing_inventory_file", relative)
        _read_checked(self.snapshot, relative, self.inventory[relative], keep=False)

    def verify_inventory(self):
        for relative in sorted(self.inventory):
            self.verify(relative)

    def document(self, relative):
        if relative not in self.documents:
            self.documents[relative] = JsonDocument(self.read(relative, json_file=True))
        return self.documents[relative]

    def load_tasks(self):
        for relative in sorted(self.inventory):
            parts = PurePosixPath(relative).parts
            if parts[0] != "tasks":
                continue
            if len(parts) < 3:
                raise ReferenceMappingError("unknown_task_layout", relative)
            owner = _id(parts[1])
            if len(parts) == 3 and parts[2] == "task.json":
                payload = self.document(relative).value
                if not isinstance(payload, dict) or payload.get("id") != owner:
                    raise ReferenceMappingError("task_identity_mismatch", relative)
                if (type(payload.get("schema_version", 0)) is not int or payload.get("schema_version", 0) not in {0, 1}):
                    raise ReferenceMappingError("unsupported_task_schema", relative)
                _validate_shape("task.json", payload)
                for field in ("source_identity", "media_integrity", "options", "learning_range"):
                    if field in payload and not isinstance(payload[field], dict):
                        raise ReferenceMappingError("unknown_task_identity_shape", field)
                for field in ("selected_resource", "active_video"):
                    if field in payload and payload[field] is not None and not isinstance(payload[field], dict):
                        raise ReferenceMappingError("unknown_task_identity_shape", field)
                if "source_task_id" in payload and not isinstance(payload["source_task_id"], str):
                    raise ReferenceMappingError("invalid_task_identity", relative)
                self.tasks[owner] = payload
        for relative in self.inventory:
            parts = PurePosixPath(relative).parts
            if parts[0] == "tasks" and parts[1] not in self.tasks:
                raise ReferenceMappingError("missing_task_manifest", relative)
        for task in self.tasks.values():
            current, seen = task, set()
            while current.get("source_task_id"):
                identifier = _id(current["source_task_id"])
                if identifier in seen or identifier == task["id"] or len(seen) >= 16:
                    raise ReferenceMappingError("cyclic_task_ancestry", task["id"])
                seen.add(identifier)
                if identifier not in self.tasks:
                    raise ReferenceMappingError("missing_task_ancestor", identifier)
                current = self.tasks[identifier]

    def relative_reference(self, value: str, owner: str | None = None):
        parsed, windows = _plain(value)
        if windows != (os.name == "nt"):
            raise ReferenceMappingError("foreign_reference_root")
        if not parsed.is_absolute():
            if owner is None:
                raise ReferenceMappingError("ambiguous_reference_root")
            return ("tasks", owner, *parsed.parts)
        try:
            return Path(str(parsed)).relative_to(self.source).parts
        except ValueError:
            return None

    def _reference_equal(self, first, second, first_owner, second_owner):
        if not isinstance(first, str) or not isinstance(second, str) or not first or not second:
            return False
        relative = self.relative_reference(first, first_owner)
        return relative is not None and relative == self.relative_reference(second, second_owner)

    def _range_link(self, child, parent, field):
        selected, original = child.get("learning_range", {}), parent.get("learning_range", {})
        required = {"start", "end", "original_start", "original_end"}

        def invalid():
            raise ReferenceMappingError("ancestor_range_mismatch", child["id"])

        def number(value):
            try:
                if type(value) not in {int, float} or not math.isfinite(value):
                    invalid()
                result = Decimal(str(value))
                if not result.is_finite():
                    invalid()
                return result
            except (OverflowError, InvalidOperation):
                invalid()

        def checked_range(value):
            if not isinstance(value, dict) or set(value) - required:
                invalid()
            if not value:
                return {}
            if not {"start", "end"} <= value.keys():
                invalid()
            result = {key: number(item) for key, item in value.items()}
            if not 0 <= result["start"] < result["end"]:
                invalid()
            origin_keys = {"original_start", "original_end"} & result.keys()
            if origin_keys and (len(origin_keys) != 2 or not 0 <= result["original_start"] < result["original_end"]):
                invalid()
            return result

        chosen, prior = checked_range(selected), checked_range(original)
        if selected == original:
            return False
        if field not in _MEDIA_FIELDS or set(selected) != required:
            invalid()
        # Match range admission exactly: decimal logical intervals, then float
        # persisted offsets. Binary base+offset or end-start rejects valid nested
        # producer values such as 0.1 + 0.2 -> 0.3.
        integrity = parent.get("media_integrity", {})
        duration = integrity.get("duration") if isinstance(integrity, dict) else None
        number(duration)
        start, end = selected["start"], selected["end"]
        if duration <= 0 or end > duration + .01:
            invalid()
        base = prior.get("original_start", prior.get("start", Decimal("0")))
        expected_start = float(base + chosen["start"])
        expected_end = float(base + chosen["end"])
        if (not math.isfinite(expected_start) or not math.isfinite(expected_end)
                or selected["original_start"] != expected_start or selected["original_end"] != expected_end):
            invalid()
        if prior:
            logical_duration = prior["end"] - prior["start"]
            if (not logical_duration.is_finite() or logical_duration <= 0 or chosen["end"] > logical_duration
                    or "original_end" in prior and selected["original_end"] > original["original_end"]):
                invalid()
        return True

    def _link(self, child, parent, field):
        if child.get("mode") not in {"rerun_from_media", "subtitle_only", "screen_subtitles"}:
            raise ReferenceMappingError("unsupported_task_ancestry", child["id"])
        if child.get("page_url", "") != parent.get("page_url", ""):
            raise ReferenceMappingError("ancestor_page_mismatch", child["id"])
        is_range = self._range_link(child, parent, field)
        for key in ("selected_resource", "active_video"):
            if child.get(key) != parent.get(key) and not (is_range and child.get(key) is None):
                raise ReferenceMappingError("ancestor_part_mismatch", child["id"])
        # Range admission copies page/platform identity, whereas ordinary rerun
        # admission intentionally replaces identity with its local media hash.
        if is_range:
            for key in ("page_url", "platform", "platform_id"):
                if child.get("source_identity", {}).get(key, "") != parent.get("source_identity", {}).get(key, ""):
                    raise ReferenceMappingError("ancestor_part_mismatch", child["id"])

    def _caption_link(self, child, parent, value):
        if (child.get("mode") != "subtitle_only" or child.get("summary_source") != "subtitle-extract"
                or child.get("options", {}).get("content_mode") != "subtitles"):
            raise ReferenceMappingError("unsupported_subtitle_ancestry", child["id"])
        identity = child.get("source_identity", {})
        digest = identity.get("media_sha256", "")
        if (not isinstance(digest, str) or not _SHA256.fullmatch(digest)
                or child.get("media_integrity", {}).get("sha256") != digest
                or identity.get("platform") != "local" or identity.get("platform_id") != digest[:16]
                or identity.get("resource_fingerprint") != digest):
            raise ReferenceMappingError("subtitle_identity_mismatch", child["id"])
        if not self._reference_equal(value, parent.get("subtitle_path"), child["id"], parent["id"]):
            raise ReferenceMappingError("subtitle_pointer_mismatch", child["id"])
        source_media = child.get("source_media_path")
        if not source_media or not any(self._reference_equal(source_media, parent.get(key), child["id"], parent["id"]) for key in _MEDIA_FIELDS):
            raise ReferenceMappingError("subtitle_media_mismatch", child["id"])
        if child.get("media_path") and not self._reference_equal(child["media_path"], source_media, child["id"], child["id"]):
            raise ReferenceMappingError("subtitle_media_mismatch", child["id"])
        for key in ("note_path", "transcript_path"):
            reference = self.relative_reference(child.get(key, ""), child["id"])
            if not reference or reference[:2] != ("tasks", child["id"]):
                raise ReferenceMappingError("subtitle_identity_mismatch", child["id"])
            self.verify("/".join(reference))
        for filename in ("pipeline_metrics.json", "whole_attempt_duration_evidence.json"):
            relative = f"tasks/{child['id']}/{filename}"
            if relative not in self.inventory:
                continue
            def routes(item):
                if isinstance(item, dict):
                    if item.get("entry_route") and item["entry_route"] not in {"local_media", "subtitle_only", "rerun_from_media"}:
                        raise ReferenceMappingError("subtitle_route_mismatch", child["id"])
                    for nested in item.values():
                        routes(nested)
                elif isinstance(item, list):
                    for nested in item:
                        routes(nested)
            routes(self.document(relative).value)

    def ancestry(self, task_id, owner, field, value):
        if field not in {*_MEDIA_FIELDS, "subtitle_path", "output_path"}:
            raise ReferenceMappingError("cross_task_reference_forbidden", task_id)
        current = self.tasks[task_id]
        for _ in range(16):
            parent_id = current.get("source_task_id")
            if not parent_id or parent_id not in self.tasks:
                raise ReferenceMappingError("missing_reference_ancestry", task_id)
            parent = self.tasks[parent_id]
            self._link(current, parent, field)
            if field == "subtitle_path":
                self._caption_link(current, parent, value)
            elif field == "output_path":
                attempts = parent.get("download_attempts", [])
                if not any(self._reference_equal(value, item.get("output_path"), task_id, parent_id) for item in attempts):
                    raise ReferenceMappingError("ancestor_pointer_mismatch", task_id)
            elif not any(self._reference_equal(value, parent.get(key), task_id, parent_id) for key in _MEDIA_FIELDS):
                raise ReferenceMappingError("ancestor_pointer_mismatch", task_id)
            if parent_id == owner:
                return
            current = parent
        raise ReferenceMappingError("missing_reference_ancestry", task_id)

    def map_task(self, value, task_id, field, location):
        if not isinstance(value, str):
            raise ReferenceMappingError("unknown_reference_shape", location)
        if not value:
            return value
        relative = self.relative_reference(value, task_id)
        if relative is None:
            parsed, _ = _plain(value)
            # An old data-root path is never reclassified as an external input.
            parts = tuple(part.casefold() for part in parsed.parts)
            if field not in _MEDIA_FIELDS or "tasks" in parts or "uploads" in parts or "materials" in parts:
                raise ReferenceMappingError("foreign_reference_root", location)
            task = self.tasks[task_id]
            if task.get("source_type") != "local" or task.get("source_task_id"):
                raise ReferenceMappingError("external_original_unproven", location)
            self.external.append({"file": location.split("#", 1)[0], "location": location, "value": value,
                                  "disposition": "unchanged_external_original_not_copied"})
            return value
        if not relative:
            raise ReferenceMappingError("invalid_reference", location)
        if relative[0] == "uploads" and len(relative) == 2 and field in _MEDIA_FIELDS:
            owners = [owner for owner in self.tasks if relative[1].startswith(owner + "_")]
            if len(owners) != 1:
                raise ReferenceMappingError("ambiguous_upload_owner", location)
            if owners[0] != task_id:
                self.ancestry(task_id, owners[0], field, value)
        elif len(relative) >= 3 and relative[0] == "tasks":
            owner = _id(relative[1])
            if owner not in self.tasks:
                raise ReferenceMappingError("missing_task_manifest", location)
            if owner != task_id:
                self.ancestry(task_id, owner, field, value)
            tail = relative[2:]
            if field in _FIXED and (len(tail) != 1 or tail[0] not in _FIXED[field]):
                raise ReferenceMappingError("unsupported_artifact_name", location)
            if field == "subtitle_path" and not (len(tail) in {1, 2} and (len(tail) == 1 or tail[0] == "downloads") and PurePosixPath(tail[-1]).suffix.lower() in _SUBTITLE_SUFFIXES):
                raise ReferenceMappingError("unsupported_artifact_name", location)
            if field in {"grid_path", "frame_path"}:
                folder = "grids" if field == "grid_path" else "frames"
                if not ((len(tail) == 2 and tail[0] == folder or len(tail) == 1 and field == "grid_path") and PurePosixPath(tail[-1]).suffix.lower() in _IMAGE_SUFFIXES):
                    raise ReferenceMappingError("unsupported_artifact_name", location)
            if field in {*_MEDIA_FIELDS, "audio_path", "output_path"} and not (len(tail) == 1 or len(tail) == 2 and tail[0] == "downloads"):
                raise ReferenceMappingError("unsupported_artifact_name", location)
        else:
            raise ReferenceMappingError("unowned_reference", location)
        self.verify("/".join(relative))
        return str(self.destination.joinpath(*relative))

    def map_documents(self):
        for relative in sorted(self.inventory):
            parts = PurePosixPath(relative).parts
            # User originals, raw resources, exports and static assets are opaque.
            # All remaining JSON is application metadata; unfamiliar path slots
            # block instead of silently retaining a pointer into the old root.
            if (not parts[-1].endswith(".json") or parts[0] in {"materials", "uploads", "raw-imports", "exports", "static"}
                    or parts[0] == "tasks" and len(parts) > 3 and parts[2] == "downloads"):
                continue
            document = self.document(relative)
            payload = document.value
            kind = parts[2] if len(parts) == 3 and parts[0] == "tasks" else ""
            known = kind in {"task.json", "visual_index.json", "summary_diagnostics.json"}
            if known and not isinstance(payload, dict):
                raise ReferenceMappingError("unknown_task_metadata_shape", relative)
            if known:
                _validate_shape(kind, payload)
            if kind == "visual_index.json" and payload.get("task_id") != parts[1]:
                raise ReferenceMappingError("visual_index_identity_mismatch", relative)
            if kind in {"visual_index.json", "summary_diagnostics.json"} and "schema_version" in payload and (type(payload["schema_version"]) is not int or payload["schema_version"] != 1):
                raise ReferenceMappingError("unsupported_companion_schema", relative)
            replacements = {}
            recognized = set()
            for pointer, value in _path_values(payload):
                if (kind == "task.json" and len(pointer) == 3 and pointer[0] == "frame_grids"
                        and isinstance(pointer[1], int) and pointer[2] in {"frame_paths", "important_frame_paths"} and value == []):
                    continue
                field = _slot(kind, pointer)
                location = relative + "#" + _pointer(pointer)
                if field is None:
                    raise ReferenceMappingError("unsupported_reference_schema", location)
                recognized.add(pointer)
                changed = self.map_task(value, parts[1], field, location)
                if changed != value:
                    replacements[pointer] = changed
                    self.changes.append({"file": relative, "json_pointer": _pointer(pointer), "before": value, "after": changed})
            for pointer in document.spans:
                if pointer in recognized:
                    continue
                value = payload
                for component in pointer:
                    value = value[component]
                if _lexically_under_source(value, self.source):
                    raise ReferenceMappingError("unsupported_reference_schema", relative + "#" + _pointer(pointer))
            if replacements:
                result = document.replace(replacements)
                masked = {pointer: "__MIGRATION_REFERENCE__" for pointer in replacements}
                preserved = _digest(document.replace(masked))
                if _digest(JsonDocument(result).replace(masked)) != preserved:
                    raise ReferenceMappingError("nonpath_json_changed", relative)
                self.outputs[relative] = result
                self.files.append({"path": relative, "original_sha256": self.inventory[relative]["sha256"],
                                   "result_sha256": _digest(result), "result_size": len(result),
                                   "nonpath_bytes_sha256": preserved, "operation": "replace"})


def _build_plan(source_root, snapshot_root, destination_root, inventory):
    from .data_migration_catalog import plan_catalog
    context = MappingContext(source_root, snapshot_root, destination_root, inventory)
    context.verify_inventory()
    context.load_tasks()
    context.map_documents()
    catalog, catalog_outputs, removed = plan_catalog(context)
    context.outputs.update(catalog_outputs)
    context.verify_inventory()
    plan = {"version": 1, "source_root": str(context.source), "destination_root": str(context.destination),
            "inventory": context.inventory, "changes": context.changes, "external_references": context.external,
            "files": context.files, "removed_paths": removed, "catalog_proof": catalog}
    return plan, context.outputs


def plan_reference_changes(source_root, snapshot_root, destination_root, inventory) -> dict:
    """Read a selected snapshot only. Never open a recorded pointer or write it.

    The launcher supplies a verified scratch copy for preview, never the source.
    SQLite families are inspected on further private disposable copies.
    Extra inventory metadata (mtime/device/inode) is left to the copy transaction.
    """
    return _build_plan(source_root, snapshot_root, destination_root, inventory)[0]


def apply_reference_changes(stage_root, plan: dict) -> dict:
    """Revalidate the complete approved plan and change only a disjoint stage.

    The caller owns cleanup if interrupted during staging, final verification,
    atomic destination publication, configuration activation and recovery receipt.
    """
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise ReferenceMappingError("unsupported_mapping_plan")
    stage = _native_root(stage_root)
    source = _native_root(plan["source_root"])
    destination = _native_root(plan["destination_root"])
    if _overlap(stage, source) or _overlap(stage, destination):
        raise ReferenceMappingError("mapping_requires_disjoint_stage")
    rebuilt, outputs = _build_plan(source, stage, destination, plan["inventory"])
    if rebuilt != plan:
        raise ReferenceMappingError("mapping_plan_changed")
    # All validation is complete before the first staged write. Parent keeps
    # activation transactional; a partially rewritten stage can only be removed.
    for relative in plan["inventory"]:
        if _checked_file(stage, relative).lstat().st_nlink != 1:
            raise ReferenceMappingError("linked_or_changed_stage", relative)
    for relative in sorted(outputs):
        path = _checked_file(stage, relative)
        _read_checked(stage, relative, plan["inventory"][relative])
        before = path.lstat()
        descriptor = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "wb") as handle:
            opened = os.fstat(handle.fileno())
            if opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ReferenceMappingError("linked_or_changed_stage", relative)
            handle.truncate(0)
            handle.write(outputs[relative])
            handle.flush()
            os.fsync(handle.fileno())
    for relative in plan["removed_paths"]:
        _read_checked(stage, relative, plan["inventory"][relative])
        _checked_file(stage, relative).unlink()
    by_path = {item["path"]: item for item in plan["files"]}
    for relative, expected in plan["inventory"].items():
        if relative in plan["removed_paths"]:
            continue
        if relative in by_path:
            item = by_path[relative]
            expected = {"size": item["result_size"], "sha256": item["result_sha256"]}
        _read_checked(stage, relative, expected)
    return plan


# Explicit naming retained for callers that already perform their own staging.
plan_staged_references = plan_reference_changes


def rewrite_staged_references(source_root, stage_root, destination_root, inventory) -> dict:
    stage, source, destination = map(_native_root, (stage_root, source_root, destination_root))
    if _overlap(stage, source) or _overlap(stage, destination):
        raise ReferenceMappingError("mapping_requires_disjoint_stage")
    return apply_reference_changes(stage, plan_reference_changes(source, stage, destination, inventory))
