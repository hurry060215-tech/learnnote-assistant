"""Optional measurements of a whole current attempt, never stage-time sums.

A process-random cohort deliberately makes copied or restarted history ineligible
without collecting a machine identifier. Older after-transcript evidence remains
independent and is never backfilled into this scope.
"""
from __future__ import annotations

from collections import OrderedDict
import math
from pathlib import Path
import time
import weakref
from uuid import uuid4
from types import SimpleNamespace

from . import config, storage
from .duration_estimates import (
    MAX_DURATION_SECONDS, MAX_TASKS, MIN_SAMPLES,
    _attempt, _context, _digest, _input_identity,
    _number, _options_identity, _read as _read_evidence, _samples, duration_estimate,
)

SCHEMA_VERSION = 1
SCOPE = "current_processing_attempt"
FILENAME = "whole_attempt_duration_evidence.json"
PROCESS_COHORT = uuid4().hex
ENTRY_ROUTES = {"current_page_media", "subtitle_only", "saved_transcript", "local_media"}
_active: OrderedDict = OrderedDict()
_history_cache: dict = {}
_successful_tasks: OrderedDict = OrderedDict()


def task_duration_estimates(task):
    """Keep the two measured scopes explicit at the task API boundary."""
    return {"duration_estimate": duration_estimate(task),
            "whole_task_duration_estimate": whole_task_duration_estimate(task)}


def _read(path):
    evidence = _read_evidence(path)
    if type(evidence["schema_version"]) is not int:
        raise ValueError("invalid_whole_evidence_version")
    return evidence


def _stable_input(task):
    # Media hashes/duration become available during normal acquisition. Only
    # compare fields that must stay fixed before that boundary is reached.
    return _digest([task.source_type, task.source_identity.resource_fingerprint, task.learning_range])


def _device():
    return (config.DEFAULT_WHISPER_DEVICE, config.DEFAULT_WHISPER_COMPUTE_TYPE)


def begin_whole_measurement(task_id, attempt_id, *, started_at, queue_interval, entry_route, retry, options=None):
    """Capture before acquisition. A queue boundary must come from this dispatch."""
    try:
        with storage._lock:
            if entry_route not in ENTRY_ROUTES or not _number(started_at):
                return
            task = storage.get_task(task_id)
            if task.cancel_requested or task.learning_range or not _attempt(storage.read_json(task_id, "pipeline_metrics.json", {}), attempt_id):
                return
            boundary, origin, start = "attempt_start", "direct", started_at
            if queue_interval is not None:
                queued, dispatched, origin = queue_interval
                if (not all(_number(value) for value in (queued, dispatched))
                        or not queued <= dispatched <= started_at or origin not in {"queued", "recovery"}):
                    return
                start, boundary = queued, "accepted_enqueue"
            path = storage.TASK_DIR / task_id / FILENAME
            if path.is_symlink() or path.parent.is_symlink():
                return
            evidence = _read(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "attempts": []}
            if any(not isinstance(item, dict) for item in evidence["attempts"]):
                return
            if any(item.get("attempt_id") == attempt_id for item in evidence["attempts"]):
                return
            now = time.monotonic()
            if not _number(now - start) or now - start > MAX_DURATION_SECONDS:
                return
            selected = options if options is not None else task.options
            state = {"start": start, "boundary": boundary, "entry_route": entry_route,
                     "dispatch_origin": origin, "attempt_kind": "retry" if retry else "fresh",
                     "task_options_identity": _options_identity(task.options), "stable_input": _stable_input(task),
                     "selected_options_identity": _options_identity(selected),
                     "text_options_identity": _options_identity(selected.model_copy(update={"visual_understanding": False})),
                     "device": _device(), "task_capability": _capability(task.options), "context": None, "input_identity": None, "bound": False}
            entry = {"attempt_id": attempt_id, "status": "running", "boundary": boundary,
                     "started_at_unix_ms": round((time.time() - (now - start)) * 1000)}
            state["started_at_unix_ms"] = entry["started_at_unix_ms"]
            evidence["attempts"] = [*evidence["attempts"], entry][-20:]
            storage.write_json(task_id, FILENAME, evidence)
            key = (str(storage.TASK_DIR / task_id), attempt_id)
            # Starting a new attempt also discards any abandoned live clock.
            for previous in list(_active):
                if previous[0] == key[0]:
                    _active.pop(previous, None)
            _active[key] = state
            while len(_active) > MAX_TASKS:
                _active.popitem(last=False)
    except Exception:
        pass


def _capability(options):
    if not options.llm_base_url or not options.llm_model:
        return None
    if options.local_ocr:
        return None  # OCR cache/runtime selection is not measured by this contract.
    if not options.visual_understanding:
        return "configured_text"
    from .model_capabilities import model_description
    from .summarizer import llm_provider_name
    description = model_description(llm_provider_name(options.llm_base_url), options.llm_base_url, options.llm_model)
    if description.get("vision") is not True:
        return None
    return _digest(description)


def _prefix(attempt):
    stages = attempt.get("stages")
    if not isinstance(stages, dict) or "transcript" not in stages or "summary" in stages or "verify" in stages:
        return None
    for stage in stages.values():
        if (not isinstance(stage, dict) or stage.get("attempt_id") != attempt["attempt_id"]
                or stage.get("status") not in {"completed", "skipped"}
                or ("duration_ms" in stage and not _number(stage["duration_ms"]))
                or (stage["status"] == "completed" and not _number(stage.get("duration_ms")))):
            return None
    return {name: stage["status"] for name, stage in sorted(stages.items())}


def bind_whole_measurement(task_id, attempt_id, options, transcript, duration, *, route,
                           transcript_reused=False, normalization_reused=False):
    """Bind actual provenance once, at the existing transcript-ready boundary."""
    try:
        with storage._lock:
            state = _active.get((str(storage.TASK_DIR / task_id), attempt_id))
            if not state or state["bound"]:
                return
            state["bound"] = True  # A later callback cannot invent a new boundary.
            task = storage.get_task(task_id)
            attempt = _attempt(storage.read_json(task_id, "pipeline_metrics.json", {}), attempt_id)
            context = _context(task, options, transcript, duration, route)
            capability = _capability(options) if context else None
            prefix = _prefix(attempt) if attempt and attempt.get("status") == "running" else None
            if (not context or not capability or prefix is None or task.cancel_requested
                    or state["task_options_identity"] != _options_identity(task.options)
                    or state["stable_input"] != _stable_input(task) or state["device"] != _device()
                    or state["task_capability"] != _capability(task.options)
                    or _options_identity(options) != state["text_options_identity" if route == "transcript_to_note" else "selected_options_identity"]
                    or type(transcript_reused) is not bool or type(normalization_reused) is not bool):
                return
            if options.visual_understanding and any((storage.TASK_DIR / task_id / name).exists()
                                                    for name in ("vision_cache", "frames/frame_cache.json")):
                return  # Future visual cache hits are not known at transcript readiness.
            context.update(scope=SCOPE, process_cohort=PROCESS_COHORT, boundary=state["boundary"],
                           entry_route=state["entry_route"], dispatch_origin=state["dispatch_origin"],
                           attempt_kind=state["attempt_kind"], prefix=prefix, capability=capability,
                           transcript_reused=transcript_reused, normalization_reused=normalization_reused)
            evidence = _read(storage.TASK_DIR / task_id / FILENAME)
            matches = [item for item in evidence["attempts"] if isinstance(item, dict) and item.get("attempt_id") == attempt_id]
            if len(matches) != 1 or matches[0].get("status") != "running" or "context" in matches[0]:
                return
            identity = _input_identity(task)
            matches[0].update(context=context, input_identity=identity)
            storage.write_json(task_id, FILENAME, evidence)
            # Observe live option mutations without extending the lifetime of
            # the provider's key-bearing options after processing stops.
            state.update(context=context, input_identity=identity, effective_options_ref=weakref.ref(options), options=SimpleNamespace(
                llm_base_url=options.llm_base_url, llm_model=options.llm_model,
                visual_understanding=options.visual_understanding, local_ocr=options.local_ocr))
    except Exception:
        pass


def _live_valid(task, state, entry):
    context = state["context"]
    effective = state.get("effective_options_ref")
    effective = effective() if effective is not None else None
    return (context is not None and entry.get("context") == context
            and entry.get("started_at_unix_ms") == state["started_at_unix_ms"]
            and entry.get("boundary") == state["boundary"]
            and context["process_cohort"] == PROCESS_COHORT and state["device"] == _device()
            and _options_identity(task.options) == state["task_options_identity"]
            and state["task_capability"] == _capability(task.options)
            and effective is not None and _options_identity(effective) == context["options_identity"]
            and _stable_input(task) == state["stable_input"]
            and entry.get("input_identity") == state["input_identity"] == _input_identity(task)
            and _capability(state["options"]) == context["capability"])


def _prefix_unchanged(attempt, context):
    stages = attempt.get("stages")
    return (isinstance(stages, dict) and all(
        isinstance(stages.get(name), dict) and stages[name].get("status") == status
        and stages[name].get("attempt_id") == attempt["attempt_id"]
        and ("duration_ms" not in stages[name] or _number(stages[name]["duration_ms"]))
        and (status == "skipped" or _number(stages[name].get("duration_ms")))
        for name, status in context["prefix"].items()))


def finish_whole_measurement(task_id, attempt_id, status):
    try:
        with storage._lock:
            state = _active.pop((str(storage.TASK_DIR / task_id), attempt_id), None)
            if not state:
                return
            task = storage.get_task(task_id)
            attempt = _attempt(storage.read_json(task_id, "pipeline_metrics.json", {}), attempt_id)
            if not attempt:
                return
            evidence = _read(storage.TASK_DIR / task_id / FILENAME)
            matches = [item for item in evidence["attempts"] if isinstance(item, dict) and item.get("attempt_id") == attempt_id]
            if len(matches) != 1:
                return
            entry = matches[0]
            elapsed = time.monotonic() - state["start"]
            stages = attempt.get("stages") or {}
            events = task.summary_diagnostics.get("llm_events", [])
            valid = (status == "completed" and attempt.get("status") == "completed" and task.status == "success"
                     and not task.cancel_requested and not task.error_code and not task.summary_warning
                     and task.summary_source == ("vision-llm" if state.get("options") and state["options"].visual_understanding else "text-llm")
                     and _live_valid(task, state, entry) and _prefix_unchanged(attempt, state["context"])
                     and _number(elapsed, positive=True) and elapsed <= MAX_DURATION_SECONDS
                     and isinstance(events, list) and all(isinstance(event, dict) and event.get("code") in {"ok", "success"}
                                                        and event.get("cache") != "hit" for event in events)
                     and all(isinstance(stage, dict) and stage.get("status") in {"completed", "skipped"}
                             and stage.get("attempt_id") == attempt_id
                             and ("duration_ms" not in stage or _number(stage["duration_ms"]))
                             and (stage["status"] == "skipped" or _number(stage.get("duration_ms")))
                             and not stage.get("cache_hit_count") for stage in stages.values())
                     and all(isinstance(stages.get(name), dict) and stages[name].get("status") == "completed"
                             and _number(stages[name].get("duration_ms")) for name in ("summary", "verify")))
            entry.update(status="completed" if valid else "unusable", finished_at_unix_ms=round(time.time() * 1000))
            if valid:
                entry["duration_seconds"] = elapsed
            storage.write_json(task_id, FILENAME, evidence)
            if valid:
                key = (str(storage.TASK_DIR), task_id)
                _successful_tasks[key] = None
                _successful_tasks.move_to_end(key)
                while len(_successful_tasks) > MAX_TASKS:
                    _successful_tasks.popitem(last=False)
            _history_cache.clear()
    except Exception:
        pass


def _history(root):
    cached = _history_cache.get(str(root))
    if cached and 0 <= time.monotonic() - cached[0] < 30:
        return cached[1]
    records = []
    # This cohort can contain only successes recorded by this process. A bounded
    # registry avoids old task folders crowding every eligible sample out.
    for registered_root, task_id in reversed(_successful_tasks):
        if registered_root != str(root):
            continue
        if len(records) >= MAX_TASKS:
            break
        try:
            evidence = _read(Path(root) / task_id / FILENAME)
        except (OSError, ValueError, TypeError):
            continue
        records.append((task_id, evidence["attempts"][-20:]))
    _history_cache.clear()
    _history_cache[str(root)] = (time.monotonic(), records)
    return records


def whole_task_duration_estimate(task):
    """Read-only aggregate. Never exposes source/configuration/history IDs."""
    now = round(time.time() * 1000)
    result = {"schema_version": SCHEMA_VERSION, "scope": SCOPE, "boundary": None,
              "cohort": "current_backend_process", "status": "unknown", "reason": "context_unavailable",
              "duration_seconds_range": None, "remaining_seconds_range": None,
              "sample_count": 0, "uncertainty": "unmeasured", "observed_at_unix_ms": now}
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
            matches = [item for item in evidence["attempts"] if isinstance(item, dict) and item.get("attempt_id") == attempt_id]
            if len(matches) != 1 or matches[0].get("status") != "running":
                return unknown("evidence_unavailable")
            entry = matches[0]
            state = _active.get((str(storage.TASK_DIR / task.id), attempt_id))
            if not state:
                return unknown("live_clock_unavailable")
            result["boundary"] = state["boundary"]
            if state["context"] is None:
                return result
            if not _live_valid(task, state, entry) or not _prefix_unchanged(attempt, state["context"]):
                return unknown("context_changed")
            elapsed = time.monotonic() - state["start"]
            if not _number(elapsed) or elapsed > MAX_DURATION_SECONDS:
                return unknown("invalid_elapsed_time")
            samples = _samples(_history(storage.TASK_DIR), task.id, state["context"], now)
            result["sample_count"] = len(samples)
            if len(samples) < MIN_SAMPLES:
                return unknown("insufficient_compatible_history")
            lower, upper = math.floor(min(samples) * .75), math.ceil(max(samples) * 1.25)
            result.update(attempt_id=attempt_id, status="estimated", reason="compatible_local_history",
                          duration_seconds_range=[lower, upper], elapsed_seconds=round(elapsed, 1),
                          uncertainty="empirical_not_probability")
            if elapsed >= upper:
                result.update(status="overrun", reason="historical_upper_bound_exceeded")
            else:
                result["remaining_seconds_range"] = [max(0, math.floor(lower - elapsed)), math.ceil(upper - elapsed)]
            return result
    except Exception:
        return unknown("evidence_unavailable")
