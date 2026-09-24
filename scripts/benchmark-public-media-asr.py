from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import shutil
import threading
import time
from pathlib import Path

import wave
from app.asr_chunks import CHUNK_SECONDS
from app.config import DEFAULT_WHISPER_COMPUTE_TYPE, DEFAULT_WHISPER_DEVICE, MODEL_CACHE_DIR
from app.transcriber import transcribe_audio


class ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def rss_bytes() -> int:
    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("Psapi.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCountersEx), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return int(counters.WorkingSetSize)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="tiny")
    args = parser.parse_args()
    audio_path = args.audio.resolve(strict=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        audio_sample_rate = audio.getframerate()
        audio_channels = audio.getnchannels()

    stop_sampling = threading.Event()
    samples: list[dict[str, float | int]] = []
    first_result: list[float] = []
    process_start = time.monotonic()

    def sample() -> None:
        previous_wall = time.monotonic()
        previous_cpu = time.process_time()
        while not stop_sampling.wait(1):
            current_wall = time.monotonic()
            current_cpu = time.process_time()
            cpu = 100 * (current_cpu - previous_cpu) / max(0.001, current_wall - previous_wall)
            previous_wall, previous_cpu = current_wall, current_cpu
            try:
                samples.append({
                    "elapsed_seconds": current_wall - process_start,
                    "rss_bytes": rss_bytes(),
                    "cpu_percent": cpu,
                    "free_disk_bytes": shutil.disk_usage(audio_path.parent).free,
                })
            except OSError:
                continue

    def progress(seconds: float, phase: str) -> None:
        if phase == "transcribing" and seconds > 0 and not first_result:
            first_result.append(time.monotonic() - process_start)

    sampler = threading.Thread(target=sample, name="learnnote-asr-resource-sampler", daemon=True)
    sampler.start()
    try:
        transcript = transcribe_audio(audio_path, args.model, progress_callback=progress)
    finally:
        stop_sampling.set()
        sampler.join(timeout=3)

    elapsed = time.monotonic() - process_start
    free_values = [int(item["free_disk_bytes"]) for item in samples]
    segments = transcript.segments
    status = "pass" if transcript.source == "faster-whisper" and bool(segments) else "fail"
    report = {
        "status": status,
        "pipeline": "LearnNote transcribe_audio with 300-second resumable WAV windows",
        "input": audio_path.name,
        "input_sha256": sha256(audio_path),
        "input_bytes": audio_path.stat().st_size,
        "input_duration_seconds": round(duration, 3),
        "sample_rate_hz": audio_sample_rate,
        "channels": audio_channels,
        "model": args.model,
        "device": DEFAULT_WHISPER_DEVICE,
        "compute_type": DEFAULT_WHISPER_COMPUTE_TYPE,
        "model_cache": str(MODEL_CACHE_DIR),
        "chunk_seconds": CHUNK_SECONDS,
        "chunk_count": math.ceil(duration / CHUNK_SECONDS) if duration > 600 else 1,
        "first_segment_seconds": round(first_result[0], 3) if first_result else None,
        "total_process_seconds": round(elapsed, 3),
        "real_time_factor": round(duration / elapsed, 3) if elapsed else None,
        "language": transcript.language,
        "transcript_segment_count": len(segments),
        "transcript_character_count": len(transcript.full_text),
        "last_transcribed_end_seconds": round(max((float(item.end) for item in segments), default=0), 3),
        "warning": transcript.warning,
        "resource_usage": {
            "sample_count": len(samples),
            "rss_peak_bytes": max((int(item["rss_bytes"]) for item in samples), default=0),
            "process_cpu_percent_mean": round(sum(float(item["cpu_percent"]) for item in samples) / len(samples), 2) if samples else 0,
            "process_cpu_percent_peak": round(max((float(item["cpu_percent"]) for item in samples), default=0), 2),
            "disk_free_before_bytes": free_values[0] if free_values else None,
            "disk_free_min_bytes": min(free_values) if free_values else None,
            "disk_free_after_bytes": free_values[-1] if free_values else None,
        },
        "provider_api_calls": 0,
        "transcript_text_saved": False,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
