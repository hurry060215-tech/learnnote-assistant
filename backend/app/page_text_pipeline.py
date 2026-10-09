"""Page-text and browser-subtitle fallback artifact generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import CurrentPageTaskRequest, TranscriptResult
from .storage import task_dir, write_json
from .claims import build_claim_evidence_map, mark_claims_for_review
from .note_document import build_note_document, normalize_note_markdown


@dataclass
class PageTextArtifacts:
    note_path: str = ""
    subtitle_path: str = ""
    transcript_path: str = ""
    created: bool = False
    summary_source: str = ""
    summary_warning: str = ""
    summary_diagnostics_path: str = ""
    summary_diagnostics: dict | None = None


def build_page_text_artifacts(
    task_id: str,
    request: CurrentPageTaskRequest,
    *,
    allow_empty: bool = True,
    transcript_from_browser_subtitles: Callable,
    page_text_with_browser_subtitles: Callable,
    write_browser_subtitles_srt: Callable,
    summarize_page_text_with_diagnostics: Callable,
    build_summary_diagnostics: Callable,
) -> PageTextArtifacts:
    transcript: TranscriptResult = transcript_from_browser_subtitles(request.browser_subtitles)
    page_text = page_text_with_browser_subtitles(request.page_text, transcript)
    if not allow_empty and not page_text.strip():
        return PageTextArtifacts()

    transcript_path = ""
    subtitle_path = ""
    if transcript.segments:
        subtitle_path = write_browser_subtitles_srt(task_id, transcript)
        transcript_path = str(write_json(task_id, "transcript.json", transcript.model_dump(mode="json")))
    note, summary_source, summary_warning = summarize_page_text_with_diagnostics(
        request.title,
        request.page_url,
        page_text,
        request.options,
    )
    normalized = normalize_note_markdown(request.title, note, generate_questions=request.options.generate_questions)
    quality_path = write_json(task_id, "note_quality.json", normalized.report)
    if normalized.report["blocking"]:
        (task_dir(task_id) / "note.quarantine.md").write_text(note, encoding="utf-8")
        raise ValueError("note_quality_failed: 页面文本笔记输出检查未通过；原始输出已保留。")
    document_evidence = [{"evidence_id": f"task-{task_id}-page-text", "source_type": "webpage",
        "locator": "captured page text", "source_uri": request.page_url, "text": request.page_text}] if request.page_text.strip() else []
    claims = build_claim_evidence_map(task_id, request.title, normalized.markdown, transcript, document_evidence=document_evidence)
    note = mark_claims_for_review(normalized.markdown, claims)
    if note != normalized.markdown:
        claims = build_claim_evidence_map(task_id, request.title, note, transcript, document_evidence=document_evidence)
        count = sum(claim["review_required"] for claim in claims["claims"])
        summary_warning = "；".join(filter(None, [summary_warning, f"{count} 条内容待回源核对，已在正文标记"]))
    claim_path = write_json(task_id, "claim_evidence_map.json", claims)
    document_path = write_json(task_id, "note_document.json", build_note_document(request.title, note, evidence=claims["evidence"]))
    note_path = task_dir(task_id) / "note.md"
    note_path.write_text(note, encoding="utf-8")
    summary_diagnostics = build_summary_diagnostics(
        task_id=task_id,
        title=request.title,
        page_url=request.page_url,
        options=request.options,
        grids=[],
        visual_windows=[],
        summary_source=summary_source,
        summary_warning=summary_warning,
    )
    summary_diagnostics.update({
        "note_quality_path": str(quality_path), "note_quality": normalized.report,
        "note_document_path": str(document_path), "claim_evidence_map_path": str(claim_path), "claim_evidence_quality": claims["quality"],
        "page_text_char_count": len((request.page_text or "").strip()),
        "browser_subtitle_count": len(transcript.segments),
        "combined_text_char_count": len(page_text),
        "used_page_text_fallback": True,
        "source_kind": "page_text_with_browser_cues" if transcript.segments else "page_text",
        "source_quality": "low",
        "evidence_quality": "low",
        "video_evidence": "missing",
        "can_claim_video_content": False,
        "evidence_warning": "No verified media, audio, or visual evidence is available.",
    })
    summary_diagnostics_path = write_json(task_id, "summary_diagnostics.json", summary_diagnostics)
    return PageTextArtifacts(
        note_path=str(note_path),
        subtitle_path=subtitle_path,
        transcript_path=transcript_path,
        created=True,
        summary_source=summary_source,
        summary_warning=summary_warning,
        summary_diagnostics_path=str(summary_diagnostics_path),
        summary_diagnostics=summary_diagnostics,
    )


__all__ = ["PageTextArtifacts", "build_page_text_artifacts"]
