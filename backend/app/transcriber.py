from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

from .config import DEFAULT_WHISPER_COMPUTE_TYPE, DEFAULT_WHISPER_DEVICE, LLM_API_KEY, LLM_BASE_URL, configure_local_caches
from .models import TaskOptions, TranscriptResult, TranscriptSegment


TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{1,3})\s+-->\s+(?P<end>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{1,3})"
)
LOCAL_ASR_MODELS = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}
MAX_ASR_ERROR_MESSAGE = 240


def _remote_asr_base_host(base_url: str) -> str:
    parsed = urlparse(base_url or "")
    return parsed.netloc or parsed.path.strip("/") or ""


def _remote_asr_provider(options: TaskOptions) -> str:
    selected = str(options.transcriber or "").strip().lower()
    if selected in {"groq", "groq-asr"}:
        return "groq"
    host = (_remote_asr_base_host(options.llm_base_url or LLM_BASE_URL)).lower()
    if "groq.com" in host:
        return "groq"
    if "openai.com" in host:
        return "openai"
    if "dashscope.aliyuncs.com" in host:
        return "dashscope"
    if "siliconflow.cn" in host:
        return "siliconflow"
    if "openrouter.ai" in host:
        return "openrouter"
    if host in {"127.0.0.1", "localhost"}:
        return "local-openai-compatible"
    return "openai-compatible"


def _remote_asr_model(options: TaskOptions) -> str:
    model = options.whisper_model or "whisper-1"
    return "whisper-1" if model in LOCAL_ASR_MODELS else model


def _remote_asr_source(options: TaskOptions) -> str:
    return "groq-asr" if _remote_asr_provider(options) == "groq" else "openai-compatible-asr"


def _safe_asr_error(exc: BaseException) -> str:
    message = re.sub(r"\s+", " ", str(exc or "")).strip()
    message = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-<redacted>", message)
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer <redacted>", message)
    message = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[A-Za-z0-9._~+/=-]{8,}", r"\1<redacted>", message)
    if len(message) > MAX_ASR_ERROR_MESSAGE:
        message = message[:MAX_ASR_ERROR_MESSAGE].rstrip() + "..."
    return message or exc.__class__.__name__


def _remote_asr_warning(options: TaskOptions, stage: str, code: str, reason: str = "") -> str:
    base_url = options.llm_base_url or LLM_BASE_URL
    return (
        f"Remote ASR failed: provider={_remote_asr_provider(options)}, "
        f"model={_remote_asr_model(options)}, base={_remote_asr_base_host(base_url) or '-'}, "
        f"stage={stage}, code={code}, reason={reason or '-'}."
    )


def _parse_timestamp(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def transcript_from_subtitle(path: Path, source: str = "page-subtitle") -> TranscriptResult:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    normalized = re.sub(r"\r+\n", "\n", text)
    normalized = re.sub(r"\r+", "\n", normalized)
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines or lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
            continue
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if time_index < 0:
            continue
        match = TIMESTAMP_RE.search(lines[time_index])
        if not match:
            continue
        cue_text = " ".join(
            re.sub(r"<[^>]+>", "", line).strip()
            for line in lines[time_index + 1:]
            if not line.startswith(("NOTE", "STYLE", "REGION"))
        ).strip()
        if not cue_text:
            continue
        cue_text = re.sub(r"\s+", " ", cue_text)
        if segments and segments[-1].text == cue_text:
            segments[-1].end = _parse_timestamp(match.group("end"))
            continue
        segments.append(
            TranscriptSegment(
                start=_parse_timestamp(match.group("start")),
                end=_parse_timestamp(match.group("end")),
                text=cue_text,
            )
        )
    return TranscriptResult(
        language="unknown",
        source=source,
        segments=segments,
        full_text="\n".join(segment.text for segment in segments),
        warning="" if segments else "字幕文件存在，但未解析出有效字幕片段。",
    )


def transcribe_audio(audio_path: Path, model_size: str = "small") -> TranscriptResult:
    configure_local_caches()
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return TranscriptResult(
            language="unknown",
            source="missing-faster-whisper",
            warning="未安装 faster-whisper；请执行 `pip install faster-whisper` 后重试以获得真实转写。",
            segments=[
                TranscriptSegment(
                    start=0,
                    end=0,
                    text="未安装 faster-whisper，当前任务没有生成真实字幕。仍可根据画面帧生成基础笔记。",
                )
            ],
            full_text="未安装 faster-whisper，当前任务没有生成真实字幕。仍可根据画面帧生成基础笔记。",
        )

    try:
        model = WhisperModel(model_size, device=DEFAULT_WHISPER_DEVICE, compute_type=DEFAULT_WHISPER_COMPUTE_TYPE)
        segments_iter, info = model.transcribe(str(audio_path), vad_filter=True)
        segments: list[TranscriptSegment] = []
        for item in segments_iter:
            text = item.text.strip()
            if text:
                segments.append(TranscriptSegment(start=float(item.start), end=float(item.end), text=text))
        return TranscriptResult(
            language=getattr(info, "language", "unknown") or "unknown",
            source="faster-whisper",
            segments=segments,
            full_text="\n".join(seg.text for seg in segments),
        )
    except Exception as exc:
        return TranscriptResult(
            language="unknown",
            source="faster-whisper-error",
            warning=f"faster-whisper 转写失败：{exc}",
            segments=[
                TranscriptSegment(start=0, end=0, text=f"转写失败：{exc}")
            ],
            full_text=f"转写失败：{exc}",
        )


def _response_value(response, key: str, default=None):
    if isinstance(response, dict):
        return response.get(key, default)
    return getattr(response, key, default)


def _segments_from_remote_response(response) -> list[TranscriptSegment]:
    raw_segments = _response_value(response, "segments", []) or []
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        text = str(_response_value(item, "text", "") or "").strip()
        if not text:
            continue
        start = float(_response_value(item, "start", 0) or 0)
        end = float(_response_value(item, "end", start) or start)
        segments.append(TranscriptSegment(start=max(0, start), end=max(start, end), text=text))
    if segments:
        return segments
    text = str(_response_value(response, "text", "") or "").strip()
    return [TranscriptSegment(start=0, end=0, text=text)] if text else []


def transcribe_audio_openai_compatible(audio_path: Path, options: TaskOptions) -> TranscriptResult:
    api_key = options.llm_api_key or LLM_API_KEY
    source = _remote_asr_source(options)
    if not api_key:
        return TranscriptResult(
            language="unknown",
            source=f"{source}-missing-key",
            warning=_remote_asr_warning(options, "configuration", "missing_api_key", "API key is not configured"),
            segments=[TranscriptSegment(start=0, end=0, text="未配置远程 ASR API Key，当前任务没有生成真实字幕。")],
            full_text="未配置远程 ASR API Key，当前任务没有生成真实字幕。",
        )

    model = _remote_asr_model(options)

    try:
        from openai import OpenAI
    except Exception as exc:
        return TranscriptResult(
            language="unknown",
            source=f"{source}-missing-sdk",
            warning=_remote_asr_warning(options, "client_import", "missing_openai_sdk", _safe_asr_error(exc)),
            segments=[TranscriptSegment(start=0, end=0, text="未安装 openai SDK，当前任务没有生成远程 ASR 字幕。")],
            full_text="未安装 openai SDK，当前任务没有生成远程 ASR 字幕。",
        )

    try:
        client = OpenAI(api_key=api_key, base_url=options.llm_base_url or LLM_BASE_URL)
        with audio_path.open("rb") as audio_file:
            try:
                response = client.audio.transcriptions.create(
                    file=audio_file,
                    model=model,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            except Exception:
                audio_file.seek(0)
                try:
                    response = client.audio.transcriptions.create(
                        file=audio_file,
                        model=model,
                        response_format="verbose_json",
                    )
                except Exception:
                    audio_file.seek(0)
                    response = client.audio.transcriptions.create(
                        file=audio_file,
                        model=model,
                    )
        segments = _segments_from_remote_response(response)
        text = "\n".join(segment.text for segment in segments) or str(_response_value(response, "text", "") or "").strip()
        return TranscriptResult(
            language=str(_response_value(response, "language", "unknown") or "unknown"),
            source=source,
            segments=segments,
            full_text=text,
            warning="" if segments else "远程 ASR 已返回，但没有解析出有效字幕片段。",
        )
    except Exception as exc:
        reason = _safe_asr_error(exc)
        return TranscriptResult(
            language="unknown",
            source=f"{source}-error",
            warning=_remote_asr_warning(options, "transcription", "api_error", reason),
            segments=[TranscriptSegment(start=0, end=0, text=f"远程 ASR 转写失败：{reason}")],
            full_text=f"远程 ASR 转写失败：{reason}",
        )
