"""Read-only, bounded support reports. Values are projected, never scrubbed prose."""
from __future__ import annotations

import json
import math
import re

from . import APP_VERSION
from .diagnostic_fields import (STATUSES, PHASES, choice, mapping, recorded,
                                summary_subset, display)

SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 256 * 1024
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
MODES = frozenset("video subtitle_only page_text download_only local rerun_from_media screen_subtitles".split())
SOURCES = frozenset("browser-subtitle page-subtitle embedded-subtitle faster-whisper openai-compatible-asr groq-asr screen-ocr selected-range-source-subtitle".split())
ASR_METHODS = frozenset("faster-whisper openai openai-compatible openai-compatible-asr groq groq-asr".split())
ASR_MODELS = frozenset("tiny base small medium large large-v2 large-v3 whisper-1 whisper-large-v3 whisper-large-v3-turbo".split())
# Exact public catalog names only. A custom deployment name may identify a user.
MODELS = frozenset("gpt-4.1-mini gpt-4.1 gpt-4o gpt-4o-mini gemini-3.5-flash qwen-vl-max deepseek-flash deepseek-v4-flash deepseek-v4-flash-vision-exp deepseek-v4-pro deepseek-chat deepseek-reasoner kimi-k2.6 mimo-v2.5 glm-5v-turbo doubao-seed-2-0-lite-260215 MiniMax-M2.7 ernie-4.5-8k-preview openrouter/auto qwen/qwen3.8-27b meta-llama/llama-4-scout-17b-16e-instruct".split())
PROVIDERS = frozenset("openai groq gemini dashscope deepseek kimi xiaomi zhipu doubao minimax qianfan openrouter siliconflow local-openai-compatible openai-compatible".split())
STAGES = ("queue", "subtitle_probe", "download", "media", "transcript", "frames", "vision", "merge", "verify", "visual", "summary")
STAGE_STATUSES = frozenset("completed failed cancelled skipped".split())
EVENT_STAGES = frozenset("configuration client_import client_init grounding_repair grounding_validation vision_batch vision_cache vision_merge text_summary summary provider_compatibility".split())
REQUEST_STAGES = frozenset("text_summary vision_merge vision_batch grounding_repair".split())
EVENT_CODES = frozenset("ok success cache_hit api_error mojibake_blocked missing_api_key missing_openai_sdk client_init_failed repair_required repaired partial_recovery rejected llm_unavailable offline_fixture unclassified partial_vision_failure provider_error".split())
ISSUES = frozenset("empty_note duration_mismatch unsupported_quantity unsupported_terms unsupported_example_section empty_repair".split())
REPAIRS = frozenset("required repaired partial_recovery rejected api_error".split())
ERROR_CATEGORIES = frozenset([f"HTTP {status}" for status in (400, 401, 403, 404, 408, 413, 422, 429, 500, 502, 503, 504)] + ["insufficient_quota", "timeout", "vision_input_rejected", "authentication_failed", "provider_error"])
LIMITS = [
    "未记录或无法确认的数据为 null（未知），不代表零、成功或未发生。",
    "当前运行版本不代表历史任务运行版本；未记录构建修订，不能据此确认是否包含某次修复。",
    "阶段时长是已记录的单次墙钟区间，可能重叠；不相加，不用预计耗时补齐。",
    "模型事件最多保留 20 条；阶段尝试最多保留最近 20 次已记录尝试，position 仅为本报告内顺序，不是原始尝试编号或重试总数。诊断不是完整请求台账，任务请求总数、用量和费用未知。",
    "配置的转写方式与模型来自保存的任务选项，不证明当时实际执行；未保存的默认值不补作历史事实。",
    "来源检查不是语义核验或事实正确性证明；保存字幕可供核对，不保证字幕准确。",
    "已省略标题、原文、笔记、提示词、错误原文、网址、端点、路径、凭据及账户或设备标识；自定义名称也不导出。",
    "仅供用户预览后保存到本地，不会自动上传或发送。",
]


def number(value, maximum=1_000_000):
    return value if type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value) else None


def integer(value, maximum=1_000_000):
    return value if type(value) is int and 0 <= value <= maximum else None


def project_events(value):
    if not isinstance(value, list):
        return []
    retained = value if len(value) <= 20 else value[:18] + value[-2:]
    result = []
    for raw in retained:
        if not isinstance(raw, dict):
            continue
        row = {"stage": choice(raw.get("stage"), EVENT_STAGES), "code": choice(raw.get("code"), EVENT_CODES)}
        for key, allowed in (("request_stage", REQUEST_STAGES), ("repair_outcome", REPAIRS), ("cache", {"hit", "miss"}),
                             ("original_code", {"unsupported_parameter"}), ("parameter", {"temperature"}),
                             ("retry_outcome", {"success", "failed", "cancelled"})):
            if (value := choice(raw.get(key), allowed)) is not None:
                row[key] = value
        if (category := choice(raw.get("error_category", raw.get("message")), ERROR_CATEGORIES)) is not None:
            row["error_category"] = category
        for key in ("batch", "issue_count", "omitted_passages"):
            if (value := integer(raw.get(key))) is not None:
                row[key] = value
        if (duration := number(raw.get("duration_ms"), 7 * 24 * 3600 * 1000)) is not None:
            row["duration_ms"] = duration
        if type(raw.get("original_status")) is int and raw["original_status"] in {400, 422}:
            row["original_status"] = raw["original_status"]
        issues = raw.get("issue_codes", raw.get("issues"))
        if isinstance(issues, list):
            row["issue_codes"] = sorted({v.split(":", 1)[0] for v in issues[:100] if isinstance(v, str)} & ISSUES)
        count, index, completed = (integer(raw.get(key)) for key in ("chunk_count", "chunk_index", "completed_chunks"))
        if count and index and index <= count:
            row.update(chunk_count=count, chunk_index=index)
            if completed is not None and completed <= count:
                row["completed_chunks"] = completed
        result.append(row)
    return result


def _read_owned(task, filename, *, transcript=False):
    from .task_artifacts import task_artifact_path, task_dir
    from .task_paths import TaskArtifactUnavailable, resolve_task_artifact
    try:
        root = task_dir(task.id).absolute()
        path = task_artifact_path(task, "transcript_path") if transcript else resolve_task_artifact(root, task.id, str(root / filename))
        if path is None:
            return {}, "not_recorded"
        limit = MAX_TRANSCRIPT_BYTES if transcript else MAX_REPORT_BYTES
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            return {}, "unavailable"
        value = json.loads(raw)
        if not isinstance(value, dict):
            return {}, "unavailable"
        return value, "recorded"
    except TaskArtifactUnavailable as exc:
        return {}, "not_recorded" if exc.reason == "missing_destination" else "unavailable"
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {}, "unavailable"


def _timings(task):
    value, availability = _read_owned(task, "pipeline_metrics.json")
    result = {"availability": availability, "attempts": []}
    if availability != "recorded":
        return result
    version = value.get("schema_version")
    if type(version) is not int or version not in {1, 2} or value.get("task_id", task.id) != task.id:
        return {"availability": "unavailable", "attempts": []}
    attempts = value.get("attempts") if version == 2 else [{"stages": value.get("stages")}]
    current = value.get("current_attempt_id")
    if not isinstance(attempts, list):
        return {"availability": "unavailable", "attempts": []}
    for attempt in attempts[-20:]:
        if not isinstance(attempt, dict):
            continue
        identity = attempt.get("attempt_id")
        if version == 2 and (not isinstance(identity, str) or not identity or
                sum(isinstance(row, dict) and row.get("attempt_id") == identity for row in attempts) != 1):
            continue
        stages = mapping(attempt.get("stages"))
        rows = []
        for stage in STAGES:
            saved = mapping(stages.get(stage))
            if not saved:
                continue
            if version == 2 and saved.get("attempt_id") != identity:
                continue
            status = choice(saved.get("status"), STAGE_STATUSES)
            rows.append({"stage": stage, "status": status,
                         "duration_ms": number(saved.get("duration_ms"), 7 * 24 * 3600 * 1000) if status != "skipped" else None})
        result["attempts"].append({"position": len(result["attempts"]) + 1,
            "current": identity == current if version == 2 and isinstance(current, str) and current else None,
            "status": choice(attempt.get("status"), STAGE_STATUSES | {"running"}), "stages": rows})
    return result


def build_report(task):
    diagnostics = mapping(getattr(task, "summary_diagnostics", None))
    transcript, availability = _read_owned(task, "transcript.json", transcript=True)
    # Validate the same saved transcript shape as retry-summary, without retaining text.
    valid = None
    if availability == "recorded":
        from .models import TranscriptResult
        try:
            valid = bool(TranscriptResult.model_validate(transcript).full_text.strip())
        except (ValueError, TypeError):
            valid = False
    observed = choice(transcript.get("source"), SOURCES) if valid else None
    events = project_events(diagnostics.get("llm_events"))
    last_failure = project_events([diagnostics.get("llm_last_failure")])
    grounding = [row for row in events if row["stage"] in {"grounding_validation", "grounding_repair"}]
    extension = getattr(task, "extension_version", "")
    options = recorded(task, "options")
    status = choice(recorded(task, "status"), STATUSES)
    saved_options = getattr(options, "model_fields_set", set()) if "options" in getattr(task, "model_fields_set", set()) else set()
    return {
        "schema_version": SCHEMA_VERSION,
        "versions": {"current_app": APP_VERSION, "task_run_app": None, "build_revision": None,
                     "recorded_extension": extension if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}", extension or "") else None},
        "task": {**summary_subset(task), "mode": choice(recorded(task, "mode"), MODES),
                 "source_type": choice(getattr(task, "source_type", None), {"current_page", "local", "page_text"})},
        "asr": {"configured_method": choice(getattr(options, "transcriber", None), ASR_METHODS) if "transcriber" in saved_options else None,
                "configured_model": choice(getattr(options, "whisper_model", None), ASR_MODELS) if "whisper_model" in saved_options else None,
                "observed_source": observed, "observed_model": None},
        "model": {"recorded_provider": choice(diagnostics.get("llm_provider"), PROVIDERS),
                  "recorded_model": choice(diagnostics.get("llm_model"), MODELS),
                  "failure_stage": choice(diagnostics.get("llm_failure_stage"), EVENT_STAGES),
                  "failure_code": choice(diagnostics.get("llm_failure_code"), EVENT_CODES),
                  "failure_category": choice(diagnostics.get("llm_failure_reason"), ERROR_CATEGORIES),
                  "events": events, "last_failure": last_failure[0] if last_failure else None,
                  "request_count": None, "input_tokens": None, "output_tokens": None, "total_tokens": None, "cost": None},
        "grounding": {"events": grounding, "semantic_verification": "not_established"},
        "timings": _timings(task),
        "resummary": {"transcript_record": availability, "saved_transcript_usable": valid,
                      "text_retry_supported": True if valid and observed in SOURCES - {"screen-ocr"} else None,
                      "task_active": status in {"queued", "running", "cancelling"} if status else None,
                      "requires_text_mode": getattr(options, "content_mode", None) in {"subtitles", "visual"} if "content_mode" in saved_options else None,
                      "requires_media_validation": observed == "screen-ocr" if observed else None,
                      "model_readiness": "not_checked"},
        "limits": list(LIMITS),
    }


def render_markdown(report):
    lines = ["# LearnNote 任务诊断报告", "", "仅包含已记录的类别与数值。保存前请检查；是否分享由你决定。", ""]
    labels = {"versions": "版本", "task": "任务结果", "asr": "转写方式", "model": "模型请求结果", "grounding": "来源检查", "timings": "已记录阶段耗时", "resummary": "复用已保存字幕"}
    names = {"current_app": "当前运行版本", "task_run_app": "任务运行版本", "build_revision": "构建修订", "recorded_extension": "记录的扩展版本",
             "configured_method": "保存配置中的转写方式", "configured_model": "保存配置中的转写模型", "observed_source": "记录的字幕来源", "observed_model": "实际转写模型",
             "recorded_provider": "记录的模型服务类别", "recorded_model": "记录的模型名称", "request_count": "请求总数", "input_tokens": "输入用量", "output_tokens": "输出用量", "total_tokens": "总用量", "cost": "实际费用"}
    for section, label in labels.items():
        lines += ["## " + label, ""]
        for key, value in report[section].items():
            if isinstance(value, (list, dict)) and key not in {"structure_issue_codes"}:
                # All nested values were projected above; no source prose enters this renderer.
                lines += ["### " + key, "", "```json", json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), "```", ""]
            else:
                lines.append(f"- {names.get(key, key)}：{display(value)}")
        lines.append("")
    lines += ["## 使用边界", "", *["- " + value for value in report["limits"]], ""]
    return "\n".join(lines)


def support_members(report):
    """Keep the legacy archive shape, but no legacy report or raw event is copied."""
    events = report["model"]["events"]
    manifest = {"schema_version": SCHEMA_VERSION, "bundle_type": "support-package", "event_count": len(events),
                "event_scope": "retained_summary_diagnostics", "privacy": {key: False for key in
                ("cookies", "authorization", "request_bodies", "signed_urls", "course_content", "source_paths", "identifiers")}}
    audit = "# LearnNote 任务审计摘要\n\n" + json.dumps({"task": report["task"], "grounding": report["grounding"], "resummary": report["resummary"]}, ensure_ascii=False, indent=2, allow_nan=False) + "\n\n" + "\n".join(report["limits"]) + "\n"
    return manifest, events, render_markdown(report), audit
