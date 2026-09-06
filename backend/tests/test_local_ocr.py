from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.local_ocr import recognize_frames
from app.local_ocr import ocr_available
from app.models import FrameSample


class LocalOcrTests(unittest.TestCase):
    @unittest.skipUnless(ocr_available(), 'Optional OCR runtime is not installed')
    def test_installed_engine_recognizes_a_real_local_image(self):
        from PIL import Image, ImageDraw, ImageFont
        candidates=[Path('C:/Windows/Fonts/arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/System/Library/Fonts/Supplemental/Arial.ttf')]
        font=next((path for path in candidates if path.is_file()),None)
        if font is None:
            self.skipTest('A fixture font is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'actual-ocr.png'
            image=Image.new('RGB',(700,180),'white');ImageDraw.Draw(image).text((30,50),'LEARNING RATE',font=ImageFont.truetype(str(font),48),fill='black');image.save(path)
            result=recognize_frames([FrameSample(path=str(path),timestamp=0)],cache_dir=root/'cache')
            text=''.join(line['text'] for frame in result['frames'] for line in frame['lines']).replace(' ','').upper()
            self.assertIn('LEARNINGRATE',text)
            self.assertEqual(result['remote_calls'],0)
    def test_ocr_cache_retains_boxes_and_never_labels_text_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);frame=root/'frame.png';frame.write_bytes(b'fixture')
            sample=FrameSample(path=str(frame),timestamp=12)
            calls=[]
            def engine(path):
                calls.append(path)
                return [[[[0,0],[20,0],[20,10],[0,10]],'自动识别文字',.96]], .1
            first=recognize_frames([sample],engine=engine,cache_dir=root/'cache')
            second=recognize_frames([sample],engine=engine,cache_dir=root/'cache')
            self.assertEqual(len(calls),1)
            self.assertEqual(second['cache_hits'],1)
            line=first['frames'][0]['lines'][0]
            self.assertEqual(line['verification'],'unreviewed')
            self.assertEqual(len(line['bbox']),4)
            self.assertEqual(first['remote_calls'],0)

    def test_optional_ocr_unavailable_does_not_require_model_calls(self):
        with patch('app.local_ocr.ocr_available',return_value=False):
            result=recognize_frames([])
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['frames'],[])


if __name__=='__main__':
    unittest.main()
