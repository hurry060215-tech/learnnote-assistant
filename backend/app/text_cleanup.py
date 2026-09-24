from __future__ import annotations

from dataclasses import dataclass
import codecs
import hashlib
import re
import unicodedata
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from charset_normalizer import from_bytes

from .models import TranscriptResult


TEXT_NORMALIZATION_VERSION = "nfc-newlines-controls-v1"


# Only exact, high-confidence Chinese ASR confusions belong here. This avoids
# changing legitimate wording while fixing common course terminology errors.
COMMON_ZH_ASR_REPLACEMENTS = {
    "半分建": "半封建",
    "半风建": "半封建",
    "武士运动": "五四运动",
    "五式运动": "五四运动",
    "骨田会议": "古田会议",
    "固田会议": "古田会议",
    "笼心阶段": "《论新阶段》",
    "论心阶段": "《论新阶段》",
}


class TextDecodingError(ValueError):
    """Raised when text cannot be decoded without silently losing content."""


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str
    repaired: bool = False
    mojibake_score: int = 0
    raw_sha256: str = ""
    byte_count: int = 0
    encoding_source: str = "unknown"
    # A provenance category, not a calibrated probability.
    encoding_confidence: str = "low"
    declared_encoding: str = ""
    replacement_character_count: int = 0
    normalization_version: str = TEXT_NORMALIZATION_VERSION


_MOJIBAKE_MARKERS = (
    "\ufffd",
    "\u00e2\u20ac",
    "\u00f0\u0178",
    "\u00ef\u00bb\u00bf",
    "\u00e8\u00af",
    "\u00e7\u00a8",
    "\u00e6\u20ac",
    "\u00e7\u00bb",
    "\u951f\u65a4\u62f7",
    "\u6d93\ue15f",
    "\u93c2\u56e7",
    "\u7487\u8f70",
)
_UTF8_MOJIBAKE_RE = re.compile(r"(?:Ã[\u0080-\u00bf]|Â(?:[\u0080-\u00bf]|\s)|â(?:€|™|œ|“|”|…)|ðŸ)")
_SENSITIVE_URL_VALUE_RE = re.compile(
    r"([?&](?:token|access_token|auth|auth_token|authorization|signature|sign|sig|key|expires|expires_at|jwt|policy|key-pair-id|x-amz-signature|x-amz-credential)=)[^&#\s]+",
    re.I,
)
_URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.I)
_SENSITIVE_QUERY_KEYS = {
    "token", "accesstoken", "refreshtoken", "auth", "authtoken", "authorization",
    "signature", "sign", "sig", "credential", "policy", "key", "keypairid", "jwt",
    "session", "sessionid", "secret", "password", "expires", "expiresat", "expiry",
    "xamzsignature", "xamzcredential", "xamzsecuritytoken", "xamzexpires",
    "ossaccesskeyid", "securitytoken", "sas", "se", "sp", "sr", "sv",
}
_ALLOWED_DETECTED_ENCODINGS = {
    "ascii", "utf_8", "utf_8_sig", "utf_16", "utf_16_le", "utf_16_be",
    "utf_32", "utf_32_le", "utf_32_be", "gb18030", "gbk", "big5",
    "cp932", "shift_jis", "shift_jis_2004", "cp1252", "latin_1", "iso8859_1",
}
_HTML_CHARSET_RE = re.compile(r"<meta\b[^>]*charset\s*=\s*['\"]?\s*([a-zA-Z0-9._-]+)", re.I)
_HTML_CONTENT_CHARSET_RE = re.compile(
    r"<meta\b(?=[^>]*http-equiv\s*=\s*['\"]?content-type)[^>]*content\s*=\s*['\"][^'\"]*?charset\s*=\s*([a-zA-Z0-9._-]+)",
    re.I,
)


def mojibake_score(value: str) -> int:
    """Return a conservative corruption score without penalising normal CJK."""

    text = str(value or "")
    score = sum(text.count(marker) * (10 if marker == "\ufffd" else 2) for marker in _MOJIBAKE_MARKERS)
    score += len(_UTF8_MOJIBAKE_RE.findall(text)) * 2
    score += sum(4 for char in text if 0x80 <= ord(char) <= 0x9F)
    score += text.count("\x00") * 4
    return score


def _repair_utf8_mojibake(value: str) -> tuple[str, bool]:
    original = str(value or "")
    original_score = mojibake_score(original)
    if original_score <= 0:
        return original, False
    best = original
    best_score = original_score
    for legacy_encoding in ("cp1252", "latin-1", "gb18030"):
        try:
            candidate = original.encode(legacy_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        candidate_score = mojibake_score(candidate)
        if candidate_score < best_score:
            best = candidate
            best_score = candidate_score
    return best, best != original


def redact_sensitive_url_values(value: str) -> str:
    """Keep local drafts useful without persisting signed query values."""

    text = str(value or "")

    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = ""
        while raw and raw[-1] in ".,;，。；)":
            suffix = raw[-1] + suffix
            raw = raw[:-1]
        try:
            parsed = urlsplit(raw)
            query = []
            for key, item in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=200):
                normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
                sensitive = normalized in _SENSITIVE_QUERY_KEYS or any(
                    token in normalized for token in ("token", "signature", "credential", "password", "secret")
                )
                query.append((key, "<redacted>" if sensitive else item))
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, safe="<>"), parsed.fragment)) + suffix
        except (TypeError, ValueError):
            return _SENSITIVE_URL_VALUE_RE.sub(r"\1<redacted>", raw) + suffix

    return _SENSITIVE_URL_VALUE_RE.sub(r"\1<redacted>", _URL_RE.sub(redact_url, text))


def canonicalize_unicode_text(value: str, *, reject_mojibake: bool = True) -> str:
    """Normalize text to NFC/newline form and block high-confidence corruption."""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.lstrip("\ufeff")
    text, _repaired = _repair_utf8_mojibake(text)
    text = unicodedata.normalize("NFC", text)
    # NUL and non-whitespace C0 controls cannot be meaningful subtitle/note text.
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 0x20)
    score = mojibake_score(text)
    if reject_mojibake and score >= 4:
        raise TextDecodingError("text_mojibake_detected")
    return text


def _encoding_name(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "")
    aliases = {
        "utf8": "utf_8",
        "utf8sig": "utf_8_sig",
        "gb2312": "gb18030",
        "gb_2312": "gb18030",
        "cp936": "gb18030",
        "ms936": "gb18030",
        "big5hkscs": "big5hkscs",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        canonical = codecs.lookup(normalized).name
    except LookupError:
        return ""
    return canonical if canonical.replace("-", "_") in _ALLOWED_DETECTED_ENCODINGS else ""


def declared_text_encoding(content_type: str = "", content: bytes = b"", *, html_hint: bool = False) -> str:
    """Read a bounded MIME charset or HTML meta charset without decoding body text."""

    try:
        mime = Message()
        mime["content-type"] = str(content_type or "")
        charset = str(mime.get_content_charset() or "").strip()
    except (TypeError, ValueError):
        charset = ""
    is_html = html_hint or "html" in str(content_type or "").lower()
    if not charset and is_html:
        # Latin-1 maps every byte one-to-one and is used only to parse ASCII
        # charset declarations in the document header.
        header = bytes(content or b"")[:8192].decode("latin-1")
        match = _HTML_CHARSET_RE.search(header) or _HTML_CONTENT_CHARSET_RE.search(header)
        charset = match.group(1) if match else ""
    return str(charset or "").strip()[:40]


def _decode_candidates(
    content: bytes,
    requested_encoding: str = "",
    declared_encoding: str = "",
) -> list[tuple[str, str, str]]:
    if not content:
        return [("utf_8", "", "empty-input")]
    if requested_encoding:
        normalized = _encoding_name(requested_encoding)
        if not normalized:
            return []
        try:
            return [(normalized, content.decode(normalized, errors="strict"), "user-selected")]
        except (UnicodeDecodeError, UnicodeError):
            return []
    candidates: list[tuple[str, str, str]] = []
    if content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encodings = ("utf-32",)
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    elif content.startswith(b"\xef\xbb\xbf"):
        encodings = ("utf-8-sig",)
    elif declared_encoding:
        declared = _encoding_name(declared_encoding)
        if not declared:
            return []
        try:
            return [(declared, content.decode(declared, errors="strict"), "declared-charset")]
        except (UnicodeDecodeError, UnicodeError):
            # A declared charset is authoritative. Do not silently switch to
            # a lossy legacy fallback; ask the user to choose another encoding.
            return []
    else:
        detected = ""
        try:
            match = from_bytes(content).best()
            detected = str(match.encoding or "").lower().replace("-", "_") if match is not None else ""
            if detected not in _ALLOWED_DETECTED_ENCODINGS:
                detected = ""
        except Exception:
            detected = ""
        preferred_detected = detected if detected not in {"utf_16", "utf_16_le", "utf_16_be", "utf_32", "utf_32_le", "utf_32_be"} else ""
        encodings: list[tuple[str, str]] = []
        encodings.append(("utf_8", "strict-utf8"))
        if preferred_detected:
            encodings.append((preferred_detected, "charset-normalizer"))
        if detected:
            encodings.append((detected, "charset-normalizer"))
        encodings.extend(
            (encoding, "fallback")
            for encoding in (
                "gb18030",
                "utf_16_le" if len(content) % 2 == 0 else "",
                "utf_16_be" if len(content) % 2 == 0 else "",
                "cp932",
                "shift_jis",
                "cp1252",
            )
            if encoding
        )
        # Keep the first provenance path for an encoding so declared charsets
        # and strict UTF-8 are not relabeled as generic fallbacks.
        unique: dict[str, str] = {}
        for encoding, source in encodings:
            canonical = _encoding_name(encoding)
            if canonical:
                unique.setdefault(canonical, source)
        encodings = list(unique.items())
    if content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        source = "bom"
    elif content.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
        source = "bom"
    else:
        source = ""
    for encoding in encodings:
        if source:
            candidate_encoding, candidate_source = _encoding_name(encoding), source
        else:
            candidate_encoding, candidate_source = encoding
        try:
            candidates.append((candidate_encoding, content.decode(candidate_encoding, errors="strict"), candidate_source))
        except (UnicodeDecodeError, UnicodeError):
            continue
    return candidates


def _decode_quality_penalty(text: str) -> int:
    scripts: set[str] = set()
    for char in str(text or ""):
        code = ord(char)
        if 0x3400 <= code <= 0x9FFF:
            scripts.add("han")
        elif 0x3040 <= code <= 0x30FF:
            scripts.add("kana")
        elif 0xAC00 <= code <= 0xD7A3:
            scripts.add("hangul")
        elif 0x0600 <= code <= 0x06FF or 0xFE70 <= code <= 0xFEFF:
            scripts.add("arabic")
        elif 0x0900 <= code <= 0x0D7F:
            scripts.add("indic")
        elif "LATIN" in unicodedata.name(char, ""):
            scripts.add("latin")
    penalty = 0
    if len(scripts) >= 3:
        penalty += (len(scripts) - 2) * 6
    penalty += sum(8 for char in text if unicodedata.category(char) in {"Cs", "Co", "Cn"})
    return penalty


def decode_text_bytes(
    content: bytes,
    *,
    source: str = "",
    reject_mojibake: bool = True,
    encoding: str = "",
    declared_encoding: str = "",
) -> DecodedText:
    """Decode common subtitle encodings strictly; never discard invalid bytes."""

    decoded: list[tuple[int, int, DecodedText]] = []
    declared = _encoding_name(declared_encoding)
    for priority, (candidate_encoding, raw_text, encoding_source) in enumerate(
        _decode_candidates(bytes(content or b""), encoding, declared_encoding)
    ):
        try:
            repaired_text, repaired = _repair_utf8_mojibake(raw_text)
            text = canonicalize_unicode_text(repaired_text, reject_mojibake=False)
        except (UnicodeError, ValueError):
            continue
        raw_penalty = _decode_quality_penalty(raw_text) + sum(
            8 for char in raw_text if ord(char) < 0x20 and char not in "\n\r\t"
        )
        decoded.append(
            (priority, raw_penalty, DecodedText(
                text=text,
                encoding=candidate_encoding,
                repaired=repaired,
                mojibake_score=mojibake_score(text),
                encoding_source=encoding_source,
                encoding_confidence={
                    "bom": "high",
                    "declared-charset": "high",
                    "strict-utf8": "high",
                    "charset-normalizer": "medium",
                    "fallback": "low",
                    "user-selected": "user_selected",
                    "empty-input": "high",
                }.get(encoding_source, "low"),
                declared_encoding=declared,
                replacement_character_count=text.count("\ufffd"),
            ))
        )
    if not decoded:
        label = f" ({source})" if source else ""
        raise TextDecodingError(f"text_encoding_unsupported{label}")
    _priority, quality_penalty, best = min(
        decoded,
        key=lambda item: (item[2].mojibake_score + item[1] + _decode_quality_penalty(item[2].text), item[0]),
    )
    if reject_mojibake and quality_penalty >= 8:
        label = f" ({source})" if source else ""
        raise TextDecodingError(f"text_encoding_unsupported{label}")
    if reject_mojibake and best.mojibake_score >= 4:
        label = f" ({source})" if source else ""
        raise TextDecodingError(f"text_mojibake_detected{label}")
    return DecodedText(
        text=best.text,
        encoding=best.encoding,
        repaired=best.repaired,
        mojibake_score=best.mojibake_score,
        raw_sha256=hashlib.sha256(bytes(content or b"")).hexdigest(),
        byte_count=len(content or b""),
        encoding_source=best.encoding_source,
        encoding_confidence=best.encoding_confidence,
        declared_encoding=best.declared_encoding,
        replacement_character_count=best.replacement_character_count,
        normalization_version=best.normalization_version,
    )


def read_canonical_text(path: Path, *, reject_mojibake: bool = True) -> DecodedText:
    return decode_text_bytes(path.read_bytes(), source=path.name, reject_mojibake=reject_mojibake)


def correct_common_zh_asr_text(value: str) -> str:
    text = canonicalize_unicode_text(value)
    for wrong, correct in COMMON_ZH_ASR_REPLACEMENTS.items():
        text = text.replace(wrong, correct)
    return text


def correct_transcript_terms(transcript: TranscriptResult) -> TranscriptResult:
    if not transcript.segments and not transcript.full_text:
        return transcript
    # Local speech decoding may emit a replacement token for an uncertain word.
    # Preserve the raw artifact upstream, mark sparse uncertainty visibly, and
    # keep imported text and widespread corruption subject to the strict gate.
    raw_text = "\n".join(segment.text for segment in transcript.segments) if transcript.segments else transcript.full_text
    missing = raw_text.count("\ufffd")
    if transcript.source == "faster-whisper" and 0 < missing <= 10 and missing / max(1, len(raw_text)) <= 0.01:
        locations = [f"{int(segment.start) // 60:02d}:{int(segment.start) % 60:02d}" for segment in transcript.segments if "\ufffd" in segment.text]
        warning = f"本地语音识别有 {missing} 处字符无法确定，已标记为【识别不清】，请核对原音频" + ("（" + "、".join(locations) + "）" if locations else "") + "。"
        transcript = transcript.model_copy(update={
            "segments": [segment.model_copy(update={"text": segment.text.replace("\ufffd", "【识别不清】")}) for segment in transcript.segments],
            "full_text": transcript.full_text.replace("\ufffd", "【识别不清】"),
            "warning": "\n".join(filter(None, [transcript.warning, warning])),
        })
    segments = [
        segment.model_copy(update={"text": correct_common_zh_asr_text(segment.text)})
        for segment in transcript.segments
    ]
    full_text = "\n".join(segment.text for segment in segments) if segments else correct_common_zh_asr_text(transcript.full_text)
    return transcript.model_copy(update={"segments": segments, "full_text": full_text})


__all__ = [
    "DecodedText",
    "TEXT_NORMALIZATION_VERSION",
    "TextDecodingError",
    "canonicalize_unicode_text",
    "correct_common_zh_asr_text",
    "correct_transcript_terms",
    "decode_text_bytes",
    "declared_text_encoding",
    "mojibake_score",
    "read_canonical_text",
    "redact_sensitive_url_values",
]
