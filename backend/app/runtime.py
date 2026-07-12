from __future__ import annotations

import os
import shutil
import subprocess
import sys


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


def hidden_subprocess_kwargs() -> dict:
    """Prevent command windows from flashing when launched by the desktop GUI."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }
