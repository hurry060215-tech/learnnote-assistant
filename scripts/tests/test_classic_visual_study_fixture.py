"""Offline fixture boundaries; actual rendering requires hosted Edge."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ClassicVisualStudyFixtureTests(unittest.TestCase):
    def test_fixture_boundaries_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="classic-visual-study-") as temporary:
            env = {**os.environ, "TMPDIR": temporary, "TMP": temporary, "TEMP": temporary}
            subprocess.run(["node", "--test", "scripts/tests/classic-visual-study-fixture.test.cjs"],
                           cwd=ROOT, env=env, check=True, timeout=30)

    def test_reuses_hosted_classic_browser_and_existing_artifacts(self):
        flow = (ROOT / "scripts/learning-workflow-acceptance.cjs").read_text(encoding="utf-8")
        self.assertEqual(flow.count('runClassicVisualStudy(browser, base, path.join(output, "visual-study"))'), 1)
        workflow = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")
        for name in ("scripts/learning-workflow-acceptance.cjs", "scripts/classic-visual-study-fixture.cjs",
                     "scripts/tests/classic-visual-study-fixture.test.cjs", "scripts/tests/test_classic_visual_study_fixture.py"):
            self.assertEqual(workflow.count('"' + name + '"'), 2, name)
        self.assertIn("learning-workflow-acceptance.cjs http://127.0.0.1:8765/web/classic.html build/learning-ui", workflow)
        self.assertIn("Learning interaction gate failed", workflow)
        self.assertIn("build/learning-ui", workflow[workflow.index("actions/upload-artifact@"):])

    def test_fixture_matches_real_local_study_plan_api(self):
        fixture = subprocess.check_output([
            "node", "-e", "const f=require('./scripts/classic-visual-study-fixture.cjs'); "
            "const plan=f.createStudyPlan(); console.log(JSON.stringify(f.fixtureResponse("
            "'/api/study/plan/initialize', {method:'POST',postData:JSON.stringify({timezone:'UTC'}),"
            "contentType:'application/json',plan}).json));"
        ], cwd=ROOT)
        # Node emits UTF-8: retain those bytes across the parent locale boundary.
        self.assertIn("本地学习计划".encode("utf-8"), fixture)
        # A fresh process keeps imported backend configuration isolated from other script tests.
        code = r'''
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.models import StudyPlan, StudyPlanUpdateRequest
from app.routers.knowledge_study import study_router

fixture = json.loads(sys.stdin.buffer.read().decode("utf-8"))
StudyPlan.model_validate(fixture["plan"])
StudyPlanUpdateRequest.model_validate({"timezone": "UTC"})
app = FastAPI()
app.include_router(study_router)
with tempfile.TemporaryDirectory(prefix="classic-plan-api-") as tmp, patch("app.study.DATA_DIR", Path(tmp)):
    with TestClient(app) as client:
        initialized = client.post("/api/study/plan/initialize", json={"timezone": "UTC"})
        assert initialized.status_code == 200, initialized.text
        fetched = client.get("/api/study/plan")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json() == initialized.json()
        actual = fetched.json()["plan"]
        assert set(actual) == set(fixture["plan"])
        for key in actual:
            if key not in {"created_at", "updated_at"}:
                assert actual[key] == fixture["plan"][key], (key, actual[key], fixture["plan"][key])
        assert client.post("/api/study/plan/initialize", json={"timezone": "UTC"}).json() == fetched.json()
        for payload in ({"timezone": "Invalid/Zone"}, {"timezone": "UTC", "extra": True}):
            assert client.post("/api/study/plan/initialize", json=payload).status_code == 422
        for method in ("GET", "PUT", "DELETE"):
            assert client.request(method, "/api/study/plan/initialize").status_code == 405
        assert client.get("/api/study/plan").json() == fetched.json()
'''
        for stdio_encoding in ("utf-8", "cp1252", "ascii"):
            with self.subTest(stdio_encoding=stdio_encoding):
                env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"),
                       "PYTHONIOENCODING": stdio_encoding}
                subprocess.run([sys.executable, "-c", code], input=fixture, cwd=ROOT,
                               env=env, check=True, timeout=30)
