"""Bound long WAV transcription memory and checkpoint completed audio windows."""
from __future__ import annotations

import gc
import hashlib
import json
import math
from pathlib import Path
import wave

from .models import TranscriptResult, TranscriptSegment
from .storage import atomic_write_text

CHUNK_SECONDS = 300


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), 'rb') as audio:
            return audio.getnframes() / audio.getframerate()
    except (OSError, wave.Error, EOFError):
        return 0


def transcribe_windows(audio_path, model_factory, model_identity, progress_callback=None):
    audio_path = Path(audio_path)
    with audio_path.open('rb') as stream:
        audio_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    checkpoint_dir = audio_path.parent / 'asr-checkpoints'
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256((audio_hash + '|' + model_identity + '|300').encode()).hexdigest()
    segments = []
    language = 'unknown'
    with wave.open(str(audio_path), 'rb') as audio:
        rate, total = audio.getframerate(), audio.getnframes()
        for start in range(0, total, rate * CHUNK_SECONDS):
            end = min(total, start + rate * CHUNK_SECONDS)
            offset = start / rate
            checkpoint = checkpoint_dir / f'{start:012d}.json'
            if progress_callback:
                progress_callback(offset, 'transcribing')
            cached = None
            try:
                cached = json.loads(checkpoint.read_text(encoding='utf-8'))
                if not isinstance(cached, dict) or cached.get('signature') != signature or cached.get('end_frame') != end:
                    cached = None
                elif not isinstance(cached.get('segments'), list):
                    cached = None
                else:
                    rows = [TranscriptSegment.model_validate(item) for item in cached['segments']]
                    if any(not math.isfinite(row.start) or not math.isfinite(row.end) or not offset <= row.start <= row.end <= end / rate for row in rows):
                        cached = None
            except (OSError, ValueError, TypeError):
                cached = None
            if cached is None:
                chunk = checkpoint_dir / f'{start:012d}.wav'
                audio.setpos(start)
                with wave.open(str(chunk), 'wb') as target:
                    target.setparams(audio.getparams())
                    target.writeframes(audio.readframes(end - start))
                model = model_factory()
                try:
                    iterator, info = model.transcribe(str(chunk), vad_filter=True)
                    current = []
                    for item in iterator:
                        left = max(offset, min(end / rate, offset + float(item.start)))
                        right = max(left, min(end / rate, offset + float(item.end)))
                        if item.text.strip():
                            current.append(TranscriptSegment(start=left, end=right, text=item.text.strip()))
                        if progress_callback:
                            progress_callback(right, 'transcribing')
                    language = getattr(info, 'language', language)
                    cached = {'signature':signature, 'end_frame':end, 'language':language,
                              'segments':[item.model_dump(mode='json') for item in current]}
                    atomic_write_text(checkpoint, json.dumps(cached,ensure_ascii=False))
                finally:
                    del model
                    gc.collect()
            language = cached.get('language') or language
            segments.extend(TranscriptSegment.model_validate(item) for item in cached['segments'])
            if progress_callback:
                progress_callback(end / rate, 'transcribing')
        duration = total / rate
    if progress_callback:
        progress_callback(duration, 'complete')
    return TranscriptResult(language=language, source='faster-whisper', segments=segments,
                            full_text='\n'.join(item.text for item in segments),
                            warning='长音频按五分钟窗口转写；分段边界的内容请结合原音频核对。')
