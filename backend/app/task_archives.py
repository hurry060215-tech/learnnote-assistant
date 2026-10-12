"""Portable ZIP serialization from explicit, already-projected task artifacts.

HTTP validation, artifact lookups and report rendering stay with the caller. This
module preserves member order and literal bytes; it never updates source files.
Personal annotations are an explicit opt-in and remain a separate ZIP member.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .models import TaskRecord


@dataclass(frozen=True)
class StudyArchive:
    task: TaskRecord
    note: str
    transcript: dict
    visual_index: dict
    qa_history: list[dict]
    claim_map: dict


@dataclass(frozen=True)
class BundleArchive(StudyArchive):
    diagnostics: str
    audit_report: str
    visual_windows: str
    qa_report: str
    manifest: dict
    resource_inventory: dict
    page_preflight: dict
    generated_subtitles: str


def write_file_if_exists(archive: ZipFile, path_value: str, archive_name: str) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if path.is_file():
        archive.write(path, archive_name)


def build_bundle_archive(
    data: BundleArchive, *, annotations: list[dict] | None = None,
    qa_history_file: str = "qa_history.json",
    write_file: Callable[[ZipFile, str, str], None] = write_file_if_exists,
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(data.manifest, ensure_ascii=False, indent=2))
        archive.writestr("audit.md", data.audit_report)
        archive.writestr("diagnostics.md", data.diagnostics)
        archive.writestr("visual_windows.md", data.visual_windows)
        if data.qa_history:
            archive.writestr("qa.md", data.qa_report)
            archive.writestr(qa_history_file, json.dumps({"schema_version": 1, "items": data.qa_history}, ensure_ascii=False, indent=2))
        if data.note.strip():
            archive.writestr("note.md", data.note)
        archive.writestr("task.json", json.dumps(data.task.model_dump(mode="json"), ensure_ascii=False, indent=2))
        archive.writestr("transcript.json", json.dumps(data.transcript, ensure_ascii=False, indent=2))
        archive.writestr("visual_index.json", json.dumps(data.visual_index, ensure_ascii=False, indent=2))
        if data.resource_inventory:
            archive.writestr("resource_inventory.json", json.dumps(data.resource_inventory, ensure_ascii=False, indent=2))
        if data.page_preflight:
            archive.writestr("page_preflight_report.json", json.dumps(data.page_preflight, ensure_ascii=False, indent=2))
        if data.task.subtitle_path:
            write_file(archive, data.task.subtitle_path, f"subtitles/{Path(data.task.subtitle_path).name}")
        elif data.generated_subtitles:
            archive.writestr("subtitles/generated-transcript.srt", data.generated_subtitles)
        if data.task.summary_diagnostics:
            archive.writestr("summary_diagnostics.json", json.dumps(data.task.summary_diagnostics, ensure_ascii=False, indent=2))
        if isinstance(data.claim_map, dict) and data.claim_map:
            archive.writestr("claim_evidence_map.json", json.dumps(data.claim_map, ensure_ascii=False, indent=2))
        if annotations is not None:
            archive.writestr("personal_annotations.json", json.dumps({"schema_version": 2, "task_id": data.task.id, "annotations": annotations}, ensure_ascii=False, indent=2))
        for index, grid in enumerate(data.task.frame_grids):
            filename = Path(grid.path).name or f"grid_{index:03d}.jpg"
            write_file(archive, grid.path, f"grids/{filename}")

    return buffer.getvalue()


def build_sanitized_archive(data: StudyArchive) -> bytes:
    safe_manifest = {
        "schema_version": 1,
        "bundle_type": "sanitized-study",
        "privacy": {
            "original_media": False,
            "cookies": False,
            "signed_urls": False,
            "diagnostics": False,
            "source_paths": False,
        },
        "task": {"id": data.task.id, "title": data.task.title, "source_type": data.task.source_type, "status": data.task.status},
        "artifacts": {"note": bool(data.note.strip()), "transcript": bool(data.transcript.get("segments")), "visual_index": bool(data.visual_index.get("windows")), "qa": bool(data.qa_history), "claim_evidence": bool(data.claim_map)},
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(safe_manifest, ensure_ascii=False, indent=2))
        if data.note.strip():
            archive.writestr("note.md", data.note)
        archive.writestr("transcript.json", json.dumps(data.transcript, ensure_ascii=False, indent=2))
        archive.writestr("visual_index.json", json.dumps(data.visual_index, ensure_ascii=False, indent=2))
        if data.qa_history:
            archive.writestr("qa_history.json", json.dumps({"schema_version": 1, "items": data.qa_history}, ensure_ascii=False, indent=2))
        if isinstance(data.claim_map, dict) and data.claim_map:
            archive.writestr("claim_evidence_map.json", json.dumps({
                "schema_version": data.claim_map.get("schema_version", 1),
                "task_id": data.task.id,
                "title": data.task.title,
                "claims": data.claim_map.get("claims", []),
                "counts": data.claim_map.get("counts", {}),
                "quality": data.claim_map.get("quality", {}),
            }, ensure_ascii=False, indent=2))
    return buffer.getvalue()


def build_support_archive(manifest: dict, events: list[dict], diagnostics: str, audit: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("events.json", json.dumps(events, ensure_ascii=False, indent=2))
        archive.writestr("diagnostics.md", diagnostics)
        archive.writestr("audit.md", audit)
    return buffer.getvalue()
