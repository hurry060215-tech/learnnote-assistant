from contextlib import contextmanager
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import system


class UpdateActionTests(unittest.TestCase):
    def test_extension_intents_bind_component_version_and_server_selected_asset(self):
        with self.client() as (client, controller):
            url = "https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Browser-Extension-v9.8.6.zip"
            release = {"latest": {"version": "9.8.7", "extension": {"version": "9.8.6", "available": True, "url": url, "sha256": "b" * 64}}}
            controller.start_extension_update_download = Mock(return_value={"ok": True})
            controller.apply_extension_update = Mock(return_value={"ok": True})
            controller._extension_update_state = {"phase": "ready", "version": "9.8.6", "path": "owned-extension.zip"}
            with patch.object(system, "update_status", return_value=release):
                for version, action, expected in (("9.8.7", "download", 409), ("9.8.6", "download", 200), ("9.8.6", "apply", 200)):
                    body = {"component": "extension", "action": action, "version": version}
                    token = client.post("/api/update/intent", json=body).json()["token"]
                    self.assertEqual(client.post("/api/update/action", json=body, headers={"X-LearnNote-Update-Intent": token}).status_code, expected)
            controller.start_extension_update_download.assert_called_once_with("9.8.6", url, "b" * 64)
            controller.apply_extension_update.assert_called_once_with("9.8.6", "owned-extension.zip", "b" * 64)

    @contextmanager
    def client(self, mode="desktop", client_supported=True):
        app=FastAPI();app.include_router(system.system_router)
        controller=SimpleNamespace(_update_lock=threading.RLock(),_update_state={"phase":"ready","version":"9.8.7","path":"owned-installer.exe"},_extension_update_state={},start_update_download=Mock(return_value={"ok":True}),apply_update=Mock(return_value={"ok":True}))
        app.state.desktop_update_api=controller
        release={"latest":{"version":"9.8.7","client":{"url":"https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Setup-x64.exe","sha256":"a"*64}},"capabilities":{}}
        with patch("app.config.DEPLOYMENT_MODE",mode), patch.object(system,"client_updater_supported",return_value=client_supported), patch.object(system,"update_status",return_value=release):
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

    def test_unsupported_platform_rejects_intents_and_direct_actions(self):
        with self.client(client_supported=False) as (client, controller):
            for action in ("download", "apply"):
                body = {"action": action, "version": "9.8.7", "component": "client"}
                for path in ("/api/update/intent", "/api/update/action"):
                    response = client.post(path, json=body)
                    self.assertEqual(response.status_code, 409)
                    self.assertIn("手动更新", response.json()["detail"])
            controller.apply_update.assert_not_called()
            controller.start_update_download.assert_not_called()
            self.assertEqual(client.post("/api/update/intent", json={"action": "download", "version": "9.8.7", "component": "extension"}).status_code, 200)
