import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import subprocess

from app.range_learning import source_range_subtitles, _srt_stamp
from app.media import extract_video_clip, probe_duration
from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs
from app.models import BrowserSubtitleCue
from app.processor import _learning_range_bounds, _slice_browser_subtitles


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

    def test_current_page_range_filters_complete_cues_and_keeps_source_offsets(self):
        cues = [
            BrowserSubtitleCue(start=0, end=5, text="前段"),
            BrowserSubtitleCue(start=10, end=15, text="范围内"),
            BrowserSubtitleCue(start=15, end=20, text="范围末段"),
            BrowserSubtitleCue(start=20, end=25, text="后段"),
        ]
        selected = _slice_browser_subtitles(cues, 10, 20)
        self.assertEqual([(cue.start, cue.end, cue.text) for cue in selected], [(0, 5, "范围内"), (5, 10, "范围末段")])
        self.assertEqual(_learning_range_bounds({"start": 10, "end": 20}), (10.0, 20.0))
        self.assertIsNone(_learning_range_bounds({"start": 20, "end": 10}))


class RangeSourceIdentityTests(unittest.TestCase):
    def test_nested_range_cannot_select_encoded_padding_or_epsilon_past_parent(self):
        from app.models import TaskOptions, TaskRecord, MediaIntegrity
        from app.range_learning import create_range_task
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "source.mp4"; media.write_bytes(b"fixture")
            source = TaskRecord(id="source", source_type="local", title="Quantized clip", created_at="", updated_at="",
                media_path=str(media), media_integrity=MediaIntegrity(duration=11.064026),
                learning_range={"start":5.25,"end":15.75,"original_start":5.25,"original_end":15.75})
            created = source.model_copy(update={"id":"new"})
            with patch("app.range_learning.DATA_DIR", Path(tmp)), patch("app.range_learning.completed_range_media", return_value=media), patch("app.range_learning.get_task", return_value=source), patch("app.range_learning.create_task", return_value=created) as create, patch("app.range_learning.update_task", side_effect=lambda key, **kw:created.model_copy(update=kw)), patch("app.range_learning.schedule_processing") as schedule:
                for start, end in ((10.5, 11), (0, 10.500000001), (0, 10.505)):
                    with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, "invalid_learning_range"):
                        create_range_task("source", start, end, TaskOptions(), None)
                create.assert_not_called(); schedule.assert_not_called()
                result = create_range_task("source", 5.25, 10.5, TaskOptions(), None)
                self.assertEqual(result.learning_range, {"start":5.25,"end":10.5,"original_start":10.5,"original_end":15.75})

    def test_full_media_and_legacy_offset_only_keep_container_tolerance(self):
        from app.models import TaskOptions, TaskRecord, MediaIntegrity
        from app.range_learning import create_range_task
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "source.mp4"; media.write_bytes(b"fixture")
            for selected in ({}, {"original_start":60}):
                with self.subTest(selected=selected):
                    source = TaskRecord(id="source", source_type="local", title="Source", created_at="", updated_at="",
                        media_path=str(media), media_integrity=MediaIntegrity(duration=20), learning_range=selected)
                    with patch("app.range_learning.DATA_DIR", Path(tmp)), patch("app.range_learning.completed_range_media", return_value=media), patch("app.range_learning.get_task", return_value=source), patch("app.range_learning.create_task", return_value=source), patch("app.range_learning.update_task", side_effect=lambda key, **kw:source.model_copy(update=kw)), patch("app.range_learning.schedule_processing"):
                        result = create_range_task("source", 0, 20.005, TaskOptions(), None)
                    self.assertEqual(result.learning_range["end"], 20.005)

    def test_decimal_endpoint_is_accepted_without_expanding_original_parent(self):
        from app.models import TaskOptions, TaskRecord, MediaIntegrity
        from app.range_learning import create_range_task
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "source.mp4"; media.write_bytes(b"fixture")
            source = TaskRecord(id="source", source_type="local", title="Decimal clip", created_at="", updated_at="",
                media_path=str(media), media_integrity=MediaIntegrity(duration=1),
                learning_range={"start":0.1,"end":0.3,"original_start":0.1,"original_end":0.3})
            with patch("app.range_learning.DATA_DIR", Path(tmp)), patch("app.range_learning.completed_range_media", return_value=media), patch("app.range_learning.get_task", return_value=source), patch("app.range_learning.create_task", return_value=source), patch("app.range_learning.update_task", side_effect=lambda key, **kw:source.model_copy(update=kw)), patch("app.range_learning.schedule_processing"):
                result = create_range_task("source", 0, 0.2, TaskOptions(), None)
                self.assertEqual(result.learning_range, {"start":0,"end":0.2,"original_start":0.1,"original_end":0.3})
                with self.assertRaisesRegex(ValueError, "invalid_learning_range"):
                    create_range_task("source", 0, 0.200000001, TaskOptions(), None)

    def test_nonfinite_stored_bounds_and_overflowed_offsets_reject_before_creation(self):
        from app.models import TaskOptions, TaskRecord, MediaIntegrity
        from app.range_learning import create_range_task
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "source.mp4"; media.write_bytes(b"fixture")
            valid = {"start":0.1,"end":0.3,"original_start":0.1,"original_end":0.3}
            cases = [({**valid, key:value}, .1) for key in valid for value in (float('inf'), float('-inf'), float('nan'))]
            cases += [({"start":float('inf'),"end":float('inf')}, .1), ({"original_start":1e308}, 1e308)]
            for selected, end in cases:
                with self.subTest(selected=selected):
                    source = TaskRecord(id="source", source_type="local", title="Invalid bounds", created_at="", updated_at="",
                        media_path=str(media), media_integrity=MediaIntegrity(duration=1e308), learning_range=selected)
                    with patch("app.range_learning.DATA_DIR", Path(tmp)), patch("app.range_learning.completed_range_media", return_value=media), patch("app.range_learning.get_task", return_value=source), patch("app.range_learning.create_task") as create, patch("app.range_learning.schedule_processing") as schedule:
                        with self.assertRaisesRegex(ValueError, "invalid_learning_range"):
                            create_range_task("source", 0, end, TaskOptions(), None)
                        create.assert_not_called(); schedule.assert_not_called()

    def test_reused_range_preserves_page_identity_and_original_offsets(self):
        from app.models import TaskOptions, TaskRecord, SourceIdentity, MediaIntegrity
        from app.range_learning import create_range_task
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "source.mp4"; media.write_bytes(b"fixture")
            source = TaskRecord(id="source", source_type="local", title="Part 2", page_url="https://www.bilibili.com/video/BV1xx?p=2", created_at="", updated_at="", media_path=str(media), media_integrity=MediaIntegrity(duration=100), learning_range={"original_start":60}, source_identity=SourceIdentity(media_sha256="original-hash"))
            created = source.model_copy(update={"id":"new"})
            with patch("app.range_learning.DATA_DIR", Path(tmp)), patch("app.range_learning.completed_range_media", return_value=media), patch("app.range_learning.get_task", return_value=source), patch("app.range_learning.create_task", return_value=created) as create, patch("app.range_learning.update_task", side_effect=lambda key, **kw:created.model_copy(update=kw)), patch("app.range_learning.schedule_processing") as schedule:
                result = create_range_task("source", 10, 20, TaskOptions(), None)
            self.assertEqual(create.call_args.kwargs["page_url"], source.page_url)
            self.assertEqual(result.learning_range["original_start"], 70)
            self.assertEqual(result.learning_range["original_end"], 80)
            self.assertEqual(result.source_task_id, source.id)
            self.assertEqual(result.source_identity.media_sha256, "")
            self.assertEqual(schedule.call_count, 1)


if __name__ == "__main__":
    unittest.main()
