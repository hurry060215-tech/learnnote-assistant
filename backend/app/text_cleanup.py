from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from charset_normalizer import from_bytes

from .models import TranscriptResult


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


def _decode_candidates(content: bytes) -> list[tuple[str, str]]:
    if not content:
        return [("utf-8", "")]
    candidates: list[tuple[str, str]] = []
    if content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encodings = ("utf-32",)
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    elif content.startswith(b"\xef\xbb\xbf"):
        encodings = ("utf-8-sig",)
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
        encodings = tuple(dict.fromkeys(
            encoding
            for encoding in (
                "utf-8",
                preferred_detected,
                "gb18030",
                detected,
                "utf-16-le" if len(content) % 2 == 0 else "",
                "utf-16-be" if len(content) % 2 == 0 else "",
                "cp932",
                "shift_jis",
                "cp1252",
            )
            if encoding
        ))
    for encoding in encodings:
        try:
            candidates.append((encoding, content.decode(encoding, errors="strict")))
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


def decode_text_bytes(content: bytes, *, source: str = "", reject_mojibake: bool = True) -> DecodedText:
    """Decode common subtitle encodings strictly; never discard invalid bytes."""

    decoded: list[tuple[int, int, DecodedText]] = []
    for priority, (encoding, raw_text) in enumerate(_decode_candidates(bytes(content or b""))):
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
                encoding=encoding,
                repaired=repaired,
                mojibake_score=mojibake_score(text),
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
    return best


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
    segments = [
        segment.model_copy(update={"text": correct_common_zh_asr_text(segment.text)})
        for segment in transcript.segments
    ]
    full_text = "\n".join(segment.text for segment in segments) if segments else correct_common_zh_asr_text(transcript.full_text)
    return transcript.model_copy(update={"segments": segments, "full_text": full_text})


__all__ = [
    "DecodedText",
    "TextDecodingError",
    "canonicalize_unicode_text",
    "correct_common_zh_asr_text",
    "correct_transcript_terms",
    "decode_text_bytes",
    "mojibake_score",
    "read_canonical_text",
    "redact_sensitive_url_values",
]
