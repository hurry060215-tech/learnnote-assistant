import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from app.models import TaskRecord
from app.range_media import completed_range_media, range_media_preview_state
from app.task_inputs import task_media_path


class RangeMediaTests(unittest.TestCase):
    def test_pending_and_different_range_never_resolve_parent_but_matching_rerun_does(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def folder(key):
                path = root / key; path.mkdir(exist_ok=True); return path
            parent_clip = folder('parent') / 'selected-range.mp4'; parent_clip.write_bytes(b'completed clip')
            selected = {'start':5.25,'end':15.75,'original_start':5.25,'original_end':15.75}
            parent = TaskRecord(id='parent',source_type='local',title='Parent',created_at='',updated_at='',learning_range=selected)
            child = parent.model_copy(update={'id':'child','mode':'rerun_from_media','source_task_id':'parent','source_media_path':str(parent_clip)})
            with patch('app.range_media.task_dir',side_effect=folder), patch('app.range_media.get_task',return_value=parent):
                self.assertEqual(completed_range_media(child,duration_probe=lambda _:10.56),parent_clip)
                different = child.model_copy(update={'learning_range':{'start':0,'end':5}})
                self.assertIsNone(task_media_path(different))
                self.assertEqual(task_media_path(different,allow_range_source=True),parent_clip)
                self.assertEqual(range_media_preview_state(different),{'range_media_ready':False})
                with self.assertRaises(HTTPException) as caught:
                    completed_range_media(different,duration_probe=lambda _:5)
                self.assertEqual(caught.exception.status_code,409)
                (folder('child') / 'selected-range.partial.mp4').write_bytes(b'partial')
                self.assertFalse(range_media_preview_state(different)['range_media_ready'])

    def test_nonfinite_probe_symlink_and_retained_ocr_path_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root / 'selected-range.mp4'; clip.write_bytes(b'clip')
            task = TaskRecord(id='child',source_type='local',title='Clip',created_at='',updated_at='',
                learning_range={'start':5,'end':15},media_path=str(clip))
            with patch('app.range_media.task_dir',return_value=root):
                for duration in (float('nan'),float('inf'),-1,0):
                    with self.subTest(duration=duration), self.assertRaises(HTTPException):
                        completed_range_media(task,duration_probe=lambda _:duration)
                mismatch = task.model_copy(update={'screen_subtitles_media_sha256':'retained-hash','media_path':str(root/'different.mp4')})
                with self.assertRaises(HTTPException):
                    completed_range_media(mismatch,duration_probe=lambda _:10)
                retained = task.model_copy(update={'screen_subtitles_media_sha256':'retained-hash'})
                self.assertEqual(completed_range_media(retained,duration_probe=lambda _:10),clip)
                with patch.object(Path,'is_symlink',return_value=True), self.assertRaises(HTTPException):
                    completed_range_media(task,duration_probe=lambda _:10)


if __name__ == '__main__':
    unittest.main()
