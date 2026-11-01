"""PDF extraction implementation. Called only inside the bounded PDF worker."""
from io import BytesIO
from .text_cleanup import TEXT_NORMALIZATION_VERSION, TextDecodingError, canonicalize_unicode_text


def extract_pdf(content: bytes, max_pages: int, max_chars: int):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pdf_text_extraction_unavailable") from exc

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("pdf_password_required")
        if len(reader.pages) > max_pages:
            raise ValueError("pdf_page_limit_exceeded")
        pages = []
        extracted_chars = 0
        replacement_character_count = 0
        for index, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            replacement_character_count += page_text.count("\ufffd")
            try:
                page_text = canonicalize_unicode_text(page_text)
            except TextDecodingError as exc:
                raise ValueError("text_mojibake_detected") from exc
            extracted_chars += len(page_text)
            if extracted_chars > max_chars:
                raise ValueError("extracted_text_too_large")
            pages.append(f"[第 {index} 页]\n{page_text}")
        return "\n\n".join(pages), "pdf", {
            "encoding": "pdf-text",
            "decoding_source": "pypdf",
            "encoding_source": "pypdf",
            "encoding_confidence": "not_applicable",
            "declared_encoding": "",
            "replacement_character_count": replacement_character_count,
            "normalization_version": TEXT_NORMALIZATION_VERSION,
            "page_count": len(reader.pages),
            "extracted_page_count": len(pages),
            "ocr_required": not any(page.strip() for page in pages),
        }
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("pdf_file_invalid") from exc
