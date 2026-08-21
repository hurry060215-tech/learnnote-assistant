"""Page-text and browser-subtitle fallback artifact generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import CurrentPageTaskRequest, TranscriptResult
from .storage import task_dir, write_json


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
