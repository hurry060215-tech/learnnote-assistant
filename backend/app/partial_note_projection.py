"""Task-owned draft validation, legacy preservation, and read-only projection."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from .models import TranscriptResult
from .partial_outline_projection import partial_outline
from .reading_notes import source_block_entries
from .storage import get_task, task_file
from .text_chunk_sections import valid_text_chunk


_TASK_PROVENANCE = {"id", "created_at", "status", "retry_count", "source_identity", "options", "mode",
                    "note_path", "transcript_path", "summary_source"}


class _UnavailablePartial(ValueError):
    """Saved partial source mismatch; exception details remain internal."""


def partial_revision(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def valid_partial_section(item: object, source_revision: str, text_blocks: list) -> bool:
    if (not isinstance(item, dict) or item.get("status") != "evidence_pending"
            or item.get("verified") is not False or item.get("summary_generated") is not True
            or not isinstance(item.get("markdown"), str)
            or item.get("revision") != partial_revision(item["markdown"])):
        return False
    windows = item.get("source_windows")
    if not isinstance(windows, list) or any(not isinstance(window, dict)
            or type(window.get("index")) is not int or window["index"] < 0
            or any(type(window.get(key)) not in (int, float) or not math.isfinite(window[key]) for key in ("start", "end"))
            or window["start"] < 0 or window["end"] < window["start"] for window in windows):
        return False
    if item.get("kind") == "text_chunk":
        return valid_text_chunk(item, text_blocks, source_revision)
    if item.get("kind") != "vision_batch" or not windows:
        return False
    expected_id = "vision-" + partial_revision([source_revision, [[w["start"], w["end"]] for w in windows]])[:24]
    return (item.get("id") == expected_id
            and all(type(item.get(key)) in (int, float) for key in ("start", "end"))
            and item.get("start") == min(w["start"] for w in windows)
            and item.get("end") == max(w["end"] for w in windows))


def _partial_owned_file(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if (root.is_symlink() or path.is_symlink() or path.resolve().parent != root.resolve()
            or not path.is_file()):
        raise ValueError("Unavailable task artifact")
    return path


def _partial_json(root: Path, value: str | Path):
    path = _partial_owned_file(root, value)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Oversized task artifact")
    return json.loads(path.read_bytes().decode("utf-8"))


def _partial_attempt(root: Path) -> str:
    metrics = _partial_json(root, root / "pipeline_metrics.json")
    attempt = metrics.get("current_attempt_id") if isinstance(metrics, dict) else None
    if (not isinstance(metrics, dict) or type(metrics.get("schema_version")) is not int or metrics["schema_version"] != 2
            or not isinstance(attempt, str) or not re.fullmatch(r"[a-f0-9]{12}", attempt)):
        raise ValueError("Unavailable current attempt")
    return attempt


def attempt_owns_partial_revision(root: Path, attempt: str, revision: str) -> bool:
    # Publication of the draft pointer/Markdown precedes the ready event. The
    # stamp also prevents a late old callback being attributed to a new attempt.
    active, ready = False, False
    path = root / "events.jsonl"
    if not path.exists() and not path.is_symlink():
        return False
    path = _partial_owned_file(root, path)
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if not isinstance(event, dict) or type(event.get("schema_version")) is not int or event["schema_version"] != 1:
                return False
            details = event.get("details")
            if not isinstance(details, dict):
                return False
            if event.get("event") == "pipeline_attempt_started":
                active = details.get("attempt_id") == attempt
                ready = False
            elif active and event.get("event") == "partial_section_ready":
                ready = ready or (details.get("revision") == revision and details.get("verified") is False
                         and details.get("artifact") == "draft.partial.md" and event.get("status") == "draft")
    return active and ready


def preserve_previous_partial(root: Path) -> bytes | None:
    """Preserve exact bytes once before replacing an incompatible projection."""
    path = root / "partial_note.json"
    if not path.exists() and not path.is_symlink():
        return None
    raw = _partial_owned_file(root, path).read_bytes()
    backup = root / f"partial_note.previous.{hashlib.sha256(raw).hexdigest()}.json"
    if backup.is_symlink():
        raise ValueError("Unsafe previous projection backup")
    try:
        with backup.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if _partial_owned_file(root, backup).read_bytes() != raw:
            raise ValueError("Previous projection backup does not match")
    return raw


def prepare_legacy_partial(root: Path, previous: dict, attempt: str, source: str, generation: str, blocks: list) -> bool:
    """Preserve unstamped bytes before replacement; reuse only proven sections."""
    raw = preserve_previous_partial(root)
    if raw is None:
        return False
    try:
        persisted = json.loads(raw.decode("utf-8"))
        sections = previous.get("sections")
        return (persisted == previous and type(previous.get("schema_version")) is int and previous["schema_version"] == 1
                and previous.get("status") == "draft" and previous.get("verified") is False
                and previous.get("source_revision") == source and previous.get("generation_revision") == generation
                and previous.get("revision") == partial_revision({key: value for key, value in previous.items() if key != "revision"})
                and isinstance(sections, list) and bool(sections)
                and all(valid_partial_section(section, source, blocks) for section in sections)
                and len({section["id"] for section in sections}) == len(sections)
                and attempt_owns_partial_revision(root, attempt, previous["revision"]))
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RuntimeError):
        return False


def _partial_sections(document: object, transcript: TranscriptResult, media_sha256: str) -> list[dict]:
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] != 1 or document.get("status") != "draft"
            or document.get("verified") is not False):
        raise ValueError("Unavailable partial document")
    for key in ("source_revision", "generation_revision", "revision"):
        if not isinstance(document.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", document[key]):
            raise ValueError("Invalid partial revision")
    source = partial_revision([media_sha256, transcript.model_dump(mode="json")])
    if document["revision"] != partial_revision({key: value for key, value in document.items() if key != "revision"}):
        raise ValueError("Invalid partial document revision")
    if document["source_revision"] != source:
        raise _UnavailablePartial("source_mismatch")
    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("No partial sections")
    blocks, result, seen = source_block_entries(transcript), [], set()
    for order, section in enumerate(sections):
        if not valid_partial_section(section, source, blocks) or section["id"] in seen:
            raise ValueError("Invalid partial identity")
        windows = section["source_windows"]
        seen.add(section["id"])
        # Keep markdown literal; normalization/redaction belongs to generation.
        projected = {key: section[key] for key in ("id", "kind", "revision", "markdown", "status", "verified")}
        projected.update(order=order, source_windows=[{key: window[key] for key in ("index", "start", "end")} for window in windows])
        for key in (("block_index", "start", "end") if section["kind"] == "text_chunk" else ("start", "end")):
            if key in section:
                projected[key] = section[key]
        result.append(projected)
    return result


def _generated_partial(root: Path, task, attempt: str, transcript: TranscriptResult) -> dict:
    result = {"sections": [], "revision": "", "source_revision": "", "generation_revision": "", "reason": "not_ready"}
    if Path(task.note_path).name != "draft.partial.md":
        return result
    try:
        document = _partial_json(root, root / "partial_note.json")
        if isinstance(document, dict) and document.get("attempt_id") and document["attempt_id"] != attempt:
            return {**result, "reason": "attempt_mismatch"}
        sections = _partial_sections(document, transcript, task.source_identity.media_sha256)
        if document.get("attempt_id") != attempt:
            return {**result, "reason": "legacy_unproven"}
        try:
            ready = attempt_owns_partial_revision(root, attempt, document["revision"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            ready = False
        provenance = {key: document[key] for key in ("source_revision", "generation_revision")}
        if not ready:
            return {**result, **provenance, "reason": "publication_pending"}
        return {**provenance, "sections": sections, "revision": document["revision"], "reason": "ready"}
    except _UnavailablePartial:
        return {**result, "reason": "source_mismatch"}
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RuntimeError):
        return {**result, "reason": "invalid_artifact"}


def _outline_partial(root: Path, transcript: TranscriptResult, attempt: str) -> dict:
    result = {"sections": [], "revision": "", "reason": "not_ready"}
    path = root / "draft_sections.json"
    if not path.exists() and not path.is_symlink():
        return result
    try:
        return partial_outline(_partial_json(root, path), transcript, _partial_owned_file(root, root / "events.jsonl"), attempt)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RuntimeError):
        return {**result, "reason": "invalid_artifact"}


def read_partial_note(task_id: str) -> dict:
    """Read an unverified current-attempt projection; never run the pipeline."""
    root = task_file(task_id).parent
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise FileNotFoundError(task_id)
        _partial_owned_file(root, task_file(task_id))
        task = get_task(task_id)
        if task.id != task_id:
            raise FileNotFoundError(task_id)
    except (OSError, ValueError, RuntimeError) as exc:
        raise FileNotFoundError(task_id) from exc
    response = {"task_id": task.id, "attempt_id": "", "task_updated_at": task.updated_at,
                "schema_version": 1, "status": "unavailable", "reason": "not_ready", "verified": False,
                "revision": "", "source_revision": "", "generation_revision": "", "sections": []}
    try:
        if not (root / "pipeline_metrics.json").exists():
            return response
        attempt = _partial_attempt(root)
        response["attempt_id"] = attempt
        if (task.status not in {"running", "cancelling", "failed", "cancelled"}
                or (task.status in {"running", "cancelling"} and task.summary_source not in {"partial-draft", "transcript-draft"})
                or Path(task.note_path).name not in {"draft.md", "draft.partial.md"}):
            return response
        if Path(task.note_path).name == "draft.md" and not Path(task.note_path).exists() and not Path(task.note_path).is_symlink():
            return response
        _partial_owned_file(root, task.note_path)
        transcript = TranscriptResult.model_validate(_partial_json(root, task.transcript_path))
        generated = _generated_partial(root, task, attempt, transcript)
        outline = _outline_partial(root, transcript, attempt)
        current, current_attempt = get_task(task_id), _partial_attempt(root)
        response.update(task_updated_at=current.updated_at, attempt_id=current_attempt)
        if current.model_dump(include=_TASK_PROVENANCE) != task.model_dump(include=_TASK_PROVENANCE) or current_attempt != attempt:
            return {**response, "reason": "snapshot_changed"}
        if generated["reason"] == "publication_pending":
            return {**response, "reason": "publication_pending", "source_revision": generated["source_revision"],
                    "generation_revision": generated["generation_revision"]}
        sections = outline["sections"] + generated["sections"]
        if sections:
            for order, section in enumerate(sections):
                section["order"] = order
            digest = partial_revision([outline["revision"], generated["revision"]]) if outline["sections"] else generated["revision"]
            reason = generated["reason"] if generated["reason"] in {"legacy_unproven", "invalid_artifact", "attempt_mismatch", "source_mismatch"} else "ready"
            return {**response, "status": "draft", "reason": reason, "sections": sections, "revision": digest,
                    "source_revision": partial_revision([task.source_identity.media_sha256, transcript.model_dump(mode="json")]),
                    "generation_revision": generated["generation_revision"]}
        reason = generated["reason"] if generated["reason"] != "not_ready" else outline["reason"]
        response["reason"] = "not_ready" if reason == "publication_pending" else reason
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RuntimeError):
        response["reason"] = "invalid_artifact"
    return response
