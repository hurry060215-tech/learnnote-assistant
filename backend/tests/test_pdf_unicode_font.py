"""Bundled glyphs and exact astral ToUnicode text, without font downloads."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from app.document_exports import build_pdf_export
from app.models import TaskRecord
from app.pdf_unicode import emoji_font, bundled_emoji_font_path

SAMPLE='🧭😀👍📘🧠📝🚀✅❤️'
class PdfUnicodeFontTests(unittest.TestCase):
    def setUp(self):
        self.task=TaskRecord(id='unicode-font',title='中文 Unicode '+SAMPLE,source_type='local',created_at='2026-10-08',updated_at='2026-10-08')
    def test_unmodified_font_and_license_are_bundled_with_reproducible_hash(self):
        root=Path(__file__).resolve().parents[1]/'app/fonts/noto-emoji'
        self.assertEqual(sha256((root/'NotoEmoji.ttf').read_bytes()).hexdigest(),'de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551')
        self.assertIn('SIL OPEN FONT LICENSE Version 1.1',(root/'OFL.txt').read_text())
        self.assertIn('5e8a3ba899557829a76cfdac30fa512bda91d7ca',(root/'README.md').read_text())
    def test_frozen_font_path_matches_existing_pyinstaller_data_tree(self):
        with tempfile.TemporaryDirectory() as tmp, patch('app.pdf_unicode.__file__',str(Path(tmp)/'app/pdf_unicode.py')), patch('app.pdf_unicode.sys._MEIPASS',tmp,create=True):
            self.assertEqual(bundled_emoji_font_path(),Path(tmp)/'backend/app/fonts/noto-emoji/NotoEmoji.ttf')
    def test_title_prose_code_table_and_link_labels_preserve_exact_emoji_text(self):
        note=f'## 混排\n\n中文 日本語 English café α ∂ ≤ {SAMPLE}\n\n`{SAMPLE}`\n\n```text\n{SAMPLE}\n```\n\n| Glyphs | Label |\n| --- | --- |\n| {SAMPLE} | [{SAMPLE}](https://example.org/evidence) |'
        artifact=build_pdf_export(self.task,note)
        with self.assertNoLogs('pypdf',level='WARNING'):
            reader=PdfReader(BytesIO(artifact.content))
            text=''.join(p.extract_text() for p in reader.pages)
        self.assertGreaterEqual(text.count(SAMPLE),6)
        for value in ['中文','日本語','English café','α','∂','≤']:self.assertIn(value,text)
        self.assertEqual(reader.metadata.title,self.task.title)
        self.assertNotIn('[compass]',text);self.assertNotIn('\ufffd',text)
        self.assertNotIn('non_bmp_symbols_rendered_as_unicode_names',artifact.warnings)
        fonts=[f.get_object() for p in reader.pages for f in p['/Resources']['/Font'].values() if 'NotoEmoji' in str(f.get_object().get('/BaseFont'))]
        self.assertTrue(fonts)
        self.assertTrue(all('/FontFile2' in f['/FontDescriptor'] for f in fonts))
        self.assertTrue(any(b'D83EDDED' in f['/ToUnicode'].get_data() for f in fonts))
        self.assertFalse(any(b'<1F9ED>' in f['/ToUnicode'].get_data() for f in fonts))
    def test_multiple_font_subsets_and_repeated_exports_keep_exact_scalars(self):
        points=sorted(c for c in emoji_font().face.charToGlyph if c>=0x1F000)[:270]
        sample=''.join(chr(c) for c in points)
        for _ in range(2):
            artifact=build_pdf_export(self.task,sample)
            with self.assertNoLogs('pypdf',level='WARNING'):
                reader=PdfReader(BytesIO(artifact.content));text=''.join(p.extract_text() for p in reader.pages)
            for c in sample:self.assertIn(c,text)
            names={str(f.get_object().get('/BaseFont')) for p in reader.pages for f in p['/Resources']['/Font'].values() if 'NotoEmoji' in str(f.get_object().get('/BaseFont'))}
            self.assertGreaterEqual(len(names),2)
    def test_missing_optional_font_remains_explicit_instead_of_silent_glyph_loss(self):
        with patch('app.document_exports.emoji_font_for',return_value=''):
            artifact=build_pdf_export(self.task,'导航 🧭')
            text=''.join(p.extract_text() for p in PdfReader(BytesIO(artifact.content)).pages)
        self.assertIn('[compass]',text)
        self.assertIn('non_bmp_symbols_rendered_as_unicode_names',artifact.warnings)
