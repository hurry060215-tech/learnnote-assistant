"""Reuse owned local ASR output only for the same media and ASR settings."""
from __future__ import annotations

import hashlib
import json

from .models import TranscriptResult
from .storage import task_dir, write_json
from .text_cleanup import correct_transcript_terms, TextDecodingError


def media_cache_integrity(integrity, media_path):
    """Key the cached text to the normalized file that recovery will reopen."""
    if not getattr(integrity, "sha256", ""):
        return integrity
    with media_path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return integrity.model_copy(update={"sha256": digest})


def _identity(integrity, options) -> dict:
    return {
        "schema_version": 1,
        "media_sha256": str(getattr(integrity, "sha256", "") or ""),
        "transcriber": options.transcriber,
        "whisper_model": options.whisper_model,
    }


def save_local_transcript(task_id: str, transcript: TranscriptResult, integrity, options) -> None:
    if not getattr(integrity, "sha256", "") or transcript.source != "faster-whisper" or not transcript.segments:
        return
    try:
        transcript = correct_transcript_terms(transcript)
    except TextDecodingError:
        return
    # The metadata never includes remote model credentials or browser context.
    path = write_json(task_id, "transcript_cache_payload.json", transcript.model_dump(mode="json"))
    identity = _identity(integrity, options)
    identity["transcript_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(task_id, "transcript_cache.json", identity)


def load_local_transcript(task_id: str, integrity, options) -> TranscriptResult | None:
    if not getattr(integrity, "sha256", "") or options.transcriber != "faster-whisper":
        return None
    root = task_dir(task_id)
    try:
        metadata = json.loads((root / "transcript_cache.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or any(metadata.get(k) != v for k, v in _identity(integrity, options).items()):
            return None
        raw = (root / "transcript_cache_payload.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata.get("transcript_sha256"):
            return None
        transcript = TranscriptResult.model_validate_json(raw)
        if transcript.source == "faster-whisper" and transcript.segments and transcript.full_text.strip():
            return correct_transcript_terms(transcript)
    except (OSError, ValueError, TypeError):
        pass
    return None
