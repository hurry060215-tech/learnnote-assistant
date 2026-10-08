import ast
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

from app.ocr_runtime import create_ocr_engine
from app.pdf_ocr import ocr_pdf


class OcrPrivacyTests(unittest.TestCase):
    def test_all_native_sessions_disable_telemetry_before_creation(self):
        calls = []
        def disabled():
            self.assertEqual(os.environ.get("ORT_DISABLE_TELEMETRY"), "1")
            calls.append("disabled")
        native = types.SimpleNamespace(disable_telemetry_events=disabled)
        ocr = types.SimpleNamespace(RapidOCR=lambda **kwargs: calls.append("created"))
        with patch.dict("sys.modules", {"onnxruntime": native, "rapidocr_onnxruntime": ocr}):
            create_ocr_engine()
        self.assertEqual(calls, ["disabled", "created"])

    def test_fresh_app_process_opts_out_before_any_native_model_import(self):
        code = "import os,sys; import app; assert os.environ['ORT_DISABLE_TELEMETRY']=='1'; assert os.environ['HF_HUB_DISABLE_TELEMETRY']=='1'; assert 'onnxruntime' not in sys.modules; print('pass')"
        env = {**os.environ, "ORT_DISABLE_TELEMETRY": "0", "HF_HUB_DISABLE_TELEMETRY": "0"}
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "pass")

    def test_pdf_default_engine_uses_the_shared_private_initializer(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.pdf"
            source.write_bytes(b"fixture")
            with patch("app.pdf_ocr.ocr_available", return_value=True), patch("app.pdf_ocr.create_ocr_engine", side_effect=RuntimeError("initializer-sentinel")) as create:
                with self.assertRaisesRegex(RuntimeError, "initializer-sentinel"):
                    ocr_pdf(source)
            create.assert_called_once_with()

    def test_app_cannot_introduce_an_unreviewed_direct_ocr_constructor(self):
        app_root = Path(__file__).resolve().parents[1] / "app"
        found = []
        for path in app_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "RapidOCR":
                    found.append(path.name)
        self.assertEqual(found, ["ocr_runtime.py"])
