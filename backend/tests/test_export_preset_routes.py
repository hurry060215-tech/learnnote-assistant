import json
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers.knowledge_study import study_router


class ExportPresetContractTests(unittest.TestCase):
    def test_openapi_and_router_have_one_operation_per_method_path(self):
        app = FastAPI(); app.include_router(study_router)
        with warnings.catch_warnings(record=True) as messages:
            schema = app.openapi()
        self.assertFalse([warning for warning in messages if "Duplicate Operation ID" in str(warning.message)])
        ids = [operation["operationId"] for path in schema["paths"].values() for method, operation in path.items() if method in {"get","post","put","patch","delete"}]
        self.assertEqual(len(ids), len(set(ids)))
        routes = [(route.path, method) for route in study_router.routes for method in getattr(route, "methods", [])]
        self.assertEqual(routes.count(("/api/study/export-presets", "GET")), 1)

    def test_both_legacy_formats_round_trip_through_named_and_legacy_endpoints(self):
        app = FastAPI(); app.include_router(study_router)
        client = TestClient(app)
        fixtures = [{"My preset":{"font_size":12}}, {"schema_version":1,"presets":[{"id":"old-id","name":"My preset","options":{"font_size":12}}]}]
        for fixture in fixtures:
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as tmp, patch("app.routers.knowledge_study.DATA_DIR", Path(tmp)):
                (Path(tmp)/"export-presets.json").write_text(json.dumps(fixture))
                first = client.get("/api/study/export-presets").json()["presets"][0]
                self.assertEqual(first["name"], "My preset")
                self.assertEqual(client.put("/api/study/export-presets/My%20preset", json={"font_size":14}).status_code, 200)
                self.assertEqual(client.get("/api/study/export-presets").json()["presets"][0]["id"], first["id"])
                created = client.post("/api/study/export-presets", json={"name":"Second", "options":{"font_size":10}})
                self.assertEqual(created.status_code, 200)
                identity = created.json()["preset"]["id"]
                renamed = client.post("/api/study/export-presets", json={"id":identity,"name":"Renamed","options":{"font_size":11}})
                self.assertEqual(renamed.status_code, 200)
                self.assertEqual({item["name"] for item in client.get("/api/study/export-presets").json()["presets"]}, {"My preset","Renamed"})
                self.assertEqual(client.delete("/api/study/export-presets/My%20preset").status_code, 200)
                self.assertEqual(client.get("/api/study/export-presets").json()["presets"][0]["name"], "Renamed")
