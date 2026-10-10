"""Bounded, optional local measurements of work after transcript readiness.

No model calls, stage-time sums, progress-percentage extrapolation or legacy
backfill. See docs/LOCAL_DURATION_ESTIMATES.md for the matching policy.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from . import config, storage

SCHEMA_VERSION = 1
SCOPE = "after_transcript_ready"
FILENAME = "duration_evidence.json"
MIN_SAMPLES = 5
MAX_SAMPLES = 30
MAX_TASKS = 256
MAX_BYTES = 64 * 1024
MAX_AGE_SECONDS = 30 * 86400
MAX_DURATION_SECONDS = 24 * 3600
CACHE_SECONDS = 30
SOURCES = {"browser-subtitle", "page-subtitle", "embedded-subtitle", "faster-whisper", "openai-compatible-asr", "groq-asr"}
ROUTES = {"media_to_note", "transcript_to_note"}
# In-process monotonic clocks are never reconstructed from saved wall times.
_active: OrderedDict[tuple[str, str], tuple[float, dict, str]] = OrderedDict()
_history_cache: dict = {}


def _number(value, *, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _options_identity(options) -> str:
    # Only an opaque digest is saved; keys, endpoints, model names and personal
    # instruction text never appear in this sidecar or the aggregate projection.
    values = options.model_dump(mode="json", exclude={"llm_api_key", "use_saved_connection"})
    values["llm_base_url"] = options.llm_base_url or config.LLM_BASE_URL
    values["llm_model"] = options.llm_model or config.LLM_MODEL
    return _digest(values)


def _input_identity(task) -> str:
    # Detect changed inputs in a live attempt without exposing private source
    # identifiers or requiring unrelated tasks to contain the same media.
    return _digest([task.source_type, task.media_integrity.duration, task.media_integrity.sha256,
                    task.active_video.duration if task.active_video else None, task.learning_range,
                    task.source_identity.resource_fingerprint, task.source_identity.media_sha256])


def _context(task, options, transcript, duration, route):
    if route not in ROUTES or transcript.source not in SOURCES or not transcript.segments or transcript.warning:
        return None
    # Legacy/unresolved options can be resolved to a saved connection later by
    # the summarizer. Do not label those runs with configuration defaults that
    # may differ from the model actually selected at execution time.
    if not options.llm_base_url or not options.llm_model:
        return None
    if not _number(duration, positive=True) or duration > MAX_DURATION_SECONDS:
        return None
    endpoint = urlsplit(options.llm_base_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        return None
    device = config.DEFAULT_WHISPER_DEVICE
    compute = config.DEFAULT_WHISPER_COMPUTE_TYPE
    if device not in {"cpu", "cuda"} or compute not in {"int8", "int8_float16", "int8_float32", "float16", "float32", "bfloat16"}:
        return None  # "auto" does not identify the selected execution mode.
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "route": route,
        "subtitle_source": transcript.source,
        "device_mode": device,
        "compute_type": compute,
        "media_seconds": float(duration),
        "options_identity": _options_identity(options),
        "task_options_identity": _options_identity(task.options),
        "source_type": task.source_type,
    }


def _read(path: Path):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("linked_estimate_evidence")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("oversized_estimate_evidence")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("attempts"), list):
        raise ValueError("invalid_estimate_evidence")
    return value


def _attempt(metrics, attempt_id):
    if not attempt_id or metrics.get("schema_version") != 2 or metrics.get("current_attempt_id") != attempt_id:
        return None
    matches = [value for value in metrics.get("attempts", []) if isinstance(value, dict) and value.get("attempt_id") == attempt_id]
    return matches[0] if len(matches) == 1 else None


def begin_remaining_measurement(task_id, attempt_id, options, transcript, duration, *, route):
    """Called once at an explicit work boundary, with the actual selected options."""
    try:
        with storage._lock:
            metrics = storage.read_json(task_id, "pipeline_metrics.json", {})
            attempt = _attempt(metrics, attempt_id)
            if not attempt or attempt.get("status") != "running":
                return
            task = storage.get_task(task_id)
            context = _context(task, options, transcript, duration, route)
            if not context or task.cancel_requested:
                return
            path = storage.TASK_DIR / task_id / FILENAME
            evidence = _read(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "attempts": []}
            if any(item.get("attempt_id") == attempt_id for item in evidence["attempts"]):
                return  # A duplicate callback or restart cannot reset elapsed time.
            identity = _input_identity(task)
            entry = {"attempt_id": attempt_id, "status": "running", "context": context, "input_identity": identity,
                     "started_at_unix_ms": round(time.time() * 1000)}
            evidence["attempts"] = [*evidence["attempts"], entry][-20:]
            storage.write_json(task_id, FILENAME, evidence)
            key = (str(storage.TASK_DIR / task_id), attempt_id)
            _active[key] = (time.monotonic(), context, identity)
            while len(_active) > MAX_TASKS:
                _active.popitem(last=False)
    except Exception:
        pass  # An optional measurement must not affect processing or publication.


def finish_remaining_measurement(task_id, attempt_id, status):
    try:
        with storage._lock:
            key = (str(storage.TASK_DIR / task_id), attempt_id)
            clock = _active.pop(key, None)
            if clock is None:
                return
            metrics = storage.read_json(task_id, "pipeline_metrics.json", {})
            attempt = _attempt(metrics, attempt_id)
            task = storage.get_task(task_id)
            if not attempt:
                return
            evidence = _read(storage.TASK_DIR / task_id / FILENAME)
            entry = next(item for item in evidence["attempts"] if item.get("attempt_id") == attempt_id)
            elapsed = time.monotonic() - clock[0]
            stages = attempt.get("stages") or {}
            valid = (status == "completed" and attempt.get("status") == "completed" and task.status == "success"
                     and not task.cancel_requested and not task.error_code and _number(elapsed, positive=True)
                     and elapsed <= MAX_DURATION_SECONDS and entry.get("context") == clock[1]
                     and entry.get("input_identity") == clock[2] == _input_identity(task)
                     and _options_identity(task.options) == clock[1]["task_options_identity"]
                     and all(isinstance(stage, dict) and stage.get("status") in {"completed", "skipped"}
                             and stage.get("attempt_id") == attempt_id
                             and ("duration_ms" not in stage or _number(stage["duration_ms"]))
                             for stage in stages.values())
                     and all(isinstance(stages.get(name), dict) and stages[name].get("status") == "completed"
                             and _number(stages[name].get("duration_ms")) for name in ("summary", "verify")))
            entry["status"] = "completed" if valid else "unusable"
            entry["finished_at_unix_ms"] = round(time.time() * 1000)
            if valid:
                entry["duration_seconds"] = elapsed
            storage.write_json(task_id, FILENAME, evidence)
            _history_cache.clear()
    except Exception:
        pass


def _history(root, now):
    cache_key = str(root)
    cached = _history_cache.get(cache_key)
    if cached and 0 <= time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    records = []
    # Bound enumeration and file reads, including damaged/imported task stores.
    with os.scandir(root) as entries:
        for index, directory in enumerate(entries):
            if index >= MAX_TASKS:
                break
            if not directory.is_dir(follow_symlinks=False):
                continue
            path = Path(directory.path) / FILENAME
            try:
                evidence = _read(path)
            except (OSError, ValueError, TypeError):
                continue
            records.append((directory.name, evidence["attempts"][-20:]))
    _history_cache.clear()  # Only one configured task store, never unbounded roots.
    _history_cache[cache_key] = (time.monotonic(), records)
    return records


def _compatible(context, wanted):
    if not isinstance(context, dict) or set(context) != set(wanted):
        return False
    duration = context.get("media_seconds")
    return (_number(duration, positive=True) and 0.8 <= duration / wanted["media_seconds"] <= 1.25
            and all(context[key] == value for key, value in wanted.items() if key != "media_seconds"))


def _samples(records, task_id, context, now):
    samples = []
    for history_task, attempts in records:
        if history_task == task_id:
            continue  # Repeated attempts at this task cannot train its own estimate.
        eligible = []
        for entry in attempts:
            if not isinstance(entry, dict) or entry.get("status") != "completed" or not _compatible(entry.get("context"), context):
                continue
            started, finished, duration = (entry.get(key) for key in ("started_at_unix_ms", "finished_at_unix_ms", "duration_seconds"))
            if not all(_number(value, positive=True) for value in (started, finished, duration)):
                continue
            if not started <= finished <= now or now - finished > MAX_AGE_SECONDS * 1000 or duration > MAX_DURATION_SECONDS:
                continue
            eligible.append((finished, duration))
        if eligible:
            samples.append(max(eligible))  # At most one success per independent task.
    return [duration for _, duration in sorted(samples, reverse=True)[:MAX_SAMPLES]]


def duration_estimate(task):
    """Aggregate only; no history IDs, options, source paths or model details."""
    now = round(time.time() * 1000)
    result = {"schema_version": SCHEMA_VERSION, "scope": SCOPE, "status": "unknown", "reason": "context_unavailable",
              "duration_seconds_range": None, "remaining_seconds_range": None, "sample_count": 0,
              "uncertainty": "unmeasured", "observed_at_unix_ms": now}
    def unknown(reason):
        result["reason"] = reason
        return result
    if task.status != "running" or task.awaiting_confirmation or task.cancel_requested:
        return unknown("inactive_attempt")
    try:
        with storage._lock:
            metrics = storage.read_json(task.id, "pipeline_metrics.json", {})
            attempt_id = metrics.get("current_attempt_id")
            attempt = _attempt(metrics, attempt_id)
            if not attempt or attempt.get("status") != "running":
                return unknown("attempt_unavailable")
            path = storage.TASK_DIR / task.id / FILENAME
            if not path.exists():
                return result
            evidence = _read(path)
            entry = next((item for item in evidence["attempts"] if item.get("attempt_id") == attempt_id), None)
            if not entry or entry.get("status") != "running":
                return result
            clock = _active.get((str(storage.TASK_DIR / task.id), attempt_id))
            if clock is None:
                return unknown("live_clock_unavailable")
            context = entry.get("context")
            if (context != clock[1] or context["task_options_identity"] != _options_identity(task.options)
                    or entry.get("input_identity") != clock[2] or _input_identity(task) != clock[2]):
                return unknown("context_changed")
            if context["device_mode"] != config.DEFAULT_WHISPER_DEVICE or context["compute_type"] != config.DEFAULT_WHISPER_COMPUTE_TYPE:
                return unknown("context_changed")
            elapsed = time.monotonic() - clock[0]
            if not _number(elapsed) or elapsed > MAX_DURATION_SECONDS:
                return unknown("invalid_elapsed_time")
            samples = _samples(_history(storage.TASK_DIR, now), task.id, context, now)
            result["sample_count"] = len(samples)
            if len(samples) < MIN_SAMPLES:
                return unknown("insufficient_compatible_history")
            # An empirical envelope with engineering padding, NOT a confidence
            # interval or a deadline. Nearby lengths are not linearly scaled.
            lower, upper = math.floor(min(samples) * 0.75), math.ceil(max(samples) * 1.25)
            result.update(attempt_id=attempt_id, duration_seconds_range=[lower, upper],
                          elapsed_seconds=round(elapsed, 1), uncertainty="empirical_not_probability",
                          status="estimated", reason="compatible_local_history")
            if elapsed >= upper:
                result.update(status="overrun", reason="historical_upper_bound_exceeded")
            else:
                result["remaining_seconds_range"] = [max(0, math.floor(lower - elapsed)), math.ceil(upper - elapsed)]
            return result
    except Exception:
        return unknown("evidence_unavailable")
