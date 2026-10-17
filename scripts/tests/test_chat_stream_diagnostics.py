"""Synthetic streaming failure evidence retains the original gate and failures."""
from pathlib import Path
import hashlib
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ChatStreamDiagnosticsTests(unittest.TestCase):
    def test_original_stream_assertions_and_timeout_unchanged(self):
        source = (ROOT / 'scripts/chat-stream-acceptance.cjs').read_text(encoding='utf-8')
        body = source.split('    p.on("pageerror"', 1)[1].split('  }, async error =>', 1)[0]
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), 'e48f12183f8849c32c34acd6156c94b952b16a5468dadc68128afa49a1357672')
        self.assertNotIn('setDefaultTimeout', source)
        self.assertNotIn('retry', source)
        self.assertLess(source.index('await runWithEvidence'), source.index('await chromium.launch'))
        workflow = (ROOT / '.github/workflows/ui-visual.yml').read_text(encoding='utf-8')
        self.assertIn('build/chat-stream-ui', workflow)

    def test_both_events_cover_chat_stream_diagnostics(self):
        workflow = (ROOT / '.github/workflows/ui-visual.yml').read_text(encoding='utf-8')
        for path in ('scripts/chat-stream-*.cjs',
                     'scripts/tests/chat-stream-diagnostics.test.cjs',
                     'scripts/tests/test_chat_stream_diagnostics.py'):
            self.assertEqual(workflow.count('      - "' + path + '"'), 2)

    def test_real_helper_faults_and_success_cleanup(self):
        result = subprocess.run(['node', str(ROOT / 'scripts/tests/chat-stream-diagnostics.test.cjs')], cwd=ROOT, text=True, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('diagnostic fault cases passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
