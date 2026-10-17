"""I/O-free diagnostic fields shared by content-free and document exports."""

STATUSES = frozenset("queued running cancelling cancelled success failed".split())


PHASES = frozenset("queued detecting downloading processing_video transcribing extracting_frames summarizing completed cancelling cancelled failed".split())


SUMMARY_SOURCES = frozenset("text-llm vision-llm page-text-llm local-template transcript-draft partial-draft offline-fixture subtitle-extract screen-ocr-extract".split())


FAILURES = frozenset("summary_unavailable transcript_review_required note_quality_failed asr_failed asr_unavailable content_mismatch download_forbidden download_failed auth_required network_tls_error unsupported_manifest no_media_found drm_or_encrypted unsupported_blob incomplete_media media_invalid media_probe_failed ffmpeg_missing ffprobe_missing disk_full resource_budget_exceeded processing_failed interrupted cancelled missing_api_key".split())


QUALITY_CODES = frozenset("mojibake_detected transcript_review_required invalid_title_count heading_level_jump note_too_short missing_visible_evidence internal_prompt_leak duplicate_content long_paragraph".split())


def choice(value, allowed):
    return value if isinstance(value, str) and value in allowed else None


def mapping(value):
    return value if isinstance(value, dict) else {}


def recorded(obj, key):
    fields = getattr(obj, "model_fields_set", None)
    return getattr(obj, key, None) if fields is None or key in fields else None


def summary_subset(task):
    """Pure subset shared with opt-in document exports; never opens artifacts."""
    diagnostics = mapping(getattr(task, "summary_diagnostics", None))
    quality = mapping(diagnostics.get("note_quality"))
    issues = quality.get("issues")
    return {"status": choice(recorded(task, "status"), STATUSES),
            "phase": choice(recorded(task, "phase"), PHASES),
            "summary_source": choice(getattr(task, "summary_source", None), SUMMARY_SOURCES),
            "failure_code": choice(getattr(task, "error_code", None), FAILURES),
            "structure_issue_codes": sorted({code for row in issues[:20] if (code := choice(mapping(row).get("code"), QUALITY_CODES))}) if isinstance(issues, list) else []}


def render_summary(task):
    value = summary_subset(task)
    labels = {"status": "任务状态", "phase": "处理阶段", "summary_source": "总结路线", "failure_code": "错误代码", "structure_issue_codes": "结构检查"}
    return "## 诊断摘要\n\n" + "\n".join(f"- {labels[key]}：{display(item)}" for key, item in value.items())


def display(value):
    if value is None:
        return "未知（未记录或已省略）"
    if type(value) is bool:
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) or "未记录"
    return str(value)
