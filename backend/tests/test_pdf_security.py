"""Small synthetic regressions; every parser probe runs under process limits."""
import asyncio
from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from app import pdf_process
from app.knowledge import extract_import_text_with_metadata

# Upstream py-pdf/pypdf#4289. Never feed this directly to an unbounded reader.
TRUNCATED_XREF = b"%PDF-1.4\n startxref\n 28\n%%EOF\n xref\n 1 0\n aaa"


def blank_pdf(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


class PdfSecurityTests(unittest.TestCase):
    def test_truncated_xref_is_rejected_and_next_document_succeeds(self):
        with self.assertRaisesRegex(ValueError, '^pdf_file_invalid$'):
            extract_import_text_with_metadata('bad.pdf', TRUNCATED_XREF)
        text, kind, metadata = extract_import_text_with_metadata('valid.pdf', blank_pdf())
        self.assertEqual(kind, 'pdf')
        self.assertEqual(metadata['page_count'], 1)
        self.assertIn('[第 1 页]', text)

    def test_page_and_character_limits_survive_worker_boundary(self):
        with self.assertRaisesRegex(ValueError, '^pdf_page_limit_exceeded$'):
            pdf_process.extract_pdf_isolated(blank_pdf(2), 1, 1000)
        from reportlab.pdfgen import canvas
        stream = BytesIO()
        page = canvas.Canvas(stream)
        page.drawString(10, 20, 'bounded text')
        page.save()
        with self.assertRaisesRegex(ValueError, '^extracted_text_too_large$'):
            pdf_process.extract_pdf_isolated(stream.getvalue(), 500, 3)

    def test_timeout_crash_and_invalid_response_reap_child_and_release_slot(self):
        real_owned = pdf_process.owned_media_process
        children = []

        @contextmanager
        def tracked(*args, **kwargs):
            with real_owned(*args, **kwargs) as child:
                children.append(child)
                yield child

        for script in ('import time; time.sleep(60)', 'raise SystemExit(7)',
                       'import pathlib,sys; pathlib.Path(sys.argv[2]).write_text("[]")'):
            with self.subTest(script=script), patch.object(pdf_process, 'PDF_TIMEOUT_SECONDS', .2), \
                    patch.object(pdf_process, 'owned_media_process', tracked), \
                    patch.object(pdf_process, '_worker_command', side_effect=lambda args: [sys.executable, '-c', script, *args]):
                with self.assertRaisesRegex(ValueError, '^pdf_file_invalid$'):
                    pdf_process.extract_pdf_isolated(b'fixture', 500, 1000)
                self.assertIsNotNone(children[-1].poll())
            self.assertEqual(pdf_process.extract_pdf_isolated(blank_pdf(), 500, 1000)[1], 'pdf')

    def test_input_and_concurrency_are_bounded_before_spawning(self):
        with patch.object(pdf_process, 'MAX_PDF_BYTES', 3), patch.object(pdf_process, '_worker_command') as spawn:
            with self.assertRaises(ValueError):
                pdf_process.extract_pdf_isolated(b'1234', 500, 1000)
            spawn.assert_not_called()
        with patch.object(pdf_process, '_SLOTS') as slots, patch.object(pdf_process, '_worker_command') as spawn:
            slots.acquire.return_value = False
            with self.assertRaises(ValueError):
                pdf_process.extract_pdf_isolated(b'1234', 500, 1000)
            spawn.assert_not_called()
            slots.release.assert_not_called()

    def test_os_memory_limit_rejects_a_small_over_budget_allocation(self):
        script = """
import os
if os.name != 'nt':
 import resource
 resource.setrlimit(resource.RLIMIT_AS, (64*1024**2, 64*1024**2))
try:
 bytearray(128*1024**2)
except MemoryError:
 pass
else:
 raise AssertionError('memory limit not enforced')
"""
        with pdf_process.owned_media_process([sys.executable, '-c', script], memory_limit_bytes=64*1024**2,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as child:
            _, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr)

    def test_bad_pdf_api_paths_preserve_existing_material(self):
        from contextlib import ExitStack
        from fastapi.testclient import TestClient
        from app.main import app
        from app.library import material_content
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            for module in ('app.library', 'app.knowledge', 'app.routers.library'):
                stack.enter_context(patch(f'{module}.DATA_DIR', root))
            client = TestClient(app)
            stored = client.post('/api/library/materials/import', files={'file': ('prior.txt', b'preserve prior material', 'text/plain')})
            self.assertEqual(stored.status_code, 200, stored.text)
            prior = {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}
            for endpoint in ('/api/library/materials/preview', '/api/library/materials/import', '/api/knowledge/import-file'):
                response = client.post(endpoint, files={'file': ('bad.pdf', TRUNCATED_XREF, 'application/pdf')})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()['detail']['code'], 'pdf_file_invalid')
                self.assertEqual(prior, {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()})
            self.assertIn('preserve prior material', material_content(stored.json()['material']['material_id']))

    def test_frozen_worker_uses_early_desktop_diversion(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(pdf_process._worker_command(['input', 'result', '500', '1000']),
                             [sys.executable, '--pdf-worker', 'input', 'result', '500', '1000'])
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            source, result = Path(directory) / 'input.pdf', Path(directory) / 'result.json'
            source.write_bytes(blank_pdf())
            completed = subprocess.run([sys.executable, str(root / 'desktop/main.py'), '--pdf-worker',
                                        str(source), str(result), '500', '1000'],
                                       timeout=10, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('pdf-text', result.read_text())

    def test_small_repeated_page_tree_hits_upstream_copy_budget(self):
        # Scaled-down py-pdf/pypdf#4290: four references, not the large stress input.
        script = r'''
import resource
resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
from io import BytesIO
from pypdf import PdfReader
from pypdf._configuration import apply_configuration
from pypdf.errors import LimitReachedError
objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
 b'<< /Type /Pages /Kids [3 0 R 3 0 R] /Count 4 >>',
 b'<< /Type /Pages /Kids [4 0 R 4 0 R] /Count 2 >>',
 b'<< /Type /Page /MediaBox [0 0 9 9] /K0 0 /K1 0 >>']
buf = bytearray(b'%PDF-1.7\n'); offsets = []
for i, obj in enumerate(objects, 1):
 offsets.append(len(buf)); buf += b'%d 0 obj\n' % i + obj + b'\nendobj\n'
xref = len(buf)
buf += b'xref\n0 5\n0000000000 65535 f \n'
for offset in offsets: buf += b'%010d 00000 n \n' % offset
buf += b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % xref
with apply_configuration(page_tree_maximum_page_entries=6):
 try: len(PdfReader(BytesIO(buf)).pages)
 except LimitReachedError: pass
 else: raise AssertionError('page-copy budget was not enforced')
'''
        if os.name == 'nt':
            script = script.replace('import resource\nresource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))\nresource.setrlimit(resource.RLIMIT_CPU, (5, 5))', '')
        with pdf_process.owned_media_process([sys.executable, '-c', script], memory_limit_bytes=1024**3,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as child:
            _, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr)


class PdfAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_does_not_block_event_loop(self):
        import threading
        from fastapi import UploadFile
        from app.routers.library import api_library_material_preview
        entered, release = threading.Event(), threading.Event()
        def preview(*args):
            entered.set()
            release.wait(2)
            return {'bounded': True}
        with patch('app.routers.library.preview_document_material', preview):
            request = asyncio.create_task(api_library_material_preview(UploadFile(BytesIO(b'pdf'), filename='x.pdf'), ''))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                self.assertFalse(request.done())
            finally:
                release.set()
            self.assertEqual(await request, {'bounded': True})
