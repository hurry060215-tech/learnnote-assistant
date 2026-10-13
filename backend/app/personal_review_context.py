"""Bounded version witnesses for a whole-note personal reading record.

These hashes describe local note/source versions, never factual correctness or
the identity of the person who clicked. Large original videos are not scanned.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat

from .library import get_material, material_source_path, material_content
from .personal_anchors import digest, read_anchor_artifact
from .storage import get_task, task_dir
from .task_artifacts import owned_task_artifact

MAX_SOURCE_BYTES = 128 * 1024 * 1024


def _file_witness(path: Path) -> dict:
    """Read one bounded regular file and reject replacement/mutation while read."""
    if path.is_symlink():
        raise ValueError("personal_review_source_unsafe")
    before = path.lstat()
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_SOURCE_BYTES
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError("personal_review_source_unavailable")
        result, size = hashlib.sha256(), 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                raise ValueError("personal_review_source_unavailable")
            result.update(chunk)
        after = os.fstat(stream.fileno())
    final = path.lstat()
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if identity(opened) != identity(after) or identity(after) != identity(final):
        raise ValueError("personal_review_source_changed")
    return {"hash": result.hexdigest(), "generation": list(identity(final))}


def source_context(kind: str, source_id: str, edition: dict) -> dict:
    labels, unavailable, witnesses = [], [], {}
    stable = True
    if kind == "material":
        item = get_material(source_id)
        witnesses["catalog"] = {key: item.get(key) for key in ("material_id", "sha256", "status", "updated_at", "metadata")}
        witnesses["source_text"] = hashlib.sha256(material_content(source_id).encode("utf-8")).hexdigest()
        try:
            witnesses["original"] = _file_witness(material_source_path(source_id))
            labels.append("本地原始资料")
        except (OSError, ValueError):
            unavailable.append("原始资料")
            witnesses["original"] = None
        stable = item.get("status") not in {"processing", "running", "queued"}
    else:
        task = get_task(source_id)
        stable = task.status not in {"queued", "running", "cancelling"}
        witnesses["generation"] = [task.control_generation, task.retry_count, task.checkpoint_updated_at]
        witnesses["identity"] = [task.source_type, task.mode, task.source_task_id, task.page_url,
            task.source_identity.model_dump(mode="json"), task.screen_subtitles_media_sha256]
        # Persisted subtitle/page-text evidence can exist without a transcript.
        witnesses["browser_subtitles"] = [cue.model_dump(mode="json") for cue in task.browser_subtitles]
        if any(cue.text.strip() for cue in task.browser_subtitles):
            labels.append("已保存的页面字幕")
        if task.source_type == "page_text" or task.mode == "page_text" or task.summary_diagnostics.get("used_page_text_fallback"):
            claim_path = str(task_dir(source_id) / "claim_evidence_map.json")
            try:
                mapped = json.loads(read_anchor_artifact(source_id, claim_path))
                page_sources = [item for item in mapped.get("evidence", [])
                    if isinstance(item, dict) and item.get("source_type") == "webpage"
                    and item.get("evidence_id") == f"task-{source_id}-page-text" and isinstance(item.get("text"), str)]
                if not page_sources:
                    raise ValueError("page_source_missing")
                source_path = owned_task_artifact(source_id, claim_path)
                if source_path is None:
                    raise ValueError("page_source_missing")
                witnesses["page_text"] = [digest(page_sources), _file_witness(source_path)]
                labels.append("已保存的页面原文")
            except (OSError, ValueError, TypeError, AttributeError):
                witnesses["page_text"] = None
                unavailable.append("页面原文")
        for name, path, label in (("transcript", task.transcript_path, "字幕原文"),
                                 ("visual", task.visual_index_path, "关键帧索引")):
            if not path:
                witnesses[name] = None
                continue  # Only declared sources belong to this note's scope.
            try:
                raw = read_anchor_artifact(source_id, path)
                payload = json.loads(raw) if raw else None
                if not isinstance(payload, dict):
                    raise ValueError("source_missing")
                if name == "transcript":
                    segments = payload.get("segments")
                    if (not isinstance(segments, list) or not segments or len(segments) > 100_000
                            or any(not isinstance(item, dict) or not isinstance(item.get("text"), str)
                                or any(isinstance(item.get(key), bool) or not isinstance(item.get(key), (int, float))
                                    or not math.isfinite(item[key]) or item[key] < 0 for key in ("start", "end"))
                                or item["end"] < item["start"] for item in segments)
                            or not any(item["text"].strip() for item in segments)):
                        raise ValueError("transcript_source_invalid")
                source_path = owned_task_artifact(source_id, path)
                if source_path is None:
                    raise ValueError("source_missing")
                witnesses[name] = [digest(payload), _file_witness(source_path)]
                labels.append(label)
                if name == "visual":
                    windows = payload.get("windows", [])
                    if not isinstance(windows, list) or len(windows) > 1000:
                        raise ValueError("visual_source_invalid")
                    images, image_bytes = [], 0
                    for window in windows:
                        if not isinstance(window, dict):
                            raise ValueError("visual_source_invalid")
                        value = window.get("grid_path") or window.get("image_path") or ""
                        if value:
                            image_path = owned_task_artifact(source_id, str(value), directory="grids")
                            witness = _file_witness(image_path) if image_path else None
                            image_bytes += witness["generation"][2] if witness else 0
                            if image_bytes > MAX_SOURCE_BYTES:
                                raise ValueError("visual_source_too_large")
                            images.append([str(value), witness])
                            if not witness:
                                unavailable.append("关键帧图像")
                        else:
                            unavailable.append("关键帧图像")
                    witnesses["images"] = images
            except (OSError, ValueError, TypeError, OverflowError):
                witnesses[name] = None
                unavailable.append(label)
        # Same-byte source-note regeneration is a new review context too.
        original = owned_task_artifact(source_id, task.note_path)
        witnesses["generated_note"] = _file_witness(original) if original else None
        if not original:
            unavailable.append("原始生成稿")
    note_revision = hashlib.sha256(edition["text"].encode("utf-8")).hexdigest()
    revision = digest([kind, source_id, note_revision, edition.get("write_id", ""), witnesses])
    scope = "available_sources" if labels and not unavailable else "reading_only"
    detail = ("绑定当前正文与可用本地来源版本；只记录本机个人核对动作，不证明事实正确或个人身份。"
              if scope == "available_sources" else
              "部分来源缺失或无法校验：仅记录当前正文的个人阅读核对，不表示来源已证实。")
    if kind == "task":
        detail += " 原视频内容与模型结论未因此获得验证。"
    return {"context_revision": revision, "note_revision": note_revision,
        "can_mark": stable and bool(edition["text"].strip()), "source_scope": scope,
        "scope_detail": detail if stable else "来源任务仍在处理；请等当前版本稳定后再核对。",
        "source_labels": labels}
