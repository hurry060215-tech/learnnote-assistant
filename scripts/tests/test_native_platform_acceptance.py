from contextlib import contextmanager
from pathlib import Path
import json
import importlib.util
import os
import platform
import stat
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_acceptance", ROOT / "scripts/native-platform-acceptance.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def isolated_sys(**changes):
    # Keep platform caches, imports, argparse and other test modules on the real host.
    return SimpleNamespace(**{**vars(sys), "path": list(sys.path), **changes})


@contextmanager
def cli_arguments(argv, **system_changes):
    factory = MODULE.argparse.ArgumentParser
    def parser(*args, **kwargs):
        kwargs.setdefault("prog", argv[0])
        instance = factory(*args, **kwargs)
        parse = instance.parse_args
        instance.parse_args = lambda: parse(argv[1:])
        return instance
    with patch.object(MODULE, "sys", isolated_sys(argv=argv, **system_changes)), patch.object(
            MODULE, "argparse", SimpleNamespace(ArgumentParser=parser)):
        yield


class NativePlatformAcceptanceTests(unittest.TestCase):
    def test_isolated_environment_drops_provider_and_user_data_paths(self):
        with patch.dict(os.environ, {"LEARNNOTE_DATA_DIR": "/private", "OPENAI_API_KEY": "synthetic-secret", "LLM_API_KEY": "synthetic-secret", "LEARNNOTE_MODEL_CACHE": "/private/models"}):
            env = MODULE.isolated_environment(Path("/tmp/synthetic"), 12345)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("LLM_API_KEY", env)
        self.assertNotIn("LEARNNOTE_MODEL_CACHE", env)
        self.assertEqual(env["LEARNNOTE_DATA_DIR"], str(Path("/tmp/synthetic")))
        self.assertEqual(env["LEARNNOTE_BACKEND_ORIGIN"], "http://127.0.0.1:12345")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")

    def test_http_does_not_follow_redirects_or_use_proxy_credentials(self):
        api = MODULE.Api(12345)
        self.assertFalse(api.session.trust_env)
        with patch.object(api.session, "request") as request:
            request.return_value.status_code = 200
            api.call("GET", "/health")
            self.assertFalse(request.call_args.kwargs["allow_redirects"])
            self.assertEqual(request.call_args.args[1], "http://127.0.0.1:12345/health")
        with self.assertRaises(ValueError):
            api.call("GET", "https://example.com")
        api.session.close()

    def test_unsigned_workflow_cannot_publish_or_access_signing_secrets(self):
        text = (ROOT / ".github/workflows/native-platform-acceptance.yml").read_text(encoding="utf-8")
        workflow = yaml.safe_load(text)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", text)
        self.assertNotIn("gh release", text)
        self.assertNotIn("--clobber", text)
        job = workflow["jobs"]["native-core"]
        self.assertEqual(set(job["strategy"]["matrix"]["os"]), {"ubuntu-latest", "macos-latest"})
        self.assertNotIn("continue-on-error", text)
        self.assertIn("--app dist/LearnNote.app", text)
        self.assertIn("if: always()", text)

    def test_migration_workflow_scopes_hidden_artifacts_and_native_only_flag(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/native-platform-acceptance.yml").read_text(encoding="utf-8"))
        events = workflow.get("on", workflow.get(True))
        for path in ("scripts/native-migration-quit.swift", "scripts/native-version-window.swift", "scripts/tests/test_native_platform_acceptance.py"):
            self.assertIn(path, events["pull_request"]["paths"])
        steps = workflow["jobs"]["native-core"]["steps"]
        native = next(step for step in steps if "--app dist/LearnNote.app" in step.get("run", ""))
        self.assertIn("--migration-smoke", native["run"])
        self.assertEqual(native["if"], "runner.os == 'macOS'")
        linux = next(step for step in steps if step.get("name") == "Exercise Linux source backend")
        self.assertNotIn("--migration-smoke", linux["run"])
        uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 2)
        state = next(step for step in uploads if step["with"].get("include-hidden-files"))
        self.assertEqual(state["if"], "always() && runner.os == 'macOS'")
        self.assertEqual(set(state["with"]["path"].splitlines()), {
            "build/native-acceptance/migration-smoke/source/",
            "build/native-acceptance/migration-smoke/destination/",
            "build/native-acceptance/migration-smoke/app-root/",
            "build/native-acceptance/migration-smoke/.learnnote-migration-*/",
            "build/native-acceptance/migration-smoke/previous-config.bin",
        })
        general = next(step for step in uploads if not step["with"].get("include-hidden-files"))
        self.assertEqual(general["if"], "always()")
        self.assertIn("!build/native-acceptance/capture-home/**", general["with"]["path"])
        self.assertIn("!build/native-acceptance/migration-smoke/*-home/**", general["with"]["path"])

    def test_macos_bundle_collects_dependencies_for_excluded_binary_layout(self):
        spec = (ROOT / "LearnNote.macos.spec").read_text(encoding="utf-8")
        self.assertIn("exclude_binaries=True", spec)
        self.assertIn("collection = COLLECT(", spec)
        self.assertIn("exe, a.binaries, a.datas", spec)
        self.assertIn("BUNDLE(\n    collection,", spec)

    def test_backup_annotation_uses_grouped_export_schema(self):
        backup = {"personal": {"annotations": [{"key": "material-fixture", "items": [{"text": MODULE.PERSONAL}]}]}}
        MODULE.assert_backup_annotation(backup, "fixture")
        backup["personal"]["annotations"][0]["items"][0]["text"] = "wrong"
        with self.assertRaises(AssertionError):
            MODULE.assert_backup_annotation(backup, "fixture")

    def test_failure_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            with cli_arguments(["native", "--output", directory]), patch.object(MODULE, "exercise", side_effect=RuntimeError("fixture failure")):
                with self.assertRaises(RuntimeError):
                    MODULE.main()
            import json
            report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertIn("fixture failure", report["error"])

    def test_isolation_redirects_home_and_cocoa_caches(self):
        with patch.dict(os.environ, {"HOME": "/private/home", "CFFIXED_USER_HOME": "/private/home",
                                     "PYTHONHOME": "/private/python", "PYTHONUSERBASE": "/private/site"}):
            env = MODULE.isolated_environment(Path("/tmp/fixture/source"), 12345)
        for key in ("HOME", "USERPROFILE", "CFFIXED_USER_HOME", "APPDATA", "LOCALAPPDATA",
                    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "CLANG_MODULE_CACHE_PATH", "SWIFT_MODULECACHE_PATH"):
            self.assertTrue(Path(env[key]).is_relative_to(Path("/tmp/fixture/source-home")), key)
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotIn("PYTHONUSERBASE", env)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_frozen_helper_uses_exact_executable_real_parent_and_no_source_import_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); executable = root / "LearnNote.app/Contents/MacOS/LearnNote"
            process = Mock(); process.poll.return_value = None
            args = ["--apply-data-migration", "a" * 32, "--migration-digest", "b" * 64, "--wait-for-parent", "456"]
            with patch.object(MODULE.subprocess, "Popen", return_value=process) as launch, patch.object(MODULE, "Api"):
                with MODULE.launched(executable, root / "source", root, "helper", 12345, args):
                    pass
            self.assertEqual(launch.call_args.args[0], [str(executable), *args, "--port", "12345"])
            self.assertEqual(launch.call_args.kwargs["cwd"], executable.parent)
            env = launch.call_args.kwargs["env"]
            self.assertNotIn("PYTHONPATH", env)
            self.assertEqual(env["LEARNNOTE_DATA_DIR"], str(root / "source"))
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=15)

    def test_constructor_and_cleanup_failures_preserve_primary_and_stop_process(self):
        for stage in ("constructor", "body"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                primary = RuntimeError("original failure")
                process = Mock(); process.poll.return_value = None
                api = Mock(); api.session.close.side_effect = OSError("secondary close")
                with patch.object(MODULE.subprocess, "Popen", return_value=process), patch.object(MODULE, "Api", return_value=api,
                        side_effect=primary if stage == "constructor" else None):
                    with self.assertRaises(RuntimeError) as caught:
                        with MODULE.launched(Path(temp) / "app", Path(temp) / "source", Path(temp), "helper", 12345):
                            raise primary
                self.assertIs(caught.exception, primary)
                process.terminate.assert_called_once()

    def test_copied_bundle_cleanup_does_not_mask_copy_failure(self):
        primary = RuntimeError("copy failed")
        temporary = Mock(name="temporary")
        temporary.name = "/tmp/synthetic-native-copy"
        temporary.cleanup.side_effect = OSError("cleanup failed")
        with patch.object(MODULE.tempfile, "TemporaryDirectory", return_value=temporary), patch.object(MODULE.shutil, "copytree", side_effect=primary):
            with self.assertRaises(RuntimeError) as caught:
                with MODULE.copied_native_app(Path("/tmp/synthetic.app/Contents/MacOS/LearnNote"), Path("/tmp")):
                    self.fail("Failed copy cannot launch")
        self.assertIs(caught.exception, primary)

    def test_packaged_root_matches_production_for_both_macos_layouts(self):
        from desktop import main as desktop
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "LearnNote.app/Contents/MacOS/LearnNote"
            executable.parent.mkdir(parents=True)
            for resources in (False, True):
                if resources:
                    (executable.parent.parent / "Resources/LearnNote").mkdir(parents=True)
                with patch.object(desktop, "sys", isolated_sys(frozen=True, platform="darwin", executable=str(executable))):
                    self.assertEqual(MODULE.packaged_application_root(executable), desktop.application_root())

    def test_wait_gate_rejects_each_early_activation_signal(self):
        for changed in ("old", "helper", "config", "target", "stage", "receipt"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); app = root / "app"; target = root / "target"
                app.mkdir(); target.mkdir()
                previous = b'{"data_dir":"synthetic"}'
                (app / "learnnote-config.json").write_bytes(previous)
                request = {"token": "a" * 32}
                receipt = app / ".data-migrations" / request["token"] / "receipt.json"
                receipt.parent.mkdir(parents=True)
                receipt.write_text('{"status":"scheduled"}', encoding="utf-8")
                old, helper = Mock(), Mock()
                old.poll.return_value = helper.poll.return_value = None
                MODULE.assert_waiting(old, helper, app, target, request, previous)
                if changed in {"old", "helper"}:
                    (old if changed == "old" else helper).poll.return_value = 1
                elif changed == "config":
                    (app / "learnnote-config.json").write_bytes(b"changed")
                elif changed == "target":
                    (target / "file").write_bytes(b"changed")
                elif changed == "stage":
                    (root / (".learnnote-migration-" + request["token"])).mkdir()
                else:
                    receipt.write_text('{"status":"copying"}', encoding="utf-8")
                with self.assertRaises(AssertionError):
                    MODULE.assert_waiting(old, helper, app, target, request, previous)

    def test_owned_capture_binds_native_pid_window_and_isolated_home(self):
        window = {"id": 123, "title": "LearnNote - Video Learning Notes", "bounds": {}}
        with tempfile.TemporaryDirectory() as temp, patch.object(MODULE.subprocess, "run", return_value=Mock(stdout=json.dumps([window]))) as run:
            output = Path(temp)
            (output / "helper.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            proof = MODULE.capture_native_window(72, output, "helper")
            self.assertEqual(proof["pid"], 72)
            self.assertEqual(run.call_args_list[0].args[0][-1], "72")
            self.assertEqual(run.call_args_list[1].args[0][:4], ["screencapture", "-x", "-l", "123"])
            self.assertTrue(Path(run.call_args.kwargs["env"]["HOME"]).is_relative_to(output))

    def test_migration_requires_packaged_macos_and_reports_source_scope(self):
        with patch.object(MODULE, "sys", isolated_sys(platform="linux")):
            with self.assertRaises(ValueError):
                MODULE.migration_smoke(Path("app"), Path("unused"))
        with cli_arguments(["gate", "--output", "unused", "--migration-smoke"]), patch.object(MODULE, "exercise") as exercise:
            with self.assertRaises(SystemExit):
                MODULE.main()
            exercise.assert_not_called()
        with tempfile.TemporaryDirectory() as temp, cli_arguments(["gate", "--output", temp]), patch.object(MODULE, "exercise", return_value={"status": "pass", "runtime": "linux_source_backend", "not_tested": []}):
            MODULE.main()
            report = json.loads((Path(temp) / "report.json").read_bytes())
            self.assertIn("packaged_data_migration", report["not_tested"])
            self.assertNotIn("migration", report)

    def test_report_failure_does_not_hide_primary_failure(self):
        primary = RuntimeError("migration failed")
        with tempfile.TemporaryDirectory() as temp, cli_arguments(["gate", "--output", temp]), patch.object(MODULE, "exercise", side_effect=primary), patch.object(MODULE, "write_json", side_effect=OSError("disk full")):
            with self.assertRaises(RuntimeError) as caught:
                MODULE.main()
        self.assertIs(caught.exception, primary)

    def test_capture_failure_still_stops_owned_app(self):
        primary = RuntimeError("capture unavailable")
        process = Mock(); process.poll.return_value = None
        api = Mock()
        api.call.return_value.json.side_effect = [{"ok": True, "service": "learnnote"}, {"focused": True}]
        api.call.return_value.text = "LearnNote"
        with tempfile.TemporaryDirectory() as temp, patch.object(MODULE, "free_port", return_value=12345), patch.object(MODULE.subprocess, "Popen", return_value=process), patch.object(MODULE, "Api", return_value=api), patch.object(MODULE, "capture_native_window", side_effect=primary):
            with self.assertRaises(RuntimeError) as caught:
                with MODULE.running(Path(temp) / "app", Path(temp) / "source", Path(temp), "native"):
                    self.fail("Unavailable capture cannot pass")
        self.assertIs(caught.exception, primary)
        process.terminate.assert_called_once()

    def test_selected_session_origin_accepts_only_canonical_bounded_loopback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            marker = root / ".desktop-session.json"
            self.assertIsNone(MODULE.selected_session_origin(root, 12345))
            for preferred, origin in ((12345, "http://127.0.0.1:12345"), (12345, "http://127.0.0.1:12364"),
                                      (65530, "http://127.0.0.1:65535")):
                marker.write_text(json.dumps({"url": origin}), encoding="utf-8")
                self.assertEqual(MODULE.selected_session_origin(root, preferred), origin)
            invalid = ("https://127.0.0.1:12345", "http://localhost:12345", "http://[::1]:12345",
                       "http://127.0.0.2:12345", "http://example.test:12345", "http://127.0.0.1:12345/",
                       "http://127.0.0.1:12345/path", "http://user@127.0.0.1:12345", "http://127.0.0.1:12345?x=1",
                       "http://127.0.0.1:12345#x", "http://127.0.0.1:012345", "http://127.0.0.1:0",
                       "http://127.0.0.1:65536", "http://127.0.0.1:12344", "http://127.0.0.1:12365",
                       " http://127.0.0.1:12345", "http://127.0.0.1:12345\n", 12345)
            for origin in invalid:
                with self.subTest(origin=origin):
                    marker.write_text(json.dumps({"url": origin}), encoding="utf-8")
                    with self.assertRaises(AssertionError):
                        MODULE.selected_session_origin(root, 12345)

    def test_selected_session_rejects_invalid_file_shape_size_encoding_and_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            marker = root / ".desktop-session.json"
            for raw in (b"[]", b"{}", b'{"url":"http://127.0.0.1:12345","pid":71}', b"{", b"\xff", b" " * 4097):
                with self.subTest(raw=raw[:60]):
                    marker.write_bytes(raw)
                    with self.assertRaises((AssertionError, ValueError)):
                        MODULE.selected_session_origin(root, 12345)
            marker.write_text('{"url":"http://127.0.0.1:12345"}', encoding="utf-8")
            with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFLNK, st_size=1)):
                with self.assertRaisesRegex(AssertionError, "marker file"):
                    MODULE.selected_session_origin(root, 12345)
            with patch.object(Path, "resolve", return_value=root / "elsewhere"):
                with self.assertRaisesRegex(AssertionError, "resolve elsewhere"):
                    MODULE.selected_session_origin(root, 12345)
            opened = marker.stat()
            with patch.object(MODULE.os, "fstat", return_value=SimpleNamespace(st_dev=opened.st_dev, st_ino=opened.st_ino + 1)):
                with self.assertRaisesRegex(AssertionError, "changed while opening"):
                    MODULE.selected_session_origin(root, 12345)

    def test_helper_readiness_waits_for_session_then_uses_only_selected_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); destination = root / "destination"; destination.mkdir()
            marker = destination / ".desktop-session.json"
            process = Mock(pid=71); process.poll.return_value = None
            api = Mock(origin="http://127.0.0.1:12345")
            health = {"ok": True, "service": "learnnote", "app_version": "fixture",
                      "data_paths": {"root": str(destination), "all_under_data_dir": True}}
            def call(method, path, **kwargs):
                self.assertEqual(api.origin, "http://127.0.0.1:12346")
                return SimpleNamespace(json=lambda: health if path == "/health" else {"focused": True}, text="LearnNote")
            api.call.side_effect = call
            clock = [0.0]
            def sleep(seconds):
                api.call.assert_not_called()
                clock[0] += seconds
                marker.write_text('{"url":"http://127.0.0.1:12346"}', encoding="utf-8")
            with patch.object(MODULE, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)), patch.object(
                    MODULE, "capture_native_window", return_value={"pid": 71, "visual_review_required": True}) as capture:
                self.assertEqual(MODULE.await_ready(process, api, root, "helper", native=True,
                                 session_root=destination, expected_version="fixture"), health)
            self.assertEqual([call.args[:2] for call in api.call.call_args_list], [("GET", "/health"), ("GET", "/"), ("POST", "/api/desktop/focus")])
            capture.assert_called_once_with(71, root, "helper")
            self.assertEqual(clock[0], .25)
            self.assertEqual(json.loads((root / "helper-window.json").read_bytes())["pid"], 71)

    def test_helper_session_timeout_and_death_never_probe_unadvertised_port(self):
        for dead in (False, True):
            with self.subTest(dead=dead), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve(); process = Mock(pid=71)
                process.poll.return_value = 1 if dead else None
                api = Mock(origin="http://127.0.0.1:12345")
                with patch.object(MODULE, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 90]), sleep=Mock())):
                    with self.assertRaises(AssertionError if dead else TimeoutError):
                        MODULE.await_ready(process, api, root, "helper", native=True,
                                           session_root=root, expected_version="fixture")
                api.call.assert_not_called()
                self.assertEqual(api.origin, "http://127.0.0.1:12345")

    def test_helper_session_cannot_substitute_wrong_backend_or_exited_process(self):
        for changed in ("service", "version", "root", "paths", "process"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                (root / ".desktop-session.json").write_text('{"url":"http://127.0.0.1:12346"}', encoding="utf-8")
                process = Mock(pid=71); process.poll.return_value = None
                api = Mock(origin="http://127.0.0.1:12345")
                health = {"ok": True, "service": "learnnote", "app_version": "fixture",
                          "data_paths": {"root": str(root), "all_under_data_dir": True}}
                if changed == "service": health["service"] = "foreign"
                elif changed == "version": health["app_version"] = "other"
                elif changed == "root": health["data_paths"]["root"] = str(root / "other")
                elif changed == "paths": health["data_paths"]["all_under_data_dir"] = False
                else: process.poll.side_effect = [None, 0]
                api.call.return_value.json.return_value = health
                with patch.object(MODULE, "capture_native_window") as capture, self.assertRaises(AssertionError):
                    MODULE.await_ready(process, api, root, "helper", native=True,
                                       session_root=root, expected_version="fixture")
                api.call.assert_called_once_with("GET", "/health")
                capture.assert_not_called()

    def test_helper_session_origin_change_does_not_scan_another_port(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); marker = root / ".desktop-session.json"
            marker.write_text('{"url":"http://127.0.0.1:12346"}', encoding="utf-8")
            process = Mock(pid=71); process.poll.return_value = None
            api = Mock(origin="http://127.0.0.1:12345")
            api.call.side_effect = MODULE.requests.ConnectionError("not ready")
            clock = [0.0]
            def sleep(seconds):
                clock[0] += seconds
                marker.write_text('{"url":"http://127.0.0.1:12347"}', encoding="utf-8")
            with patch.object(MODULE, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)):
                with self.assertRaisesRegex(AssertionError, "origin changed"):
                    MODULE.await_ready(process, api, root, "helper", native=True,
                                       session_root=root, expected_version="fixture")
            api.call.assert_called_once_with("GET", "/health")
            self.assertEqual(api.origin, "http://127.0.0.1:12346")

    def test_failed_migration_cannot_retain_passing_base_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app = root / "LearnNote.app"
            executable = app / "Contents/MacOS/LearnNote"
            executable.parent.mkdir(parents=True); executable.write_bytes(b"fixture")
            args = ["gate", "--app", str(app), "--output", str(root), "--migration-smoke"]
            with cli_arguments(args, platform="darwin"), patch.object(MODULE, "exercise", return_value={"status": "pass", "not_tested": []}), patch.object(MODULE, "migration_smoke", side_effect=RuntimeError("helper failed")):
                with self.assertRaisesRegex(RuntimeError, "helper failed"):
                    MODULE.main()
            self.assertEqual(json.loads((root / "report.json").read_bytes())["status"], "failed")
            (executable.parent / "learnnote-config.json").write_text('{"data_dir":"private"}', encoding="utf-8")
            with cli_arguments(args, platform="darwin"), patch.object(MODULE, "exercise") as exercise:
                with self.assertRaises(SystemExit):
                    MODULE.main()
                exercise.assert_not_called()

    def test_native_quit_requires_cleanup_and_never_falls_back_to_force(self):
        scenarios = ("unavailable", "destination", "missing_marker", "session_retained", "source_backend", "nonzero", "timeout", "wrong_identity", "rejected")
        for outcome in scenarios:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                output = Path(temp); source = output / "source"; source.mkdir()
                target = output / "destination"
                executable = output / "LearnNote.app/Contents/MacOS/LearnNote"
                endpoint = source / ".desktop-session.json"
                endpoint.write_text('{"url":"http://127.0.0.1:12345"}', encoding="utf-8")
                (output / "old-app.log").write_text("", encoding="utf-8")
                process = Mock(pid=71); process.poll.return_value = None
                api = Mock(origin="http://127.0.0.1:12345")
                if outcome == "unavailable":
                    api.session.get.side_effect = MODULE.requests.ConnectionError("closed")
                else:
                    api.session.get.return_value.status_code = 200
                    api.session.get.return_value.json.return_value = {"data_paths": {"root": str(source if outcome == "source_backend" else target)}}
                def wait(*, timeout):
                    self.assertEqual(timeout, 10)
                    if outcome == "timeout":
                        raise MODULE.subprocess.TimeoutExpired("owned native app", timeout)
                    if outcome != "session_retained":
                        endpoint.unlink()
                    if outcome != "missing_marker":
                        (output / "old-app.log").write_text(f"LearnNote Desktop closed. Data kept at {source}\n", encoding="utf-8")
                    return 1 if outcome == "nonzero" else 0
                process.wait.side_effect = wait
                request = {"pid": 72 if outcome == "wrong_identity" else 71,
                           "executable": str(executable.resolve()), "quit_requested": True}
                result = Mock(returncode=2 if outcome == "rejected" else 0, stdout=json.dumps(request), stderr="")
                with patch.object(MODULE.subprocess, "run", return_value=result) as run:
                    if outcome in {"unavailable", "destination"}:
                        proof = MODULE.quit_native_app(process, executable, source, target, api, output)
                        self.assertEqual(proof["status"], "pass")
                        self.assertTrue(proof["python_shutdown_marker"] and proof["session_marker_removed"])
                        self.assertEqual(proof["backend_after_exit"], outcome)
                    else:
                        with self.assertRaises(MODULE.subprocess.TimeoutExpired if outcome == "timeout" else AssertionError):
                            MODULE.quit_native_app(process, executable, source, target, api, output)
                        self.assertEqual(json.loads((output / "native-quit.json").read_bytes())["status"], "failed")
                    self.assertEqual(run.call_args.args[0][-2:], ["71", str(executable.resolve())])
                    self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
                    self.assertEqual(run.call_args.kwargs["timeout"], 15)
                process.terminate.assert_not_called()
                process.kill.assert_not_called()
                if outcome in {"wrong_identity", "rejected"}:
                    process.wait.assert_not_called()

    def test_native_quit_evidence_failure_preserves_primary(self):
        primary = RuntimeError("native request failed")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); source = output / "source"; source.mkdir()
            (source / ".desktop-session.json").write_text("{}", encoding="utf-8")
            process = Mock(pid=71); process.poll.return_value = None
            with patch.object(MODULE.subprocess, "run", side_effect=primary), patch.object(MODULE, "write_json", side_effect=OSError("disk full")):
                with self.assertRaises(RuntimeError) as caught:
                    MODULE.quit_native_app(process, output / "app", source, output / "target", Mock(), output)
            self.assertIs(caught.exception, primary)
            process.terminate.assert_not_called()

    def test_native_quit_helper_checks_exact_identity_without_permissions_or_force(self):
        helper = (ROOT / "scripts/native-migration-quit.swift").read_text(encoding="utf-8")
        for expected in ("NSRunningApplication(processIdentifier: pid)", "application.processIdentifier == pid",
                         "!application.isTerminated", "application.executableURL?", "executable == expected",
                         "resolvingSymlinksInPath()", "application.terminate()"):
            self.assertIn(expected, helper)
        for forbidden in ("forceTerminate", "kill(", "NSAppleScript", "AXIsProcessTrusted", "System Events"):
            self.assertNotIn(forbidden, helper)

    def test_offline_orchestration_uses_production_transaction_and_keeps_failure_evidence(self):
        from desktop import data_migration as migration
        host_platform, host_system = sys.platform, platform.system()
        for outcome in ("pass", "helper_failed", "source_changed", "shutdown_changed", "precommit_failed"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                output = Path(temp); executable = output / "LearnNote.app/Contents/MacOS/LearnNote"
                executable.parent.mkdir(parents=True); executable.write_bytes(b"synthetic frozen executable")
                processes = []; launches = []; clock = [0.0]
                @contextmanager
                def launch(exe, data, destination, phase, port, arguments=()):
                    process = Mock(pid=71 + len(processes)); process.poll.return_value = None
                    processes.append(process); launches.append((exe, data, list(arguments)))
                    api = Mock(origin=f"http://127.0.0.1:{port}"); api.call.return_value.json.return_value = {"material": {"material_id": "fixture", "sha256": "a" * 64}}
                    try:
                        yield process, api
                    finally:
                        process.poll.return_value = 0
                def ready(process, api, destination, phase, *, native, session_root=None, expected_version=None):
                    self.assertTrue(native)
                    source = destination / "source"
                    if phase == "old-app":
                        (source / ".desktop-session.lock").write_bytes(b"0")
                        (source / "preferences.json").write_text('{"theme":"light"}', encoding="utf-8")
                        return {"app_version": "fixture", "data_paths": {"root": str(source)}}
                    self.assertIsNotNone(processes[0].poll())
                    self.assertEqual(session_root, destination / "destination")
                    self.assertEqual(expected_version, "fixture")
                    api.origin = "http://127.0.0.1:12346"
                    if outcome == "helper_failed":
                        raise RuntimeError("synthetic frozen helper failure")
                    exe, _data, args = launches[1]
                    self.assertIs(migration.sys, sys)
                    self.assertEqual(sys.platform, host_platform)
                    self.assertEqual(platform.system(), host_system)
                    def checkpoint(phase):
                        if outcome == "precommit_failed" and phase == "copied":
                            raise OSError("injected precommit failure")
                    migration.apply_request(MODULE.packaged_application_root(exe), args[1], args[3], checkpoint=checkpoint)
                    return {"app_version": "fixture", "data_paths": {"root": str(destination / "destination"), "all_under_data_dir": True}}
                def exports(api, material, destination, phase):
                    if outcome == "source_changed" and phase == "after":
                        (destination / "source/preferences.json").write_text('{"theme":"changed"}', encoding="utf-8")
                    return {"export": "identical"}
                def close(process, exe, source, target, api, destination):
                    process.poll.return_value = 0
                    if outcome == "shutdown_changed":
                        (source / "preferences.json").write_text('{"theme":"shutdown write"}', encoding="utf-8")
                def sleep(seconds):
                    clock[0] += seconds
                with patch.object(MODULE, "sys", isolated_sys(platform="darwin")), patch.object(MODULE, "free_port", return_value=12345), patch.object(MODULE, "launched", side_effect=launch), patch.object(MODULE, "await_ready", side_effect=ready), patch.object(MODULE, "migration_exports", side_effect=exports), patch.object(MODULE, "quit_native_app", side_effect=close), patch.object(MODULE, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)):
                    if outcome == "pass":
                        report = MODULE.migration_smoke(executable, output)
                        self.assertEqual(report["status"], "pass")
                    else:
                        error = RuntimeError if outcome == "helper_failed" else OSError if outcome == "precommit_failed" else AssertionError
                        message = "helper failure" if outcome == "helper_failed" else "precommit failure" if outcome == "precommit_failed" else "durable source"
                        with self.assertRaisesRegex(error, message):
                            MODULE.migration_smoke(executable, output)
                evidence = output / "migration-smoke"
                self.assertTrue((evidence / "source").is_dir())
                self.assertTrue((evidence / "destination").is_dir())
                self.assertEqual(launches[0][0], launches[1][0])
                self.assertEqual(launches[0][1], launches[1][1])  # Never fake config with destination env.
                self.assertEqual(launches[1][2][-2:], ["--wait-for-parent", "71"])
                receipt = next((evidence / "app-root/data-migrations").glob("*/receipt.json"))
                previous = (receipt.parent / "previous-config.bin").read_bytes()
                self.assertEqual(previous, (evidence / "previous-config.bin").read_bytes())
                expected_status = "scheduled" if outcome in {"helper_failed", "shutdown_changed"} else "failed" if outcome == "precommit_failed" else "complete"
                self.assertEqual(json.loads(receipt.read_bytes())["status"], expected_status)
                if outcome == "precommit_failed":
                    hidden = evidence / (".learnnote-migration-" + receipt.parent.name)
                    self.assertEqual((evidence / "source/preferences.json").read_bytes(), (hidden / "preferences.json").read_bytes())
                    self.assertEqual((evidence / "app-root/learnnote-config.json").read_bytes(), previous)
                    self.assertEqual(json.loads(receipt.read_bytes())["stage"], str(hidden))
                if outcome == "pass":
                    backend = json.loads((evidence / "restarted-backend.json").read_bytes())
                    self.assertEqual(backend["requested_origin"], "http://127.0.0.1:12345")
                    self.assertEqual(backend["selected_origin"], "http://127.0.0.1:12346")
                    self.assertEqual(backend["routing_source"], "destination/.desktop-session.json")
                self.assertFalse((executable.parent / "learnnote-config.json").exists())
                self.assertFalse(launches[0][0].exists())  # Disposable bundle removed after evidence capture.


if __name__ == "__main__":
    unittest.main()
