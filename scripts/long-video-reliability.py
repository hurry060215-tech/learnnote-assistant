from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.media import build_frame_grids, extract_frames_adaptive, probe_media_integrity  # noqa: E402
from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs  # noqa: E402


def run_checked(command: list[str], description: str) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        **hidden_subprocess_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-1200:]
        raise RuntimeError(f"{description} failed with code {result.returncode}: {detail}")


def generate_synthetic_media(path: Path, duration_seconds: int) -> None:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for the long-video reliability gate.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial.mp4")
    temporary.unlink(missing_ok=True)
    run_checked(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000",
            "-t",
            str(duration_seconds),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "35",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "60",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(temporary),
        ],
        "synthetic media generation",
    )
    temporary.replace(path)


def media_matches_requested_duration(path: Path, duration_seconds: int, tolerance_seconds: float) -> bool:
    integrity = probe_media_integrity(path)
    return (
        integrity.status == "ready"
        and integrity.has_video
        and integrity.has_audio
        and abs(integrity.duration - duration_seconds) <= tolerance_seconds
    )


def default_output_dir() -> Path:
    if os.name == "nt" and Path("D:/").exists():
        return Path("D:/LearnNoteReliability/long-video")
    return ROOT / "data" / "test-runs" / "long-video-reliability"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise LearnNote's media probe, adaptive frame extraction, and grid pipeline without ASR or LLM calls."
    )
    parser.add_argument("--media", type=Path, help="Reuse an existing media file instead of generating synthetic media.")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--frame-interval", type=int, default=120)
    parser.add_argument("--max-frames", type=int, default=40)
    parser.add_argument("--grid-columns", type=int, default=3)
    parser.add_argument("--grid-rows", type=int, default=3)
    parser.add_argument("--scene-threshold", type=float, default=0.30)
    parser.add_argument("--duration-tolerance", type=float, default=3.0)
    parser.add_argument("--regenerate", action="store_true", help="Regenerate the cached synthetic media.")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    if args.duration_seconds < 5:
        parser.error("--duration-seconds must be at least 5.")
    if args.frame_interval < 1 or args.max_frames < 2:
        parser.error("--frame-interval must be >= 1 and --max-frames must be >= 2.")
    if args.grid_columns < 1 or args.grid_rows < 1:
        parser.error("Grid dimensions must be positive.")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = output_dir / "frames"
    grid_dir = output_dir / "grids"
    report_path = output_dir / "report.json"
    media_path = (
        args.media.expanduser().resolve()
        if args.media
        else output_dir / f"synthetic-{args.duration_seconds}s.mp4"
    )
    generated = not args.media

    started = time.monotonic()
    try:
        if args.media:
            if not media_path.is_file():
                raise RuntimeError(f"Media file does not exist: {media_path}")
        elif (
            args.regenerate
            or not media_path.is_file()
            or not media_matches_requested_duration(media_path, args.duration_seconds, args.duration_tolerance)
        ):
            generate_synthetic_media(media_path, args.duration_seconds)

        integrity = probe_media_integrity(media_path)
        if integrity.status != "ready" or not integrity.has_video or not integrity.has_audio:
            raise RuntimeError(
                f"Media integrity failed: status={integrity.status}, "
                f"video={integrity.has_video}, audio={integrity.has_audio}, "
                f"reasons={integrity.blocking_reasons}"
            )
        if generated and abs(integrity.duration - args.duration_seconds) > args.duration_tolerance:
            raise RuntimeError(
                f"Synthetic duration mismatch: expected {args.duration_seconds}s, got {integrity.duration:.3f}s."
            )
        if not generated and integrity.duration + args.duration_tolerance < args.duration_seconds:
            raise RuntimeError(
                f"Reused media is too short for this gate: required at least "
                f"{args.duration_seconds - args.duration_tolerance:.1f}s, got {integrity.duration:.3f}s."
            )

        shutil.rmtree(frame_dir, ignore_errors=True)
        shutil.rmtree(grid_dir, ignore_errors=True)
        frames, samples = extract_frames_adaptive(
            media_path,
            frame_dir,
            interval=args.frame_interval,
            max_frames=args.max_frames,
            scene_threshold=args.scene_threshold,
        )
        if len(frames) < 2:
            raise RuntimeError(f"Frame extraction produced only {len(frames)} frame(s).")
        timestamps = [float(sample.timestamp) for sample in samples]
        if min(timestamps) > max(1, args.frame_interval):
            raise RuntimeError("Frame extraction did not cover the beginning of the media.")
        tail_tolerance = max(args.frame_interval * 1.5, 5)
        if max(timestamps) < integrity.duration - tail_tolerance:
            raise RuntimeError(
                f"Frame extraction did not cover the tail: last={max(timestamps):.1f}s, "
                f"duration={integrity.duration:.1f}s."
            )

        grids = build_frame_grids(
            "long-video-reliability",
            frames,
            grid_dir,
            columns=args.grid_columns,
            rows=args.grid_rows,
            interval=args.frame_interval,
            media_duration=integrity.duration,
        )
        if not grids or any(not Path(grid.path).is_file() for grid in grids):
            raise RuntimeError("Frame grid generation did not produce valid grid files.")

        report = {
            "status": "pass",
            "mode": "media-and-frames-only",
            "api_calls": 0,
            "transcription_attempted": False,
            "media": str(media_path),
            "generated": generated,
            "duration_seconds": integrity.duration,
            "file_size": integrity.file_size,
            "sha256": integrity.sha256,
            "probe_backend": integrity.probe_backend,
            "video_codec": integrity.video_codec,
            "audio_codec": integrity.audio_codec,
            "frame_interval": args.frame_interval,
            "frame_count": len(frames),
            "first_frame_seconds": min(timestamps),
            "last_frame_seconds": max(timestamps),
            "grid_count": len(grids),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {
            "status": "fail",
            "mode": "media-and-frames-only",
            "api_calls": 0,
            "transcription_attempted": False,
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        report_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if not args.keep_artifacts:
            shutil.rmtree(frame_dir, ignore_errors=True)
            shutil.rmtree(grid_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
