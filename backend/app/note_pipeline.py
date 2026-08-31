"""Evidence gate, summarization, and final note artifact persistence."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .processor_state import ContentMismatchError
from .note_document import build_note_document, normalize_note_markdown
from .storage import task_dir, update_task, write_json


def finish_note_task(
    task_id: str,
    title: str,
    page_url: str,
    options,
    transcript,
    grids,
    visual_windows,
    frames,
    frame_samples,
    integrity,
    asr_error: str,
    frame_extraction_warning: str,
    page_context: str,
    frame_anchor_timestamps: list[float] | None,
    *,
    has_visual_summary_evidence: Callable,
    calculate_evidence_coverage: Callable,
    evidence_coverage_markdown: Callable,
    summarize_with_diagnostics: Callable,
    build_summary_diagnostics: Callable,
    check_cancel: Callable,
    mark_checkpoint: Callable,
) -> None:
    media_duration = integrity.duration
    if asr_error and not has_visual_summary_evidence(frames, media_duration):
        update_task(
            task_id,
            status="failed",
            phase="failed",
            progress=100,
            message=asr_error,
            error_code="asr_failed",
            error_detail=asr_error,
        )
        return

    evidence_coverage = calculate_evidence_coverage(
        integrity,
        transcript,
        frame_samples,
        visual_enabled=options.visual_understanding,
    )
    evidence_coverage_path = write_json(task_id, "evidence_coverage.json", evidence_coverage.model_dump(mode="json"))
    update_task(task_id, evidence_coverage=evidence_coverage, evidence_coverage_path=str(evidence_coverage_path))
    if not evidence_coverage.can_summarize:
        raise ContentMismatchError(
            "Evidence reliability gate blocked summary generation: "
            + ", ".join(evidence_coverage.blocking_reasons)
        )

    update_task(task_id, phase="summarizing", progress=84, message="正在生成 Markdown 笔记")
    check_cancel(task_id)
    summary_result = summarize_with_diagnostics(title, transcript, grids, options, page_url, page_context)
    check_cancel(task_id)
    if len(summary_result) == 4:
        note, summary_source, summary_warning, llm_events = summary_result
    else:
        note, summary_source, summary_warning = summary_result
        llm_events = []
    evidence_section = evidence_coverage_markdown(integrity, evidence_coverage)
    if "## 依据与覆盖" not in note:
        note = f"{note.rstrip()}\n\n{evidence_section}\n"
    if frame_extraction_warning:
        summary_warning = "；".join(filter(None, [summary_warning, frame_extraction_warning]))
    summary_diagnostics = build_summary_diagnostics(
        task_id=task_id,
        title=title,
        page_url=page_url,
        options=options,
        grids=grids,
        visual_windows=visual_windows,
        summary_source=summary_source,
        summary_warning=summary_warning,
        llm_events=llm_events,
        page_context=page_context,
        extracted_frame_count=len(frames) if options.visual_understanding else None,
        frame_extraction_warning=frame_extraction_warning,
        frame_anchor_timestamps=frame_anchor_timestamps,
    )
    normalized_note = normalize_note_markdown(title, note)
    note = normalized_note.markdown
    note_quality_path = write_json(task_id, "note_quality.json", normalized_note.report)
    if normalized_note.report["blocking"]:
        quarantine_path = task_dir(task_id) / "note.quarantine.md"
        quarantine_path.write_text(note, encoding="utf-8")
        update_task(
            task_id,
            status="failed",
            phase="failed",
            progress=100,
            message="笔记质量检查发现疑似乱码，已阻止不可靠内容进入资料库。",
            error_code="note_quality_failed",
            error_detail="疑似乱码内容已保留在本地隔离文件，可在修复编码后重试。",
            summary_warning="笔记未发布：Unicode/乱码质量门禁未通过",
        )
        return
    note_document = build_note_document(title, note)
    note_document_path = write_json(task_id, "note_document.json", note_document)
    summary_diagnostics["media_integrity"] = integrity.model_dump(mode="json")
    summary_diagnostics["evidence_coverage"] = evidence_coverage.model_dump(mode="json")
    summary_diagnostics["note_quality"] = normalized_note.report
    summary_diagnostics["note_quality_path"] = str(note_quality_path)
    summary_diagnostics["note_document_path"] = str(note_document_path)
    summary_diagnostics_path = write_json(task_id, "summary_diagnostics.json", summary_diagnostics)
    note_path = task_dir(task_id) / "note.md"
    note_path.write_text(note, encoding="utf-8")

    final_fields = {
        "note_path": str(note_path),
        "summary_source": summary_source,
        "summary_warning": summary_warning,
        "summary_diagnostics_path": str(summary_diagnostics_path),
        "summary_diagnostics": summary_diagnostics,
    }
    if asr_error:
        update_task(
            task_id,
            status="failed",
            phase="failed",
            progress=100,
            message=asr_error,
            error_code="asr_failed",
            error_detail=asr_error,
            **final_fields,
        )
    else:
        update_task(
            task_id,
            status="success",
            phase="completed",
            progress=100,
            message="任务完成，但未生成视觉切片" if frame_extraction_warning else "任务完成",
            **final_fields,
        )
        mark_checkpoint(task_id, "note_ready")


__all__ = ["finish_note_task"]
