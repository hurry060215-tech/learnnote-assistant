"""Exercise the acceptance assertion against the real API's backup schema."""
from contextlib import ExitStack, contextmanager
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from backend.tests.test_learning_backup_flow import LearningBackupFlowTests

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_acceptance', ROOT / 'scripts/native-platform-acceptance.py')
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class NativeAcceptanceBackupContractTests(unittest.TestCase):
    def test_every_native_api_assertion_against_real_local_api(self):
        @contextmanager
        def api_session(executable, data, output, phase):
            with ExitStack() as stack:
                LearningBackupFlowTests()._bind_source_data(stack, data)
                client = TestClient(app)
                class Adapter:
                    def call(self, method, endpoint, expected=200, **kwargs):
                        response = client.request(method, endpoint, **kwargs)
                        self_test.assertEqual(response.status_code, expected, response.text)
                        return response
                yield Adapter(), client.get('/health').json()
        self_test = self
        with tempfile.TemporaryDirectory() as temporary, patch.object(NATIVE, 'running', api_session):
            report = NATIVE.exercise(None, Path(temporary))
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(len(report['checks']), 6)

    def test_real_import_backup_and_new_directory_restore_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with ExitStack() as source:
                LearningBackupFlowTests()._bind_source_data(source, root / 'source')
                client = TestClient(app)
                imported = client.post('/api/library/materials/import', files={'file': ('native.md', NATIVE.TEXT.encode(), 'text/markdown')})
                self.assertEqual(imported.status_code, 200, imported.text)
                material = imported.json()['material']
                saved = client.post(f"/api/personal/material/{material['material_id']}", json={'text': NATIVE.PERSONAL})
                self.assertEqual(saved.status_code, 200, saved.text)
                backup = client.get('/api/study/backup').json()
                NATIVE.assert_backup_annotation(backup, material['sha256'])
            with ExitStack() as restored:
                LearningBackupFlowTests()._bind_source_data(restored, root / 'restored')
                client = TestClient(app)
                reimported = client.post('/api/library/materials/import', files={'file': ('native.md', NATIVE.TEXT.encode(), 'text/markdown')}).json()['material']
                self.assertNotEqual(reimported['material_id'], material['material_id'])
                self.assertEqual(reimported['sha256'], material['sha256'])
                result = client.post('/api/study/backup/restore', json=backup)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()['merge']['restored_annotations'], 1)
                annotations = client.get(f"/api/personal/material/{reimported['material_id']}").json()['annotations']
                self.assertEqual(annotations[0]['text'], NATIVE.PERSONAL)
