"""Keep a read-only file reference for new OCR tasks without copying media."""
from contextlib import ExitStack
import os
from pathlib import Path
import re
import tempfile

from fastapi import HTTPException

from .storage import create_task, delete_task, task_dir, update_task


def retained_media_name(path: Path, *, range_pending=False):
    suffix = path.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ".media"
    stem = "screen-subtitles-original" if range_pending else "screen-subtitles-source"
    return stem + suffix


def create_retained_ocr_task(source, path: Path, options, *, title=None, range_pending=False):
    task = None
    with ExitStack() as cleanup:
        try:
            prepared = None
            root = task_dir(source.id).parent.resolve()
            if path.resolve().is_relative_to(root):
                # Probe/support failure happens before any task record exists.
                stage = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix=".screen-subtitles-", dir=root)))
                prepared = stage / "source.media"
                os.link(path.resolve(strict=True), prepared)
            task = create_task("local", title or source.title, source.page_url, options=options, mode="screen_subtitles")
            if prepared is not None:
                name = retained_media_name(path, range_pending=range_pending)
                path = task_dir(task.id) / name
                prepared.replace(path)
            return task, path
        except OSError as exc:
            if task is not None:
                # Roll back only this newly created, still-empty task. Nothing
                # has been queued or linked to the original record yet.
                update_task(task.id, status="failed", phase="failed")
                delete_task(task.id)
            raise HTTPException(409, {"code": "screen_ocr_media_retention_failed",
                "message": "无法保留独立视频引用，未开始提取。原资料保持不变；请在支持硬链接且有可用空间的本地资料目录中重试。"}) from exc
