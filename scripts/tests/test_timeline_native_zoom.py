"""Contract checks; the actual native keyboard/reflow result comes from Edge CI."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeTimelineZoomContract(unittest.TestCase):
    def test_native_capture_diagnostics_and_hidden_overflow_fail_closed(self):
        subprocess.run(["node", str(ROOT / "scripts/tests/timeline-native-capture.cjs")], check=True, timeout=30)

    def test_setup_cleanup_and_reporting_failures_keep_original_error(self):
        subprocess.run(["node", str(ROOT / "scripts/tests/timeline-native-zoom-failures.cjs")], check=True, timeout=30)

    def test_keys_are_bound_to_owned_edge_process_and_window(self):
        source = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        for required in ("$OwnedBrowserPid", '$process.ProcessName -ne "msedge"', "OwnedWindows", "$windows.Count -ne 1", "GetWindowThreadProcessId", "GetForegroundWindow() -ne $window", 'Send-OwnedZoomKey "^0"', 'Send-OwnedZoomKey "^{ADD}"'):
            self.assertIn(required, source)
        for forbidden in ("SECURITY WARNING", "WM_CLOSE", "WM_COMMAND", "SetWindowPos", "--disable-extensions-except", "--load-extension"):
            self.assertNotIn(forbidden, source)

    def test_capture_is_owned_window_only_and_never_changes_zoom(self):
        source = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        capture = source.split('if ($Zoom -in @("prepare", "capture")) {', 1)[1].split('Send-OwnedZoomKey "^0"', 1)[0]
        for required in ("DwmGetWindowAttribute($window", "$display.Contains($bounds)", "Assert-OwnedForeground",
                         "CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)", "$colors.Count -lt 2", "exit 0"):
            self.assertIn(required, capture)
        self.assertIn("Assert-OwnedForeground", capture.split("function Read-OwnedBounds", 1)[1])
        self.assertLess(capture.index("$beforeCopy = Read-OwnedBounds"), capture.index("CopyFromScreen"))
        self.assertLess(capture.index("CopyFromScreen"), capture.index("$afterCopy = Read-OwnedBounds"))
        self.assertLess(capture.index("Assert-SameBounds $beforeCopy $afterCopy"), capture.index("$bitmap.Save"))
        for required in ("$screens.Count -ne 1", "$windowAwareness -lt 1", "GetDpiForWindow($window) -ne 96",
                         "$display.Left -ne 0", "$display.Top -ne 0", "$display.Equals($screens[0].Bounds)",
                         'coordinate_contract = "single-display-96-dpi"', "helper_thread_dpi_awareness", "bounds_stable = $true"):
            self.assertIn(required, capture)
        for forbidden in ("SetProcessDpiAwareness", "SetThreadDpiAwareness", "SetProcessDPIAware"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("SendWait", capture)
        self.assertNotIn("Send-OwnedZoomKey", capture)

    def test_owned_window_is_fitted_only_before_native_zoom_baseline(self):
        helper = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        prepare = helper.split('if ($Zoom -eq "prepare") {', 1)[1].split("$width =", 1)[0]
        self.assertIn("Assert-OwnedForeground", prepare)
        self.assertIn("ShowWindow($window, 3)", prepare)
        self.assertIn("$rect = Read-OwnedBounds", prepare)
        self.assertEqual(helper.count("::ShowWindow("), 1)
        self.assertIn("$display.Contains($bounds)", helper)
        self.assertIn("Geometry: $(Describe-Geometry $rect", helper)
        self.assertIn("before = $initialGeometry", helper)
        source = (ROOT / "scripts/timeline-native-zoom-acceptance.cjs").read_text(encoding="utf-8")
        self.assertLess(source.index('preparation = nativeKey("prepare")'), source.index('nativeKey("reset"); before = await metrics()'))
        self.assertLess(source.index('nativeKey("reset"); before = await metrics()'), source.index('nativeKey("200")'))

    def test_gate_measures_native_zoom_and_restores_owned_browser(self):
        source = (ROOT / "scripts/timeline-native-zoom-acceptance.cjs").read_text(encoding="utf-8")
        for required in ('channel: "msedge", headless: false', "server.process().pid", "viewport: null", 'nativeKey("200")', "devicePixelRatio / initial.dpr - 2", "innerWidth / initial.width - .5", "after.cssZoom", "after.documentZoom", "after.visualScale", "after.overflow", 'page.keyboard.press("Enter")', 'page.keyboard.press("End")', 'nativeKey("reset")', "server.close()"):
            self.assertIn(required, source)
        for forbidden in ("setDeviceMetricsOverride", "setPageScaleFactor", "deviceScaleFactor:", "style.zoom", "connectOverCDP", "launchPersistentContext", "--load-extension"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
