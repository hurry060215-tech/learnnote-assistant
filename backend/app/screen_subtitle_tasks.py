"""A separate opt-in OCR task on already-owned media; never invokes ASR/download."""
from __future__ import annotations

from pathlib import Path
import json
import re
import time
from uuid import uuid4

from .models import TaskOptions
from .pipeline_progress import start_pipeline_attempt, finish_pipeline_attempt, record_stage_duration
from .processor_state import check_cancel, fail_task, TaskCancelled, start_task_resource_monitor, persist_task_resource_usage
from .reading_notes import stamp
from .screen_subtitles import extract, as_transcript, WARNING, ScreenOcrError
from .storage import atomic_write_text, get_task, mark_task_cancelled, task_dir, update_task, write_json
from .storage import _lock as _task_data_lock


def _prior_media_identity(task_id, root):
    # Ordinary task hashes can describe the input before normalization. This
    # separate identity is bound only when OCR starts decoding this media.
    identity = get_task(task_id).screen_subtitles_media_sha256
    report = root / "screen_subtitles.json"
    damaged = None
    if report.is_file():
        raw = report.read_bytes()
        try:
            payload = json.loads(raw)
            reported = payload.get("media_sha256") if isinstance(payload, dict) else None
            if not isinstance(reported, str) or not re.fullmatch(r"[a-f0-9]{64}", reported):
                raise ValueError("checkpoint_identity_missing")
        except (ValueError, UnicodeError):
            damaged = raw
        else:
            if identity and identity != reported:
                raise ScreenOcrError("checkpoint_identity_conflict")
            identity = reported
    if not identity and (damaged is not None or any((root / "screen-subtitles-cache").glob("*/window-*.json"))):
        raise ScreenOcrError("checkpoint_identity_missing")
    if damaged is not None:
        with (root / f"screen_subtitles.corrupt-{uuid4().hex}.json").open("xb") as backup:
            backup.write(damaged)
    return identity or None


def _srt_stamp(value):
    milliseconds = round(max(0, value) * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def process_screen_subtitle_task(task_id: str, media_path: Path, options: TaskOptions):
    resource_monitor, resource_started = start_task_resource_monitor(task_id)
    attempt = None
    latest = None
    started = time.monotonic()
    try:
        check_cancel(task_id)
        if options.screen_subtitles is None:
            raise ValueError("screen_subtitle_settings_missing")
        attempt = start_pipeline_attempt(task_id)
        update_task(task_id, status="running", phase="extracting_frames", progress=1,
                    message="正在校验已保存的视频并提取画面字幕；可取消后从已验证窗口恢复。")
        for stage in ("download", "media"):
            record_stage_duration(task_id, stage, time.monotonic(), status="skipped", expected_attempt_id=attempt)
        root = task_dir(task_id)
        expected_hash = _prior_media_identity(task_id, root)

        def save_progress(report):
            nonlocal latest
            latest = report
            write_json(task_id, "screen_subtitles.json", report)
            if report["completed_windows"] == 0:
                record = get_task(task_id)
                integrity = record.media_integrity.model_copy(update={"duration": report["media"]["duration"],
                    "sha256": report["media_sha256"], "file_size": media_path.stat().st_size, "has_video": True})
                integrity_path = write_json(task_id, "media_integrity.json", integrity.model_dump(mode="json"))
                update_task(task_id, media_integrity=integrity, media_integrity_path=str(integrity_path),
                    screen_subtitles_media_sha256=report["media_sha256"],
                    source_identity=record.source_identity.model_copy(update={"media_sha256": report["media_sha256"]}))
            done, total = report["completed_windows"], report["total_windows"]
            update_task(task_id, progress=min(75, 1 + int(74 * done / max(1, total))),
                        checkpoint="screen_subtitles_partial", message=f"画面字幕：已完成 {done}/{total} 个窗口，复用 {report['cache_hits']} 个；识别结果仍待核对。")

        report = extract(media_path, options.screen_subtitles, root / "screen-subtitles-cache",
                         cancel_check=lambda: check_cancel(task_id), progress=save_progress, expected_media_sha256=expected_hash)
        check_cancel(task_id)
        transcript = as_transcript(report)
        source_record = get_task(task_id)
        transcript.provenance.update({"source_task_id": source_record.source_task_id,
            "learning_range": source_record.learning_range,
            "timestamp_origin": "selected_media_start", "original_time_offset": source_record.learning_range.get("original_start", source_record.learning_range.get("start", 0))})
        if source_record.learning_range:
            original_start = source_record.learning_range.get("original_start", source_record.learning_range.get("start", 0))
            transcript.warning += f" 本片段时间从 0 秒起，对应原视频 {original_start:g} 秒；原视频时间 = 本片段时间 + {original_start:g} 秒。"
        transcript_path = write_json(task_id, "transcript.json", transcript.model_dump(mode="json"))
        srt = "\n\n".join(f"{index}\n{_srt_stamp(cue['start'])} --> {_srt_stamp(cue['end'])}\n{cue['text']}" for index, cue in enumerate(report["cues"], 1))
        subtitle_path = root / "screen_subtitles.srt"
        atomic_write_text(subtitle_path, srt + "\n")
        note_path = root / "screen_subtitles.md"
        lines = [f"# {get_task(task_id).title}", "", f"> {transcript.warning}", "",
                 f"抽样覆盖：{report['coverage']['sampled_seconds']:.1f}/{report['coverage']['requested_seconds']:.1f} 秒；间隔 {options.screen_subtitles.interval_seconds:g} 秒。仅表示已处理抽样窗口，不表示全部字幕已被识别。", ""]
        lines.extend(f"`{stamp(cue['start'])}–{stamp(cue['end'])}` {cue['text']}\n" for cue in report["cues"])
        atomic_write_text(note_path, "\n".join(lines) + "\n")
        check_cancel(task_id)
        update_task(task_id, transcript_path=str(transcript_path), subtitle_path=str(subtitle_path),
                    note_path=str(note_path), media_path=str(media_path), summary_source="screen-ocr-extract", summary_warning=WARNING)
        record_stage_duration(task_id, "transcript", started, status="completed" if report["status"] == "ready" else "failed", expected_attempt_id=attempt)
        if report["status"] != "ready":
            code = "screen_ocr_empty" if report["status"] == "empty" else "screen_ocr_incomplete"
            message = "未识别出所选语言的画面字幕；请预览并调整裁剪/语言。未调用音频转写或生成笔记。" if code == "screen_ocr_empty" else "画面字幕提取未覆盖完整视频；已保留完成窗口和部分结果，可恢复。未调用音频转写或生成笔记。"
            fail_task(task_id, code, message)
            return
        update_task(task_id, checkpoint="transcript_ready")
        if options.content_mode == "text":
            # The caller explicitly selected note generation. Existing configured
            # note generation is the only provider route, after complete OCR.
            from .processor import process_saved_transcript_task
            finish_pipeline_attempt(task_id, "completed", expected_attempt_id=attempt)
            attempt = None
            process_saved_transcript_task(task_id, options)
        else:
            with _task_data_lock:
                check_cancel(task_id)
                update_task(task_id, status="success", phase="completed", progress=100, checkpoint="transcript_ready",
                            error_code="", error_detail="", message="画面字幕抽样提取完成，未调用文字模型；请核对识别结果。")
    except TaskCancelled:
        if latest is not None:
            latest["status"] = "cancelled"
            write_json(task_id, "screen_subtitles.json", latest)
        mark_task_cancelled(task_id)
    except Exception as exc:
        if latest is not None:
            latest["status"] = "partial" if latest["completed_windows"] else "failed"
            write_json(task_id, "screen_subtitles.json", latest)
        if isinstance(exc, ScreenOcrError) and str(exc) == "media_changed":
            fail_task(task_id, "screen_ocr_media_changed", "原媒体内容已变化，不能恢复这份画面字幕任务。原结果已保留，请为当前视频创建新任务。")
        else:
            fail_task(task_id, "screen_ocr_failed", "画面字幕提取失败；已保留完成窗口。请检查本地 OCR 组件和裁剪设置后恢复。未自动下载、转写或调用模型。")
    finally:
        persist_task_resource_usage(task_id, resource_monitor, resource_started)
        if attempt is not None:
            task = get_task(task_id)
            finish_pipeline_attempt(task_id, "completed" if task.status == "success" else "cancelled" if task.status == "cancelled" else "failed", expected_attempt_id=attempt)
