import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import subprocess

from app.range_learning import source_range_subtitles, _srt_stamp
from app.media import extract_video_clip, probe_duration
from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs


class RangeLearningTests(unittest.TestCase):
    def test_precise_clip_does_not_include_the_previous_keyframe_interval(self):
        ffmpeg=ffmpeg_bin()
        if not ffmpeg:
            self.skipTest('FFmpeg is required for the real clip regression')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4';target=root/'clip.mp4'
            subprocess.run([ffmpeg,'-y','-loglevel','error','-f','lavfi','-i','testsrc2=size=160x90:rate=1','-t','8','-c:v','libx264','-g','60',str(source)],check=True,capture_output=True,timeout=20,**hidden_subprocess_kwargs())
            extract_video_clip(source,target,2,5)
            self.assertAlmostEqual(probe_duration(target),3,delta=.15)
    def test_only_fully_selected_cues_are_reused_with_relative_times(self):
        transcript={"segments":[{"start":0,"end":15,"text":"OUTSIDE FIRST"},{"start":15,"end":30,"text":"SELECTED ONE"},{"start":30,"end":45,"text":"SELECTED TWO"},{"start":45,"end":60,"text":"OUTSIDE LAST"}]}
        with patch('app.range_learning.read_json',return_value=transcript):
            subtitle=source_range_subtitles('source',15,45)
        self.assertNotIn('OUTSIDE',subtitle)
        self.assertIn('00:00:00,000 --> 00:00:15,000',subtitle)
        self.assertIn('00:00:15,000 --> 00:00:30,000',subtitle)

    def test_crossing_cue_requires_clip_transcription_instead_of_guessing_words(self):
        with patch('app.range_learning.read_json',return_value={"segments":[{"start":0,"end":20,"text":"不能确定哪些字属于选中片段"}]}):
            self.assertEqual(source_range_subtitles('source',5,15),'')
        self.assertEqual(_srt_stamp(3661.125),'01:01:01,125')


if __name__=='__main__':
    unittest.main()
