"""Route Cocoa application Quit through LearnNote's existing window cleanup.

pywebview's Cocoa AppDelegate (checked in 5.4 and hosted 6.2.1) calls
``BrowserView.should_close`` but returns
NSTerminateNow, which exits without returning from ``webview.start``. AppKit
documents that cleanup after its main loop is not run by ``terminate:``:
https://developer.apple.com/documentation/appkit/nsapplication/terminate(_:)

Keep that same veto/confirmation check, then use BrowserView.destroy: it queues
NSWindow.close with AppHelper.callAfter (no wait on the GUI thread). close does
not ask windowShouldClose again. pywebview's existing windowWillClose stops the
loop after the last window, allowing backend and DesktopSession cleanup to run.
https://developer.apple.com/documentation/appkit/nswindow/close()

This adapter deliberately owns only LearnNote's single window. It preserves the
upstream delegate's other callbacks and restores its class/native references on
scope exit. No signal handlers, external automation, or shutdown API are added.
The public closing event alone cannot safely redirect Quit: scheduling destroy
inside one handler would ignore another handler's veto of the same event.
The dependency contract is BrowserView's instance registry, AppDelegate,
should_close/destroy, and WindowDelegate.windowWillClose; the shared-delegate
cache added after 5.4 is optional. Unsupported shapes fail at startup. Focused
tests execute the installed Cocoa methods, and packaged acceptance verifies
their real event-loop/cleanup behavior when the dependency changes.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import logging
import sys


logger = logging.getLogger(__name__)


class _QuitController:
    def __init__(self, browser_view, window):
        self.browser_view = browser_view
        self.window = window
        self.pending = False

    def request(self):
        # Cocoa invokes this on the GUI thread, including during a modal close
        # confirmation. Mark pending before asking, so nested Quit cannot recur.
        if self.pending:
            return 0  # NSTerminateCancel: continue the existing main loop.
        self.pending = True
        queued = False
        try:
            instances = self.browser_view.instances
            browser = instances.get(self.window.uid)
            if len(instances) != 1 or browser is None or browser.pywebview_window is not self.window:
                return 0
            if not self.browser_view.should_close(self.window):
                return 0
            # A closing callback/modal dialog may have changed the window set.
            current = self.browser_view.instances
            if (len(current) != 1 or current.get(self.window.uid) is not browser
                    or browser.pywebview_window is not self.window):
                return 0
            # Do not use Window.destroy's shown-event wait in a GUI callback.
            browser.destroy()
            queued = True
        except Exception:
            logger.exception("LearnNote native Quit could not close its owned window")
        finally:
            if not queued:
                self.pending = False
        return 0


@lru_cache(maxsize=1)
def _delegate_type(base):
    # Objective-C class names are process-global; create this subclass only once
    # even when sequential sessions use the context manager in one interpreter.
    class LearnNoteAppDelegate(base):
        _learnnote_quit_controller = None

        def applicationShouldTerminate_(self, app):
            controller = self._learnnote_quit_controller
            return controller.request() if controller is not None else 0

    return LearnNoteAppDelegate


@contextmanager
def native_quit_lifecycle(window):
    if sys.platform != "darwin":
        yield
        return

    try:
        from webview.platforms.cocoa import BrowserView
        original_class = BrowserView.AppDelegate
        required = (original_class.applicationShouldTerminate_, BrowserView.should_close,
                    BrowserView.destroy, BrowserView.WindowDelegate.windowWillClose_,
                    BrowserView.app.delegate, BrowserView.app.setDelegate_)
        if not isinstance(BrowserView.instances, dict) or not isinstance(original_class, type) or not all(map(callable, required)):
            raise TypeError("Unsupported Cocoa lifecycle contract")
    except (ImportError, AttributeError, TypeError) as error:
        raise RuntimeError("LearnNote macOS 窗口运行时不支持安全退出，请更新完整客户端。") from error

    # Install before pywebview constructs its native window/shared delegate.
    # Refuse a pre-existing Cocoa session rather than take over another owner.
    if BrowserView.instances or getattr(BrowserView, "_shared_app_delegate", None) is not None:
        raise RuntimeError("LearnNote native lifecycle requires a fresh Cocoa session")
    if getattr(original_class, "_learnnote_quit_controller", None) is not None:
        raise RuntimeError("LearnNote native lifecycle is already active")
    original_native_delegate = BrowserView.app.delegate()
    delegate = _delegate_type(original_class)
    if delegate._learnnote_quit_controller is not None:
        raise RuntimeError("LearnNote native lifecycle is already active")
    delegate._learnnote_quit_controller = _QuitController(BrowserView, window)
    BrowserView.AppDelegate = delegate
    failure = None
    try:
        yield
    except BaseException as error:
        failure = error
        raise
    finally:
        BrowserView.AppDelegate = original_class
        delegate._learnnote_quit_controller = None
        # Normal last-window close already clears these references. Also release
        # our delegate if native startup failed after it was allocated.
        if isinstance(getattr(BrowserView, "_shared_app_delegate", None), delegate):
            BrowserView._shared_app_delegate = None
        try:
            current = BrowserView.app.delegate()
            if current is None or isinstance(current, delegate):
                BrowserView.app.setDelegate_(original_native_delegate)
        except Exception:
            if failure is None:
                raise
            logger.exception("Secondary failure restoring the native app delegate")
