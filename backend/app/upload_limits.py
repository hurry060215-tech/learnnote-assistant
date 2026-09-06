"""Bound request spooling and final upload writes, including chunked bodies."""
from __future__ import annotations

import shutil
from pathlib import Path

from starlette.responses import JSONResponse

from .config import TEMP_DIR, UPLOAD_DIR

MAX_VIDEO_BYTES = 4 * 1024**3
MIN_FREE_BYTES = 512 * 1024**2
MULTIPART_OVERHEAD_BYTES = 1024**2


class UploadBudgetExceeded(ValueError):
    def __init__(self, code: str, status: int, message: str):
        self.code, self.status, self.message = code, status, message
        super().__init__(message)


def check_upload_space(path: Path, incoming: int = 0) -> None:
    if shutil.disk_usage(path).free < MIN_FREE_BYTES + max(0, incoming):
        raise UploadBudgetExceeded("insufficient_storage", 507, "磁盘空间不足：请至少保留 512 MB，清理后重试。")


async def write_video_upload(file, path: Path) -> int:
    total = 0
    try:
        with path.open("wb") as output:
            while chunk := await file.read(1024**2):
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    raise UploadBudgetExceeded("video_too_large", 413, "单个视频不能超过 4 GB，请拆分后导入。")
                check_upload_space(path.parent, len(chunk))
                output.write(chunk)
        return total
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


class UploadBudgetMiddleware:
    """Enforce limits before Starlette's multipart parser consumes disk space."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        limits = {
            "/api/media/preflight-local": MAX_VIDEO_BYTES,
            "/api/tasks/from-local": MAX_VIDEO_BYTES,
            "/api/library/materials/import": 32 * 1024**2,
            "/api/knowledge/import-file": 20 * 1024**2,
            "/api/library/restore": 128 * 1024**2,
        }
        limit = limits.get(scope.get("path"))
        if scope["type"] != "http" or scope.get("method") != "POST" or limit is None:
            return await self.app(scope, receive, send)
        limit += MULTIPART_OVERHEAD_BYTES
        rejection = None
        total = 0
        async def bounded_receive():
            nonlocal total, rejection
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                try:
                    if total > limit:
                        raise UploadBudgetExceeded("upload_too_large", 413, "上传超过大小限制，请拆分文件。")
                    check_upload_space(TEMP_DIR, len(message.get("body", b"")))
                except UploadBudgetExceeded as exc:
                    rejection = exc
                    raise
            return message
        async def bounded_send(message):
            if rejection is None:
                await send(message)
        try:
            headers = dict(scope.get("headers", []))
            try:
                declared = int(headers.get(b"content-length", b"0"))
            except ValueError:
                declared = limit + 1
            if declared < 0 or declared > limit:
                raise UploadBudgetExceeded("upload_too_large", 413, "上传超过大小限制，请拆分文件。")
            copies = 2 if scope["path"] in {"/api/media/preflight-local", "/api/tasks/from-local"} else 1
            check_upload_space(TEMP_DIR, declared * copies)
            check_upload_space(UPLOAD_DIR)
            await self.app(scope, bounded_receive, bounded_send)
        except Exception as exc:
            if isinstance(exc, UploadBudgetExceeded):
                rejection = exc
            if rejection is None:
                raise
        if rejection:
            await JSONResponse({"detail": {"code": rejection.code, "message": rejection.message}}, status_code=rejection.status)(scope, receive, send)
