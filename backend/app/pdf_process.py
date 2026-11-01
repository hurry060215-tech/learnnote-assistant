"""Bound untrusted PDF parsing independently of the server and desktop process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from .media_process import owned_media_process
from .pdf_limits import wait_for_pdf_worker

MAX_PDF_BYTES = 32 * 1024 * 1024
PDF_MEMORY_BYTES = 1024 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 30
MAX_RESULT_BYTES = 32 * 1024 * 1024
_SLOTS = threading.BoundedSemaphore(2)
_ERRORS = {
    "pdf_text_extraction_unavailable", "pdf_password_required", "pdf_file_invalid",
    "pdf_page_limit_exceeded", "extracted_text_too_large", "text_mojibake_detected",
}


def _worker_command(arguments):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pdf-worker", *arguments]
    return [sys.executable, "-m", "app.pdf_worker", *arguments]


def extract_pdf_isolated(content: bytes, max_pages: int, max_chars: int):
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("pdf_file_invalid")
    # Reject overload instead of retaining an unbounded queue of uploaded PDFs.
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("pdf_file_invalid")
    try:
        with tempfile.TemporaryDirectory(prefix="learnnote-pdf-") as directory:
            source, result = Path(directory) / "input.pdf", Path(directory) / "result.json"
            source.write_bytes(content)
            arguments = [str(source), str(result), str(max_pages), str(max_chars)]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            if sys.platform == 'darwin':
                env['MallocNanoZone'] = '0'
            with owned_media_process(
                _worker_command(arguments), memory_limit_bytes=PDF_MEMORY_BYTES,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env,
            ) as process:
                wait_for_pdf_worker(process, timeout=PDF_TIMEOUT_SECONDS, memory_bytes=PDF_MEMORY_BYTES)
                if process.returncode:
                    raise ValueError("pdf_file_invalid")
            with result.open("rb") as stream:
                data = stream.read(MAX_RESULT_BYTES + 1)
            if len(data) > MAX_RESULT_BYTES:
                raise ValueError("pdf_file_invalid")
            response = json.loads(data)
            if "error" in response:
                code = response["error"]
                raise ValueError(code if code in _ERRORS else "pdf_file_invalid")
            text, source_type, metadata = response["result"]
            if not isinstance(text, str) or source_type != "pdf" or not isinstance(metadata, dict):
                raise ValueError("pdf_file_invalid")
            return text, source_type, metadata
    except ValueError as exc:
        if str(exc) in _ERRORS:
            raise
        raise ValueError("pdf_file_invalid") from exc
    except (OSError, MemoryError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        raise ValueError("pdf_file_invalid") from exc
    finally:
        _SLOTS.release()
