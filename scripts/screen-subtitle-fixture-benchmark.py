"""Offline synthetic Chinese/English MP4 acceptance: real decoder + local OCR.

No user media, downloads, provider calls, or recognition claims about real videos.
Outputs only locally generated fixtures and measured results.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

os.environ['ORT_DISABLE_TELEMETRY'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def benchmark(output):
    import av
    from PIL import Image, ImageDraw, ImageFont
    from app.models import ScreenSubtitleSettings
    from app.ocr_runtime import create_ocr_engine
    from app.processor_state import TaskCancelled
    from app.screen_subtitles import extract, media_hash, media_info
    output.mkdir(parents=True, exist_ok=True)
    candidates = [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')]
    font_path = next((path for path in candidates if path.is_file()), None)
    if not font_path:
        raise RuntimeError('A local Noto CJK font is required for this synthetic benchmark')
    font = ImageFont.truetype(str(font_path), 30)
    images = []
    for index, words in enumerate([('学习率', 'LEARNING RATE'), ('', ''), ('梯度下降', 'GRADIENT DESCENT')]):
        image = Image.new('RGB', (960, 360), (16, 25, 45))
        draw = ImageDraw.Draw(image)
        draw.text((50, 30), 'Synthetic offline OCR fixture', font=font, fill='white')
        draw.rectangle((0, 265, 960, 360), fill='black')
        draw.text((180, 267), words[0], font=font, fill='white')
        draw.text((180, 309), words[1], font=font, fill='white')
        image.save(output / f'frame-{index}.png')
        images.append(image)
    video = output / 'synthetic-bilingual-130s-no-audio.mp4'
    with av.open(str(video), mode='w') as container:
        stream = container.add_stream('libx264', rate=2)
        stream.width, stream.height = 960, 360
        stream.pix_fmt = 'yuv420p'
        for index in range(260):
            seconds = index / 2
            choice = 0 if seconds < 30 or seconds >= 90 else 1 if seconds < 35 else 2
            frame = av.VideoFrame.from_image(images[choice])
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    with av.open(str(video)) as container:
        assert not container.streams.audio
    original_hash = media_hash(video)
    engine = create_ocr_engine()
    settings = ScreenSubtitleSettings()
    calls = 0
    def counted(image):
        nonlocal calls
        result = engine(image)
        calls += 1
        return result
    def cancel():
        if calls >= 130:
            raise TaskCancelled('synthetic midway cancellation')
    started = time.monotonic()
    try:
        extract(video, settings, output / 'cache', engine=counted, cancel_check=cancel)
        raise AssertionError('Cancellation was not observed')
    except TaskCancelled:
        pass
    cancelled_calls = calls
    completed_windows = len(list((output / 'cache').glob('*/window-*.json')))
    assert completed_windows == 1, completed_windows
    calls = 0
    resumed = extract(video, settings, output / 'cache', engine=counted)
    resumed_calls = calls
    assert resumed['status'] == 'ready', resumed
    assert resumed['cache_hits'] == 1
    assert calls == 140, calls
    assert resumed['sample_count'] == 260
    text = '\n'.join(cue['text'] for cue in resumed['cues'])
    assert '学习率' in text and '梯度下降' in text, text
    assert 'LEARNINGRATE' in ''.join(text.split()) and 'GRADIENTDESCENT' in ''.join(text.split()), text
    assert any(cue['end'] <= 30 for cue in resumed['cues'])
    assert any(cue['start'] >= 35 for cue in resumed['cues'])
    assert not any(cue['start'] < 35 and cue['end'] > 30 for cue in resumed['cues'])
    calls = 0
    cached = extract(video, settings, output / 'cache', engine=counted)
    assert cached['cache_hits'] == 3 and calls == 0
    changed = extract(video, ScreenSubtitleSettings(interval_seconds=1), output / 'cache', engine=counted)
    assert changed['cache_hits'] == 0 and changed['fingerprint'] != resumed['fingerprint']
    assert calls == 130
    assert media_hash(video) == original_hash
    report = {'fixture': video.name, 'duration_seconds': 130, 'has_audio': False,
              'settings': settings.model_dump(), 'cancelled_after_ocr_calls': cancelled_calls,
              'completed_windows_at_cancel': completed_windows, 'resumed_cache_hits': resumed['cache_hits'],
              'resumed_new_ocr_calls': resumed_calls, 'sample_count': resumed['sample_count'],
              'full_cache_hits': cached['cache_hits'], 'changed_interval_cache_hits': changed['cache_hits'],
              'changed_interval_ocr_calls': calls, 'media_unchanged': True,
              'elapsed_seconds': round(time.monotonic() - started, 2),
              'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'cues': resumed['cues'], 'engine': resumed['engine'],
              'reference_phrases': [{'expected': phrase, 'exact_match': phrase in text,
                  'match_ignoring_whitespace': ''.join(phrase.split()) in ''.join(text.split())}
                  for phrase in ['学习率', '梯度下降', 'LEARNING RATE', 'GRADIENT DESCENT']],
              'scope': 'Synthetic clean two-line Chinese/English fixture only. Does not establish accuracy or performance for any real or four-hour video.',
              'network': 'Python external socket, DNS and HTTP blocked; native ONNX telemetry disabled; bundled local models only.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in {'cues','engine'}},ensure_ascii=False,indent=2))
    print('Observed text: ' + text)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('offline_test_guard',ROOT/'scripts/test-backend-offline.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with module.offline_network():
        benchmark(args.output_dir)
