from __future__ import annotations

import ast
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
import platform
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import webview
from webview.event import Event

from desktop import macos_lifecycle as lifecycle


ROOT = Path(__file__).resolve().parents[2]


def upstream_method(name, *, inner_class=None):
    """Exercise installed Cocoa methods without importing AppKit or opening UI."""
    source = Path(webview.__file__).parent / "platforms" / "cocoa.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BrowserView")
    if inner_class:
        owner = next(node for node in owner.body if isinstance(node, ast.ClassDef) and node.name == inner_class)
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    return compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), "exec")


SHOULD_CLOSE = upstream_method("should_close")
DESTROY = upstream_method("destroy")
WILL_CLOSE = upstream_method("windowWillClose_", inner_class="WindowDelegate")


class CocoaFixture:
    def __init__(self, *, shared=True):
        self.queue = []
        self.stopped = False
        self.native_delegate = None
        self.confirm = Mock(return_value=True)
        self.app = SimpleNamespace(
            delegate=lambda: self.native_delegate,
            setDelegate_=self.set_delegate,
            stop_=self.stop,
            abortModal=Mock(),
        )

        class OriginalDelegate:
            def applicationShouldTerminate_(self, app):
                return 1

            def applicationSupportsSecureRestorableState_(self, app):
                return True

        self.original = OriginalDelegate
        self.browser_view = SimpleNamespace(
            instances={}, AppDelegate=OriginalDelegate, app=self.app,
            display_confirmation_dialog=self.confirm,
        )
        if shared:
            self.browser_view._shared_app_delegate = None
        self.window = SimpleNamespace(
            uid="master", confirm_close=False,
            localization={"global.quit": "Quit", "global.cancel": "Cancel", "global.quitConfirmation": "Close?"},
        )
        self.window.events = SimpleNamespace(
            closing=Event(self.window, True), closed=Event(self.window), loaded=Event(self.window),
        )
        self.window.destroy = Mock(side_effect=AssertionError("Public destroy may block before shown"))
        namespace = {
            "Foundation": SimpleNamespace(YES=True, NO=False),
            "BrowserView": self.browser_view,
            "AppHelper": SimpleNamespace(callAfter=self.queue.append),
            "windows": [self.window],
        }
        for code in (SHOULD_CLOSE, DESTROY, WILL_CLOSE):
            exec(code, namespace)
        self.browser_view.destroy = namespace["destroy"]
        self.browser_view.WindowDelegate = SimpleNamespace(windowWillClose_=namespace["windowWillClose_"])
        self.browser_view.should_close = Mock(wraps=namespace["should_close"])
        self.browser_view.get_instance = lambda attr, value: next(
            (item for item in self.browser_view.instances.values() if getattr(item, attr) is value), None)
        self.native = SimpleNamespace()
        self.browser = SimpleNamespace(
            uid=self.window.uid, pywebview_window=self.window, window=self.native,
            webview=Mock(), closed=self.window.events.closed,
        )
        self.browser.destroy = Mock(side_effect=lambda: namespace["destroy"](self.browser))
        self.native.close = Mock(side_effect=lambda: namespace["windowWillClose_"](
            object(), SimpleNamespace(object=lambda: self.native)))

    def set_delegate(self, delegate):
        self.native_delegate = delegate

    def stop(self, _sender):
        self.stopped = True

    def start(self):
        self.browser_view.instances[self.window.uid] = self.browser
        delegate = self.browser_view.AppDelegate()
        if hasattr(self.browser_view, "_shared_app_delegate"):
            self.browser_view._shared_app_delegate = delegate
        self.set_delegate(delegate)
        return delegate

    def drain(self):
        while self.queue:
            self.queue.pop(0)()

    def install(self, stack):
        stack.enter_context(patch.object(lifecycle, "sys", SimpleNamespace(platform="darwin")))
        stack.enter_context(patch.dict(sys.modules, {
            "webview.platforms.cocoa": SimpleNamespace(BrowserView=self.browser_view),
        }))


class NativeQuitLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = CocoaFixture()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.fixture.install(self.stack)

    def enter(self):
        self.stack.enter_context(lifecycle.native_quit_lifecycle(self.fixture.window))
        return self.fixture.start()

    def test_accepted_quit_queues_existing_close_then_last_window_stops_loop(self):
        delegate = self.enter()
        self.fixture.window.confirm_close = True
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertFalse(self.fixture.stopped)
        self.assertEqual(len(self.fixture.queue), 1)
        self.fixture.native.close.assert_not_called()
        self.fixture.window.destroy.assert_not_called()
        self.fixture.confirm.assert_called_once_with("Quit", "Cancel", "Close?")
        self.fixture.browser_view.should_close.assert_called_once_with(self.fixture.window)
        self.assertTrue(delegate.applicationSupportsSecureRestorableState_(self.fixture.app))
        self.fixture.drain()
        self.assertTrue(self.fixture.stopped)
        self.assertTrue(self.fixture.window.events.closed.is_set())
        self.assertEqual(self.fixture.browser_view.instances, {})
        self.fixture.browser_view.should_close.assert_called_once()
        self.fixture.confirm.assert_called_once()
        self.stack.close()
        self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)
        self.assertIsNone(self.fixture.native_delegate)
        self.assertIsNone(self.fixture.browser_view._shared_app_delegate)

    def test_closing_veto_preserves_window_and_later_quit_can_retry(self):
        delegate = self.enter()
        veto = lambda: False
        self.fixture.window.events.closing += veto
        self.fixture.window.confirm_close = True
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.fixture.confirm.assert_not_called()
        self.assertEqual(self.fixture.queue, [])
        self.fixture.window.events.closing -= veto
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertEqual(len(self.fixture.queue), 1)
        self.fixture.confirm.assert_called_once()

    def test_normal_window_close_keeps_upstream_cleanup_without_application_quit(self):
        self.enter()
        self.assertTrue(self.fixture.browser_view.should_close(self.fixture.window))
        self.fixture.native.close()
        self.assertTrue(self.fixture.stopped)
        self.assertTrue(self.fixture.window.events.closed.is_set())
        self.assertEqual(self.fixture.queue, [])
        self.fixture.browser.destroy.assert_not_called()
        self.stack.close()
        self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)

    def test_confirmation_cancel_preserves_window_and_retry_checks_once(self):
        delegate = self.enter()
        self.fixture.window.confirm_close = True
        self.fixture.confirm.side_effect = [False, True]
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertEqual(self.fixture.queue, [])
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertEqual(self.fixture.confirm.call_count, 2)
        self.assertEqual(len(self.fixture.queue), 1)

    def test_reentrant_and_duplicate_quit_do_not_repeat_confirmation_or_destroy(self):
        delegate = self.enter()
        self.fixture.window.confirm_close = True
        def nested_quit(*_args):
            self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
            return True
        self.fixture.confirm.side_effect = nested_quit
        delegate.applicationShouldTerminate_(self.fixture.app)
        delegate.applicationShouldTerminate_(self.fixture.app)
        self.fixture.confirm.assert_called_once()
        self.fixture.browser.destroy.assert_called_once()
        self.assertEqual(len(self.fixture.queue), 1)

    def test_callback_failure_cancels_without_terminating_and_can_retry(self):
        delegate = self.enter()
        self.fixture.browser_view.should_close.side_effect = RuntimeError("synthetic confirmation failure")
        with self.assertLogs(lifecycle.logger, level="ERROR"):
            self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertEqual(self.fixture.queue, [])
        self.fixture.browser_view.should_close.side_effect = None
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertEqual(len(self.fixture.queue), 1)

    def test_scheduling_failure_cancels_and_can_retry(self):
        delegate = self.enter()
        destroy = self.fixture.browser.destroy.side_effect
        self.fixture.browser.destroy.side_effect = RuntimeError("synthetic queue failure")
        with self.assertLogs(lifecycle.logger, level="ERROR"):
            self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
        self.assertEqual(self.fixture.queue, [])
        self.fixture.browser.destroy.side_effect = destroy
        delegate.applicationShouldTerminate_(self.fixture.app)
        self.assertEqual(len(self.fixture.queue), 1)

    def test_foreign_stale_missing_or_new_window_never_gets_closed(self):
        for change in ("foreign", "stale", "missing", "during_confirmation", "replaced_registry", "replaced_owner"):
            with self.subTest(change=change):
                fixture = CocoaFixture()
                controller = lifecycle._QuitController(fixture.browser_view, fixture.window)
                fixture.start()
                if change == "foreign":
                    fixture.browser_view.instances["foreign"] = Mock()
                elif change == "stale":
                    fixture.browser.pywebview_window = Mock()
                elif change == "missing":
                    fixture.browser_view.instances.clear()
                else:
                    def change_windows(_window):
                        if change == "replaced_registry":
                            fixture.browser_view.instances = {"foreign": Mock()}
                        elif change == "replaced_owner":
                            fixture.browser.pywebview_window = Mock()
                        else:
                            fixture.browser_view.instances["foreign"] = Mock()
                        return True
                    fixture.browser_view.should_close.side_effect = change_windows
                self.assertEqual(controller.request(), 0)
                self.assertFalse(controller.pending)
                self.assertEqual(fixture.queue, [])

    def test_active_native_session_is_not_replaced(self):
        self.fixture.start()
        with self.assertRaisesRegex(RuntimeError, "fresh Cocoa session"):
            with lifecycle.native_quit_lifecycle(self.fixture.window):
                self.fail("Must refuse an existing native owner")
        self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)

    def test_unsupported_dependency_shape_fails_clearly_before_installing(self):
        for attribute in ("destroy", "should_close", "WindowDelegate", "instances"):
            with self.subTest(attribute=attribute), patch.object(self.fixture.browser_view, attribute, None):
                with self.assertRaisesRegex(RuntimeError, "LearnNote macOS"):
                    with lifecycle.native_quit_lifecycle(self.fixture.window):
                        self.fail("An unsupported runtime must not silently bypass cleanup")
                self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)

    def test_nested_scope_is_refused_before_creating_another_objc_class(self):
        with lifecycle.native_quit_lifecycle(self.fixture.window):
            original = self.fixture.browser_view.AppDelegate
            with self.assertRaisesRegex(RuntimeError, "already active"):
                with lifecycle.native_quit_lifecycle(self.fixture.window):
                    self.fail("Nested scope must not replace the delegate")
            self.assertIs(self.fixture.browser_view.AppDelegate, original)

    def test_launch_failure_restores_class_native_delegate_and_controller(self):
        previous = object()
        self.fixture.set_delegate(previous)
        with self.assertRaisesRegex(ValueError, "startup failed"):
            with lifecycle.native_quit_lifecycle(self.fixture.window):
                delegate = self.fixture.start()
                raise ValueError("startup failed")
        self.assertIs(self.fixture.native_delegate, previous)
        self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)
        self.assertIsNone(self.fixture.browser_view._shared_app_delegate)
        self.assertIsNone(delegate._learnnote_quit_controller)
        self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)

    def test_launch_failure_before_native_allocation_restores_class(self):
        with self.assertRaisesRegex(ValueError, "before native allocation"):
            with lifecycle.native_quit_lifecycle(self.fixture.window):
                delegate = self.fixture.browser_view.AppDelegate
                raise ValueError("before native allocation")
        self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)
        self.assertIsNone(delegate._learnnote_quit_controller)
        self.assertIsNone(self.fixture.native_delegate)

    def test_normal_close_restores_prior_native_delegate_but_preserves_foreign_replacement(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                fixture = CocoaFixture()
                previous, foreign = object(), object()
                fixture.set_delegate(previous)
                with ExitStack() as stack:
                    fixture.install(stack)
                    with lifecycle.native_quit_lifecycle(fixture.window):
                        delegate = fixture.start()
                        delegate.applicationShouldTerminate_(fixture.app)
                        fixture.drain()
                        self.assertIsNone(fixture.native_delegate)
                        if replace:
                            fixture.set_delegate(foreign)
                    self.assertIs(fixture.native_delegate, foreign if replace else previous)

    def test_delegate_restoration_failure_does_not_hide_launch_failure(self):
        with self.assertRaisesRegex(ValueError, "primary startup failure"), self.assertLogs(lifecycle.logger, level="ERROR"):
            with lifecycle.native_quit_lifecycle(self.fixture.window):
                self.fixture.start()
                self.fixture.app.setDelegate_ = Mock(side_effect=RuntimeError("secondary cleanup failure"))
                raise ValueError("primary startup failure")
        self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)

    def test_sequential_sessions_reuse_subclass_and_do_not_require_shared_delegate_cache(self):
        del self.fixture.browser_view._shared_app_delegate  # pywebview 5.4 layout
        with lifecycle.native_quit_lifecycle(self.fixture.window):
            first = self.fixture.browser_view.AppDelegate
        with lifecycle.native_quit_lifecycle(self.fixture.window):
            self.assertIs(self.fixture.browser_view.AppDelegate, first)
            delegate = self.fixture.start()
        self.assertIsNone(delegate._learnnote_quit_controller)
        self.assertIsNone(self.fixture.native_delegate)
        self.assertFalse(hasattr(self.fixture.browser_view, "_shared_app_delegate"))

    def test_non_macos_is_noop_and_host_platform_is_not_spoofed(self):
        host = (sys.platform, platform.system())
        for value in ("linux", "win32"):
            with patch.object(lifecycle, "sys", SimpleNamespace(platform=value)):
                with lifecycle.native_quit_lifecycle(self.fixture.window):
                    self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)
        self.assertEqual((sys.platform, platform.system()), host)

    def test_launcher_quit_runs_backend_finally_and_removes_real_session_marker(self):
        from desktop import main as desktop
        (ROOT / "data").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp:
            data = Path(temp).resolve()
            server = SimpleNamespace(should_exit=False, run=Mock())
            worker = Mock()
            parser = Mock()
            parser.parse_args.return_value = SimpleNamespace(
                port=12345, protocol="", wait_for_parent=0, apply_data_migration="",
                health_check=False, debug=False, webview_debug_port=0,
            )
            fake_webview = SimpleNamespace(settings={}, create_window=Mock(return_value=self.fixture.window))
            def start(**_kwargs):
                self.assertTrue((data / ".desktop-session.json").is_file())
                delegate = self.fixture.start()
                self.assertEqual(delegate.applicationShouldTerminate_(self.fixture.app), 0)
                self.assertFalse(server.should_exit)
                worker.join.assert_not_called()
                self.fixture.drain()
                self.assertTrue(self.fixture.stopped)
            fake_webview.start = Mock(side_effect=start)
            output = StringIO()
            with ExitStack() as stack:
                stack.enter_context(patch.dict(sys.modules, {
                    "webview": fake_webview,
                    "app.main": SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                }))
                stack.enter_context(patch.object(desktop, "argparse", SimpleNamespace(
                    ArgumentParser=Mock(return_value=parser), SUPPRESS="suppressed")))
                for name, value in {
                    "application_root": data, "configured_data_directory": data,
                    "backend_ready": False, "available_port": 12345, "configure_runtime": data,
                    "configure_model_runtime": None, "configure_webview_runtime": None,
                    "wait_for_backend": None, "server_config": object(),
                }.items():
                    stack.enter_context(patch.object(desktop, name, return_value=value))
                stack.enter_context(patch.object(desktop, "uvicorn", SimpleNamespace(Server=lambda _config: server)))
                stack.enter_context(patch.object(desktop, "threading", SimpleNamespace(
                    **(vars(threading) | {"Thread": lambda **_kwargs: worker}))))
                stack.enter_context(redirect_stdout(output))
                self.assertEqual(desktop._run(), 0)
            worker.start.assert_called_once()
            worker.join.assert_called_once_with(timeout=8)
            self.assertTrue(server.should_exit)
            self.assertFalse((data / ".desktop-session.json").exists())
            self.assertIn(f"LearnNote Desktop closed. Data kept at {data}", output.getvalue().splitlines())
            self.assertIs(self.fixture.browser_view.AppDelegate, self.fixture.original)


if __name__ == "__main__":
    unittest.main()
