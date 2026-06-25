from __future__ import annotations

import os
import shutil


def ffmpeg_bin() -> str | None:
    env_path = os.getenv("FFMPEG_BIN_PATH")
    if env_path:
        return env_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffprobe_bin() -> str | None:
    env_path = os.getenv("FFPROBE_BIN_PATH")
    if env_path:
        return env_path
    return shutil.which("ffprobe")
