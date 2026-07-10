from __future__ import annotations

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


def correct_common_zh_asr_text(value: str) -> str:
    text = str(value or "")
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
