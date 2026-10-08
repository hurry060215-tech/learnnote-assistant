"""Bounded, lossless list-marker handling for uncontrolled note text."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest

from app.document_exports import _blocks, _list_item


class ExportListMarkerLimitsTests(unittest.TestCase):
    def test_valid_markers_keep_ordinal_and_exact_continuation_offset(self):
        self.assertEqual(_list_item('  007.   Step  '), ('ordered', 'Step', 7, 9))
        self.assertEqual(_list_item('\t-\tChild'), ('bullet', 'Child', 0, 3))
        self.assertEqual(_list_item('999999999) Last bounded ordinal'), ('ordered', 'Last bounded ordinal', 999999999, 11))
        blocks = _blocks('7. Parent\n   - Child\n     continuation\n8. Next')
        self.assertEqual([(b.kind, b.text, b.level, b.ordinal) for b in blocks], [
            ('ordered', 'Parent', 0, 7), ('bullet', 'Child continuation', 1, 0), ('ordered', 'Next', 0, 8)])

    def test_oversized_invalid_and_non_ascii_markers_remain_literal(self):
        for value in ['0' * 10 + '. Keep this', '1234567890) Keep this', '². Keep this', '١. Keep this', '1.No space', '-No space']:
            with self.subTest(prefix=value[:20]):
                self.assertIsNone(_list_item(value))
                blocks = _blocks(value)
                self.assertEqual([(b.kind, b.text) for b in blocks], [('paragraph', value)])

    def test_long_adversarial_prefixes_finish_within_a_process_budget(self):
        # A subprocess timeout proves termination on every OS, even if a
        # future parser regression wedges the interpreter's regex engine.
        code = '''from app.document_exports import _blocks, _list_item
for tail in (". Keep source", ") Keep source", "X", "." + " " * 250000):
    value = "0" * 250000 + tail
    assert _list_item(value) is None
    blocks = _blocks(value)
    assert len(blocks) == 1 and blocks[0].kind == "paragraph"
    assert blocks[0].text == value.rstrip()
assert _list_item(" " * 250000 + "1. payload")[1] == "payload"
print("bounded-list-scan-pass")
'''
        root = Path(__file__).resolve().parents[2]
        env = {**os.environ, 'PYTHONPATH': str(root / 'backend'),
               'ORT_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_TELEMETRY': '1'}
        result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(result.stdout.strip(), 'bounded-list-scan-pass')
