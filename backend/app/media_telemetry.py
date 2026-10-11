"""Conservative telemetry exclusion for caller-supplied media candidates."""
import re
from urllib.parse import unquote, urlparse


def is_telemetry_endpoint(url: str) -> bool:
    try:
        path = unquote(urlparse(url).path).lower()
    except (TypeError, ValueError):
        return False
    # Keep actual media files, even when a course/directory uses these words.
    if re.search(r"\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)$", path):
        return False
    return bool(re.search(r"(?:^|/)(?:heartbeat|beacon|telemetry|analytics|click-interface)(?:/|$)", path))
