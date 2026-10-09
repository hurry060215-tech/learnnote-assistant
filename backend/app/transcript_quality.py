"""Keep unresolved ASR text reviewable without publishing it as a formal note."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .models import TranscriptResult
from .storage import atomic_write_text
from .text_cleanup import TEXT_NORMALIZATION_VERSION, mojibake_score, redact_sensitive_url_values


def transcript_quality_report(transcript: TranscriptResult) -> dict:
    text = "\n".join(segment.text for segment in transcript.segments) if transcript.segments else transcript.full_text
    replacements, markers = text.count("\ufffd"), text.count("【识别不清】")
    needs_review = bool(replacements or markers or mojibake_score(text) >= 4)
    local_asr = transcript.source == "faster-whisper"
    return {"schema_version": 1, "status": "review_required" if needs_review else "ready",
        "review_required": needs_review, "source_kind": "local_asr" if local_asr else "transcript",
        "issue_kind": "asr_character_uncertainty" if local_asr and (replacements or markers) else "unicode_corruption" if needs_review else "none",
        "replacement_character_count": replacements, "uncertain_marker_count": markers,
        "normalization_version": TEXT_NORMALIZATION_VERSION, "encoding_repaired": False,
        "formal_note_allowed": not needs_review}


def preserve_transcript_review_draft(task_id: str, title: str, transcript: TranscriptResult, *,
        task_dir: Callable[[str], Path], write_json: Callable, update_task: Callable) -> bool:
    quality = transcript_quality_report(transcript)
    quality_path = write_json(task_id, "transcript_quality.json", quality)
    if not quality["review_required"]:
        return False
    message = "转写含待核对字符，已保留原始转写和待核对草稿；请核对原音频并重新转写，尚未发布正式笔记。"
    title = redact_sensitive_url_values(str(title or "学习笔记")).replace("\n", " ").replace("\r", " ")
    lines = [f"# {title}", "", "> 待核对草稿：包含【识别不清】或可疑文字，不能作为已核对的课程结论。", "", "## 待核对字幕", ""]
    if transcript.segments:
        for segment in transcript.segments:
            seconds = max(0, int(segment.start))
            text = redact_sensitive_url_values(segment.text.replace("\ufffd", "【识别不清】"))
            lines.append(f"- [{seconds // 60:02d}:{seconds % 60:02d}] " + text.replace("\n", " "))
    else:
        lines.append(redact_sensitive_url_values(transcript.full_text.replace("\ufffd", "【识别不清】")))
    path = task_dir(task_id) / "draft.review.md"
    atomic_write_text(path, "\n".join(lines) + "\n")
    diagnostics = {"summary_generated": False, "note_publication": "review_draft", "review_required": True,
        "transcript_quality": quality, "transcript_quality_path": str(quality_path),
        "can_claim_video_content": False, "evidence_quality": "review_required"}
    diagnostic_path = write_json(task_id, "summary_diagnostics.json", diagnostics)
    update_task(task_id, status="failed", phase="failed", progress=100, message=message,
        error_code="transcript_review_required", error_detail=message, checkpoint="transcript_ready",
        failed_phase="summarizing", note_path=str(path), summary_source="transcript-draft",
        summary_warning=message, summary_diagnostics=diagnostics, summary_diagnostics_path=str(diagnostic_path))
    return True
