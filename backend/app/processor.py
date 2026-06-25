from __future__ import annotations

import json
import shutil
from pathlib import Path

from .downloader import DownloadError, MediaDownloader
from .media import build_frame_grids, extract_audio, extract_frames, normalize_video
from .models import CurrentPageTaskRequest, TaskOptions, TranscriptResult, model_dump_jsonable
from .storage import get_task, save_task, task_dir, update_task, write_json
from .summarizer import summarize, summarize_page_text
from .transcriber import transcribe_audio


def _fail(task_id: str, code: str, detail: str) -> None:
    update_task(
        task_id,
        status="failed",
        phase="failed",
        progress=100,
        error_code=code,
        error_detail=detail,
        message=detail,
    )


def process_page_text_task(task_id: str, request: CurrentPageTaskRequest) -> None:
    try:
        update_task(task_id, status="running", phase="summarizing", progress=60, message="正在总结当前页面文本")
        note = summarize_page_text(request.title, request.page_url, request.page_text, request.options)
        note_path = task_dir(task_id) / "note.md"
        note_path.write_text(note, encoding="utf-8")
        update_task(task_id, status="success", phase="completed", progress=100, message="页面文本总结完成", note_path=str(note_path))
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def process_current_page_task(task_id: str, request: CurrentPageTaskRequest) -> None:
    write_json(task_id, "request.json", request.model_dump(mode="json"))
    if request.mode == "page_text":
        process_page_text_task(task_id, request)
        return

    work_dir = task_dir(task_id)
    try:
        update_task(task_id, status="running", phase="downloading", progress=10, message="正在解析并下载当前页视频")
        downloader = MediaDownloader(work_dir)
        media_path, selected = downloader.download(request.page_url, request.resources, request.cookies, request.title)
        if selected:
            update_task(task_id, selected_resource=selected)

        _process_video_file(
            task_id=task_id,
            input_path=media_path,
            title=request.title,
            page_url=request.page_url,
            options=request.options,
        )
    except DownloadError as exc:
        _fail(task_id, exc.code, exc.message)
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def process_local_video_task(task_id: str, input_path: Path, title: str, options: TaskOptions) -> None:
    try:
        _process_video_file(task_id=task_id, input_path=input_path, title=title, page_url="", options=options)
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def _process_video_file(task_id: str, input_path: Path, title: str, page_url: str, options: TaskOptions) -> None:
    work_dir = task_dir(task_id)
    update_task(task_id, status="running", phase="processing_video", progress=25, message="正在标准化视频")

    normalized = work_dir / "media.mp4"
    if input_path.suffix.lower() == ".mp4":
        if input_path.resolve() != normalized.resolve():
            shutil.copy2(input_path, normalized)
    else:
        normalize_video(input_path, normalized)
    update_task(task_id, media_path=str(normalized))

    update_task(task_id, phase="processing_video", progress=38, message="正在提取音频")
    audio_path = work_dir / "audio.wav"
    extract_audio(normalized, audio_path)
    update_task(task_id, audio_path=str(audio_path))

    update_task(task_id, phase="transcribing", progress=52, message="正在转写音频")
    transcript = transcribe_audio(audio_path, options.whisper_model)
    transcript_path = work_dir / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    update_task(task_id, transcript_path=str(transcript_path))

    grids = []
    if options.visual_understanding:
        update_task(task_id, phase="extracting_frames", progress=68, message="正在抽帧并生成画面网格")
        frame_dir = work_dir / "frames"
        grid_dir = work_dir / "grids"
        frames = extract_frames(normalized, frame_dir, max(1, options.frame_interval))
        grids = build_frame_grids(task_id, frames, grid_dir, max(1, options.grid_columns), max(1, options.grid_rows), max(1, options.frame_interval))

    record = get_task(task_id)
    record.frame_grids = grids
    save_task(record)

    update_task(task_id, phase="summarizing", progress=84, message="正在生成 Markdown 笔记")
    note = summarize(title, transcript, grids, options, page_url)
    note_path = work_dir / "note.md"
    note_path.write_text(note, encoding="utf-8")

    update_task(
        task_id,
        status="success",
        phase="completed",
        progress=100,
        message="任务完成",
        note_path=str(note_path),
    )


def read_transcript(task_id: str) -> dict:
    record = get_task(task_id)
    path = Path(record.transcript_path)
    if not path.exists():
        return TranscriptResult().model_dump(mode="json")
    return json.loads(path.read_text(encoding="utf-8"))


def read_note(task_id: str) -> str:
    record = get_task(task_id)
    path = Path(record.note_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
