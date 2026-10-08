"""The shipped capture-byte budget must not depend on Git for Windows defaults."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("background.js", "content.js", "content-study-evidence.js", "page_hook.js", "capture-classification.js", "capture-ranking.js")


class ExtensionCheckoutBytesTests(unittest.TestCase):
    def test_autocrlf_checkout_keeps_actual_capture_bytes_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp).as_posix() + "/"
            subprocess.run(["git", "-c", "core.autocrlf=true", "checkout-index", "--force", "--prefix=" + prefix, "--", *["extension/" + name for name in SCRIPTS]], cwd=ROOT, check=True, capture_output=True)
            for name in SCRIPTS:
                actual = (Path(tmp) / "extension" / name).read_bytes()
                self.assertEqual(actual, (ROOT / "extension" / name).read_bytes(), name)
                self.assertNotIn(b"\r\n", actual, name)
