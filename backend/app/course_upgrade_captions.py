"""Fail-closed caption scope for explicitly reviewed course visual children."""
import hashlib
import json
import math

from . import storage
from .models import BrowserSubtitleCue
from .processor_state import ContentMismatchError


def reviewed_captions(task_id):
    """Return immutable reviewed cues, or None for ordinary processing routes."""
    task = storage.get_task(task_id)
    if not task.handoff_id.startswith('episode-upgrade-'):
        return None
    root = storage.TASK_DIR / task_id
    try:
        review_path = root / 'course-upgrade-review.json'
        caption_path = root / 'course-upgrade-captions.json'
        if root.is_symlink() or review_path.is_symlink() or caption_path.is_symlink():
            raise ValueError('caption artifact must be owned')
        review = json.loads(review_path.read_text(encoding='utf-8'))
        if caption_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('caption artifact too large')
        raw = caption_path.read_bytes()
        if (review.get('source_task_id') != task.source_task_id
                or review.get('source_url') != task.page_url
                or hashlib.sha256(raw).hexdigest() != review.get('caption_sha256')):
            raise ValueError('reviewed caption identity changed')
        cues = [BrowserSubtitleCue.model_validate(item) for item in json.loads(raw)]
        if not 1 <= len(cues) <= 20000 or any(
                not math.isfinite(c.start) or not math.isfinite(c.end)
                or c.start < 0 or c.end <= c.start or not c.text.strip() for c in cues):
            raise ValueError('invalid reviewed captions')
        return cues
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ContentMismatchError('Reviewed course captions are unavailable or changed; no alternate subtitles or audio transcription are authorized.') from exc


def require_reviewed_coverage(cues, duration, is_reliable):
    # Match physical-media range admission's 0.01s encoding/probe allowance.
    # Coverage ratios alone accept a long old transcript over truncated media;
    # never clip or rescale reviewed evidence to make a new source fit.
    if (not math.isfinite(duration) or duration <= 0
            or any(cue.end > duration + 0.01 for cue in cues)
            or not is_reliable(cues, duration)):
        raise ContentMismatchError(
            'Reviewed course captions do not cover the downloaded media; alternate subtitles and audio transcription require a separate action.')
