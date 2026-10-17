"""Owned media children must not inherit desktop/CI standard input."""
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import media


class MediaStdinTests(unittest.TestCase):
    def test_normalization_closes_stdin_and_drains_owned_child_in_both_modes(self):
        real_popen = subprocess.Popen
        for cancellable in (False, True):
            with self.subTest(cancellable=cancellable), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, output = root / 'source.mp4', root / 'normalized.mp4'
                source.write_bytes(b'owned input')
                children = []

                def launch(command, **kwargs):
                    self.assertEqual(kwargs.get('stdin'), subprocess.DEVNULL)
                    self.assertEqual(command[0], 'owned-ffmpeg')
                    # Exercise real EOF and pipe draining without requiring FFmpeg.
                    script = (
                        'import sys;from pathlib import Path;'
                        'assert sys.stdin.buffer.read() == b"";'
                        'sys.stdout.write("o" * 131072);sys.stdout.flush();'
                        'sys.stderr.write("e" * 131072);sys.stderr.flush();'
                        'Path(sys.argv[1]).write_bytes(b"normalized")'
                    )
                    child = real_popen([sys._base_executable, '-c', script, command[-1]], **kwargs)
                    children.append(child)
                    return child

                context = media.media_cancellation(lambda: None) if cancellable else nullcontext()
                with patch('app.media.ffmpeg_bin', return_value='owned-ffmpeg'), \
                        patch('app.media.subprocess.Popen', side_effect=launch), context:
                    self.assertEqual(media.normalize_video(source, output), output)
                self.assertEqual(output.read_bytes(), b'normalized')
                self.assertEqual(source.read_bytes(), b'owned input')
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].returncode, 0)
                self.assertTrue(children[0].stdout.closed)
                self.assertTrue(children[0].stderr.closed)
                self.assertEqual(list(root.glob('.normalize-*')), [])

    def test_cancelled_normalization_reaps_child_and_preserves_existing_output(self):
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, marker = root / 'source.mp4', root / 'output.mp4', root / 'started'
            source.write_bytes(b'input')
            output.write_bytes(b'previous output')
            children = []

            def launch(command, **kwargs):
                self.assertEqual(kwargs.get('stdin'), subprocess.DEVNULL)
                script = (
                    'import sys,time;from pathlib import Path;'
                    'assert sys.stdin.buffer.read() == b"";'
                    'Path(sys.argv[1]).write_bytes(b"partial");'
                    'Path(sys.argv[2]).touch();time.sleep(30)'
                )
                child = real_popen([sys._base_executable, '-c', script, command[-1], str(marker)], **kwargs)
                children.append(child)
                return child

            def cancelled():
                if marker.exists():
                    raise RuntimeError('test cancellation')

            with patch('app.media.ffmpeg_bin', return_value='owned-ffmpeg'), \
                    patch('app.media.subprocess.Popen', side_effect=launch):
                with self.assertRaisesRegex(RuntimeError, 'test cancellation'):
                    with media.media_cancellation(cancelled):
                        media.normalize_video(source, output)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode)
            self.assertNotEqual(children[0].returncode, 0)
            self.assertTrue(children[0].stdout.closed)
            self.assertTrue(children[0].stderr.closed)
            self.assertEqual(output.read_bytes(), b'previous output')
            self.assertEqual(list(root.glob('.normalize-*')), [])

    def test_probe_and_extraction_boundaries_disconnect_stdin(self):
        completed = subprocess.CompletedProcess([], 0, '{"format":{"duration":"1"}}', '')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mp4'
            source.write_bytes(b'owned input')
            output = Path(directory) / 'output.jpg'
            calls = [
                lambda: media.probe_duration(source),
                lambda: media._integrity_from_ffprobe(source, 'ffprobe'),
                lambda: media._integrity_from_ffmpeg(source, 'ffmpeg'),
                lambda: media.extract_embedded_subtitle(source, Path(directory) / 'subtitle.srt'),
                lambda: media.detect_scene_change_timestamps(source),
                lambda: media._extract_frame_batch('ffmpeg', source, [(0, output)]),
                lambda: media._extract_single_frame('ffmpeg', source, 0, output),
            ]
            for call in calls:
                with self.subTest(call=call), patch('app.media.ffmpeg_bin', return_value='ffmpeg'), \
                        patch('app.media.ffprobe_bin', return_value='ffprobe'), \
                        patch('app.media.subprocess.run', return_value=completed) as run:
                    call()
                    self.assertTrue(run.called)
                    for invocation in run.call_args_list:
                        self.assertEqual(invocation.kwargs.get('stdin'), subprocess.DEVNULL)
            with patch('app.media.ffprobe_bin', return_value=None), \
                    patch('app.media.ffmpeg_bin', return_value='ffmpeg'), \
                    patch('app.media.subprocess.run', return_value=completed) as run:
                media.probe_duration(source)
                self.assertEqual(run.call_args.kwargs.get('stdin'), subprocess.DEVNULL)
