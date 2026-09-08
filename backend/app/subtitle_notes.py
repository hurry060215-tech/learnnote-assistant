"""Summarize saved timed text without downloading or retranscribing media."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .models import EvidenceCoverage, EvidenceGate, TranscriptResult
from .note_document import build_note_document, normalize_note_markdown
from .pipeline_progress import record_stage_duration, write_progressive_draft
from .storage import get_task, task_dir, update_task, write_json
from .summary_outcome import has_generated_summary, safe_summary_events, safe_summary_text, summary_failure_message


def finish_transcript_note(task_id: str, title: str, page_url: str, transcript: TranscriptResult, options,
                           *, duration: float, media_skipped: bool, summarize: Callable,
                           build_diagnostics: Callable, check_cancel: Callable) -> None:
    check_cancel(task_id)
    work_dir = task_dir(task_id)
    previous = get_task(task_id)
    if not previous.note_path or not Path(previous.note_path).is_file():
        draft = write_progressive_draft(task_id, title, transcript)
        if draft:
            update_task(task_id, note_path=str(draft), summary_source="transcript-draft")
    options = options.model_copy(update={"visual_understanding": False})
    update_task(task_id, status="running", phase="summarizing", progress=78,
                message="字幕已就绪，正在提炼要点、章节和结论")
    started = time.monotonic()
    stage_status = "failed"
    try:
        result = summarize(title, transcript, [], options, page_url, "")
        check_cancel(task_id)
        note, source, warning = result[:3]
        events = safe_summary_events(result[3] if len(result) > 3 else [])
        warning = safe_summary_text(warning)
        generated = has_generated_summary(source)
        stage_status = "completed" if generated else "failed"
        span = max(0.0, max((s.end for s in transcript.segments), default=0) - min((s.start for s in transcript.segments), default=0))
        ratio = min(1.0, span / duration) if duration > 0 else 0.0
        coverage = EvidenceCoverage(status="ready", can_summarize=True, transcript_source=transcript.source,
            transcript_char_count=len(transcript.full_text), transcript_covered_seconds=span,
            transcript_coverage_ratio=ratio, platform_subtitle_coverage_ratio=ratio if "subtitle" in transcript.source else 0,
            gates=[EvidenceGate(name="transcript", passed=True, status="passed", detail="使用已保存的带时间文本"),
                   EvidenceGate(name="media", passed=False, status="skipped", detail="本次仅根据文字总结，无需下载媒体"),
                   EvidenceGate(name="visual", passed=False, status="skipped", detail="本次未进行画面分析")])
        diagnostics = build_diagnostics(task_id=task_id, title=title, page_url=page_url, options=options,
            grids=[], visual_windows=[], summary_source=source, summary_warning=warning, llm_events=events)
        diagnostics.update({"source_kind": "subtitle_only" if media_skipped else "saved_transcript",
            "source_quality": "high", "evidence_quality": "subtitle" if "subtitle" in transcript.source else "transcript",
            "transcript_source": transcript.source, "video_evidence": "not_downloaded" if media_skipped else "saved_media",
            "can_claim_video_content": False, "subtitle_coverage_ratio": ratio,
            "browser_subtitle_count": len(transcript.segments) if transcript.source == "browser-subtitle" else 0,
            "media_pipeline_skipped": True, "asr_skipped": True, "visual_pipeline_skipped": True,
            "summary_generated": generated})
        coverage_path = write_json(task_id, "evidence_coverage.json", coverage.model_dump(mode="json"))
        fields = dict(summary_source=source, summary_warning=warning,
            evidence_coverage=coverage, evidence_coverage_path=str(coverage_path))
        if not generated:
            detail = summary_failure_message(warning, events)
            diagnostics["summary_warning"] = detail
            diag_path = write_json(task_id, "summary_diagnostics.json", diagnostics)
            update_task(task_id, status="failed", phase="failed", progress=100,
                message=detail, error_code="summary_unavailable", error_detail=detail,
                checkpoint="transcript_ready", summary_diagnostics=diagnostics,
                summary_diagnostics_path=str(diag_path), **{**fields, "summary_warning": detail})
            return
        source_label = "浏览器平台字幕" if transcript.source == "browser-subtitle" else "平台字幕" if "subtitle" in transcript.source else "已保存的音频转写"
        provenance = f"> 证据来源：{source_label}；本次未分析画面。"
        if provenance not in note:
            first, sep, rest = note.lstrip().partition("\n")
            note = f"{first}\n\n{provenance}\n\n{rest.lstrip()}" if first.startswith("# ") and sep else f"{provenance}\n\n{note}"
        normalized = normalize_note_markdown(title, note)
        quality_path = write_json(task_id, "note_quality.json", normalized.report)
        if normalized.report.get("blocking"):
            (work_dir / "note.quarantine.md").write_text(note, encoding="utf-8")
            stage_status = "failed"
            update_task(task_id, status="failed", phase="failed", progress=100,
                message="总结质量检查未通过；字幕已保留，可以重新总结。", error_code="note_quality_failed",
                error_detail="疑似乱码或无效标题结构，原始输出已隔离。", checkpoint="transcript_ready")
            return
        check_cancel(task_id)
        note_path = work_dir / "note.md"
        note_path.write_text(normalized.markdown, encoding="utf-8")
        doc_path = write_json(task_id, "note_document.json", build_note_document(title, normalized.markdown))
        diagnostics.update({"note_quality_path": str(quality_path), "note_quality": normalized.report, "note_document_path": str(doc_path)})
        diag_path = write_json(task_id, "summary_diagnostics.json", diagnostics)
        update_task(task_id, status="success", phase="completed", progress=100,
            message="AI 总结已完成，字幕和原始时间点已保留", error_code="", error_detail="",
            checkpoint="note_ready", note_path=str(note_path), summary_diagnostics=diagnostics,
            summary_diagnostics_path=str(diag_path), **fields)
    finally:
        record_stage_duration(task_id, "summary", started, status=stage_status)
