"""Private CLI entry point for source and PyInstaller PDF workers."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 4:
        return 2
    source, destination, max_pages, max_chars = arguments
    # Limits are set before importing the parser or loading any PDF bytes.
    from .pdf_process import MAX_PDF_BYTES, MAX_RESULT_BYTES, PDF_MEMORY_BYTES
    from .pdf_limits import install_worker_limits
    install_worker_limits(PDF_MEMORY_BYTES, output_bytes=MAX_RESULT_BYTES)
    try:
        from .pdf_text import extract_pdf
        with Path(source).open("rb") as stream:
            content = stream.read(MAX_PDF_BYTES + 1)
        if len(content) > MAX_PDF_BYTES:
            raise ValueError("pdf_file_invalid")
        result = extract_pdf(content, int(max_pages), int(max_chars))
        from pypdf import __version__
        response = {"result": result, "parser_version": __version__}
    except ValueError as exc:
        from .pdf_process import _ERRORS
        response = {"error": str(exc) if str(exc) in _ERRORS else "pdf_file_invalid"}
    except Exception:
        response = {"error": "pdf_file_invalid"}
    data = json.dumps(response, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_RESULT_BYTES:
        data = b'{"error":"pdf_file_invalid"}'
    Path(destination).write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
