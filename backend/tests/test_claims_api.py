from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app


class ClaimRouteTests(unittest.TestCase):
    def test_rebuild_locates_chinese_paraphrase_without_claiming_verification(self):
        transcript = {'full_text':'旅行最大的支出在酒店上。', 'segments':[{'start':20,'end':30,'text':'旅行最大的支出在酒店上。'}]}
        with patch('app.main.get_task',return_value=SimpleNamespace(id='fixture',title='fixture')), patch('app.main.read_note',return_value='本次旅行的最大支出是酒店住宿。'), patch('app.main.read_transcript',return_value=transcript), patch('app.main.read_visual_index',return_value={}):
            response = TestClient(app).get('/api/tasks/fixture/claims?rebuild=true')
        self.assertEqual(response.status_code,200)
        claim = response.json()['claims'][0]
        self.assertEqual(claim['verification'],'located_only')
        self.assertTrue(claim['candidate_evidence_ids'])
        self.assertEqual(claim['evidence_ids'],[])

    def test_claim_endpoint_returns_projection_instead_of_null(self):
        payload = {'schema_version':4, 'task_id':'fixture', 'claims':[], 'quality':{}}
        with patch('app.main.get_task',return_value=SimpleNamespace(id='fixture')), patch('app.main.read_json',return_value=payload):
            response = TestClient(app).get('/api/tasks/fixture/claims')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),payload)

    def test_missing_projection_reports_not_ready(self):
        with patch('app.main.get_task',return_value=SimpleNamespace(id='fixture')), patch('app.main.read_json',return_value={}):
            response = TestClient(app).get('/api/tasks/fixture/claims')
        self.assertEqual(response.status_code,404)
        self.assertEqual(response.json()['detail']['code'],'claim_map_not_ready')

    def test_pipeline_status_keeps_its_own_response_contract(self):
        task = SimpleNamespace(id='fixture',status='running',phase='transcribing',progress=50,checkpoint='media_ready',summary_diagnostics={})
        with patch('app.main.get_task',return_value=task), patch('app.main.task_artifact_status',return_value={}):
            response = TestClient(app).get('/api/tasks/fixture/pipeline-status')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['phase'],'transcribing')
