from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop import main, startup


class StartupTests(unittest.TestCase):
    def test_protocol_accepts_local_open_and_validated_port_only(self):
        self.assertIsNone(startup.protocol_port("learnnote://open"))
        self.assertEqual(startup.protocol_port("learnnote://open?port=18898"), 18898)
        for value in ("https://example.com", "learnnote://delete", "learnnote://open?port=0",
                      "learnnote://open?port=65536", "learnnote://open?port=123&port=456",
                      "learnnote://open?url=https://example.com", "learnnote://open/path"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                startup.protocol_port(value)

    def test_health_rejects_unrelated_redirected_or_malformed_services(self):
        for body, status in (([], 200), ({"ok": True}, 200),
                             ({"ok": True, "app_version": "1", "backend_version": "1", "protocol_version": 1}, 200),
                             ({"service": "learnnote", "ok": True, "app_version": "1", "backend_version": "1", "protocol_version": 1}, 302)):
            response = Mock(status_code=status)
            response.json.return_value = body
            with self.subTest(body=body), patch.object(startup.requests, "get", return_value=response):
                self.assertFalse(startup.backend_ready("http://127.0.0.1:8765"))
        with patch.object(startup.requests, "get") as request:
            self.assertFalse(startup.backend_ready("https://example.com"))
            request.assert_not_called()

    def test_health_accepts_current_and_matching_legacy_contract(self):
        common = {"ok": True, "app_version": "0.2.3", "backend_version": "0.2.3", "protocol_version": 1}
        for extra in ({"service": "learnnote"}, {"api_version": 1, "task_schema_version": 1, "backend_origin": "http://127.0.0.1:8765"}):
            response = Mock(status_code=200)
            response.json.return_value = {**common, **extra}
            with patch.object(startup.requests, "get", return_value=response) as request:
                self.assertTrue(startup.backend_ready("http://127.0.0.1:8765"))
                self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_only_one_launch_owns_a_data_folder_and_fallback_port_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            first = startup.DesktopSession(Path(folder))
            second = startup.DesktopSession(Path(folder))
            try:
                self.assertTrue(first.acquire())
                first.publish("http://127.0.0.1:8768")
                self.assertFalse(second.acquire())
                with patch.object(startup, "backend_ready", return_value=True):
                    self.assertEqual(second.running_url(), "http://127.0.0.1:8768")
                first.close()
                self.assertTrue(second.acquire())
                self.assertEqual(second.running_url(), "")
            finally:
                first.close()
                second.close()

    def test_crashed_session_marker_is_discarded_before_new_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            session = startup.DesktopSession(Path(folder))
            session.endpoint_path.write_text(json.dumps({"url": "http://127.0.0.1:8769"}))
            try:
                self.assertTrue(session.acquire())
                self.assertFalse(session.endpoint_path.exists())
            finally:
                session.close()

    def test_session_never_requests_remote_or_corrupt_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            session = startup.DesktopSession(Path(folder))
            for text in ('{"url":"https://example.com"}', '{"url":25}', "[]", "broken"):
                session.endpoint_path.write_text(text)
                with patch.object(startup, "backend_ready") as ready:
                    self.assertEqual(session.running_url(), "")
                    ready.assert_not_called()

    def test_existing_workspace_opens_without_importing_or_starting_backend(self):
        with patch.object(main, "backend_ready", return_value=True), patch.object(main, "open_workspace") as open_url, patch.object(main, "configure_runtime") as configure:
            self.assertEqual(main.run_session(SimpleNamespace(port=18898), Path("unused"), Mock()), 0)
            open_url.assert_called_once_with("http://127.0.0.1:18898")
            configure.assert_not_called()

    def test_repeated_launch_waits_for_same_data_session(self):
        session = Mock()
        session.acquire.return_value = False
        session.running_url.return_value = "http://127.0.0.1:8770"
        with patch.object(main.sys, "argv", ["LearnNote.exe"]), patch.object(main, "DesktopSession", return_value=session), patch.object(main, "open_workspace") as open_url:
            self.assertEqual(main._run(), 0)
            open_url.assert_called_once_with("http://127.0.0.1:8770")
            session.close.assert_called_once()

    def test_dead_backend_thread_fails_without_waiting_for_timeout(self):
        worker = Mock()
        worker.is_alive.return_value = False
        with patch.object(main, "backend_ready") as ready, self.assertRaisesRegex(RuntimeError, "启动中断"):
            main.wait_for_backend("http://127.0.0.1:8765", worker=worker)
        ready.assert_not_called()

    def test_port_validation_and_upper_bound(self):
        for port in (0, -1, 65536):
            with self.assertRaises(ValueError):
                main.available_port(port)
        with patch.object(main.socket, "socket") as socket:
            socket.return_value.__enter__.return_value.bind.side_effect = OSError("occupied")
            with self.assertRaises(RuntimeError):
                main.available_port(65535)
            socket.return_value.__enter__.return_value.bind.assert_called_once_with(("127.0.0.1", 65535))

    def test_windowless_startup_failure_has_user_visible_error(self):
        with patch.object(main, "_run", side_effect=PermissionError("private details")), patch.object(main, "report_startup_error") as report:
            self.assertEqual(main.run(), 1)
            self.assertIsInstance(report.call_args.args[0], PermissionError)

    def test_startup_log_does_not_record_exception_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(main, "application_root", return_value=Path(folder)), patch.object(main.os, "name", "posix"), patch.object(main.sys, "stderr", io.StringIO()):
                main.report_startup_error(ValueError("secret-token-do-not-store"))
            log = (Path(folder) / "startup-error.log").read_text(encoding="utf-8")
            self.assertIn("ValueError", log)
            self.assertNotIn("secret-token", log)

    def test_restart_child_waits_for_original_process_and_keeps_port(self):
        with tempfile.TemporaryDirectory() as folder:
            api = main.DesktopApi(Path(folder), "http://127.0.0.1:18898")
            with patch.object(main.subprocess, "Popen") as launch:
                self.assertTrue(api.restart_application()["ok"])
            command = launch.call_args.args[0]
            self.assertEqual(command[-4:], ["--wait-for-parent", str(main.os.getpid()), "--port", "18898"])

    def test_restart_wait_finishes_when_parent_has_exited(self):
        with patch.object(startup.os, "name", "posix"), patch.object(startup.os, "kill", side_effect=ProcessLookupError) as probe:
            startup.wait_for_process_exit(123456)
            probe.assert_called_once_with(123456, 0)
        with self.assertRaises(ValueError):
            startup.wait_for_process_exit(startup.os.getpid())


if __name__ == "__main__":
    unittest.main()
