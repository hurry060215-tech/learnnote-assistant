from contextlib import contextmanager
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import system


class UpdateActionTests(unittest.TestCase):
    @contextmanager
    def client(self, mode="desktop"):
        app=FastAPI();app.include_router(system.system_router)
        controller=SimpleNamespace(_update_lock=threading.RLock(),_update_state={"phase":"ready","version":"9.8.7","path":"owned-installer.exe"},_extension_update_state={},start_update_download=Mock(return_value={"ok":True}),apply_update=Mock(return_value={"ok":True}))
        app.state.desktop_update_api=controller
        release={"latest":{"version":"9.8.7","client":{"url":"https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Setup-x64.exe","sha256":"a"*64}},"capabilities":{}}
        with patch("app.config.DEPLOYMENT_MODE",mode), patch.object(system,"update_status",return_value=release):
            with TestClient(app,base_url="http://127.0.0.1:8765",headers={"Origin":"http://127.0.0.1:8765"}) as client:
                yield client,controller

    def test_server_selected_asset_and_single_use_intent(self):
        with self.client() as (client,controller):
            body={"action":"download","version":"9.8.7","component":"client"}
            token=client.post("/api/update/intent",json=body).json()["token"]
            headers={"X-LearnNote-Update-Intent":token}
            self.assertEqual(client.post("/api/update/action",json=body,headers=headers).status_code,200)
            self.assertEqual(controller.start_update_download.call_args.args[2],"a"*64)
            self.assertEqual(client.post("/api/update/action",json=body,headers=headers).status_code,403)
            self.assertEqual(controller.start_update_download.call_count,1)

    def test_apply_uses_owned_path_and_checks_scope(self):
        with self.client() as (client,controller):
            body={"action":"apply","version":"9.8.7","component":"client"}
            self.assertEqual(client.post("/api/update/intent",json={**body,"path":"evil.exe"}).status_code,422)
            self.assertEqual(client.post("/api/update/intent",json=body,headers={"Origin":"https://evil.example"}).status_code,403)
            token=client.post("/api/update/intent",json=body).json()["token"]
            self.assertEqual(client.post("/api/update/action",json=body,headers={"X-LearnNote-Update-Intent":token}).status_code,200)
            controller.apply_update.assert_called_once_with("9.8.7","owned-installer.exe","a"*64)

    def test_server_deployment_never_installs(self):
        with self.client("server") as (client,controller):
            self.assertEqual(client.post("/api/update/intent",json={"action":"apply","version":"9.8.7"}).status_code,403)
            controller.apply_update.assert_not_called()
