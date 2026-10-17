"""Contract checks; the actual native keyboard/reflow result comes from Edge CI."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeTimelineZoomContract(unittest.TestCase):
    def test_ambiguous_owned_windows_emit_bounded_read_only_facts(self):
        helper = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        start = helper.index('if ($windows.Count -ne 1) {')
        end = helper.index('$window = $windows[0]', start)
        diagnostic = helper[start:end]
        for text in ['Select-Object -First 16', '[Math]::Min(17, $windows.Count)',
                     'truncated = ($windows.Count -gt 16)', '"zero"', '"multiple"',
                     'foreground_is_browser = ($foregroundPid -eq $OwnedBrowserPid)',
                     'hwnd = $_.ToInt64()', 'class = "Chrome_WidgetWin_1"',
                     'owner_is_browser = ($ownerPid -eq $OwnedBrowserPid)',
                     'LN_NATIVE_WINDOWS:', 'ConvertTo-Json -Depth 4 -Compress',
                     'throw "Expected exactly one visible window owned by the disposable Edge process."']:
            self.assertIn(text, diagnostic)
        for forbidden in ['SetForegroundWindow', 'ShowWindow', 'SendWait', 'CopyFromScreen',
                          'GetWindowText', 'MainWindowTitle', 'Start-Sleep']:
            self.assertNotIn(forbidden, diagnostic)
        self.assertLess(end, helper.index('[void][TimelineZoomWindow]::SetForegroundWindow($window)'))
        self.assertIn('try {\n    # Diagnostic facts only', diagnostic)
        self.assertIn('} catch {\n    # Evidence must not replace the original ownership failure', diagnostic)
        self.assertIn('try { [Console]::Error.WriteLine("LN_NATIVE_WINDOWS:unavailable"); [Console]::Error.Flush() } catch {}', diagnostic)
        self.assertLess(diagnostic.index('LN_NATIVE_WINDOWS:unavailable'), diagnostic.index('throw "Expected exactly one'))
        self.assertIn('ConvertTo-Json -Depth 4 -Compress))\n    [Console]::Error.Flush()', diagnostic)


    def test_prepare_phase_markers_are_fixed_and_bounded(self):
        helper = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        phases = ["entered", "process-lookup", "forms-load", "native-type-compile",
                  "owned-window-enumeration", "foreground", "drawing-load", "display-geometry",
                  "owned-dwm-bounds", "maximize-owned-window", "read-maximized-bounds",
                  "containment-check", "prepare-complete", "payload-built", "json-serialized", "output-emitted"]
        offsets = [helper.index(f'Write-NativePhase "{phase}"') for phase in phases]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn('[Console]::Error.Flush()', helper)
        source = (ROOT / "scripts/timeline-native-zoom-acceptance.cjs").read_text(encoding="utf-8")
        self.assertIn('const timeout = zoom === "prepare" ? 45000 : 15000;', source)
        self.assertIn('throw error;', source)
        self.assertLess(source.index('preparation = nativeKey("prepare")'), source.index('before = await metrics()'))
        self.assertIn('context.setDefaultTimeout(15000)', source)
        subprocess.run(["node", "-e", r"""
const assert = require('node:assert/strict');
const {nativeFailureEvidence} = require('./scripts/timeline-native-zoom-acceptance.cjs');
const r = nativeFailureEvidence('prepare', {code:'ETIMEDOUT',stderr:'secret\nLN_NATIVE_PHASE:entered|0\r\nLN_NATIVE_PHASE:unknown|0\n'+'LN_NATIVE_PHASE:forms-load|10\n'.repeat(500)});
assert.equal(r.code,'ETIMEDOUT'); assert.equal(r.phases.length,32); assert.equal(r.stderr_truncated,true);
assert(!JSON.stringify(r).includes('secret')); assert(!JSON.stringify(r).includes('unknown'));
assert.equal(nativeFailureEvidence('prepare',{code:'private',stderr:''}).code,'native-call-failed');
assert.equal(nativeFailureEvidence('x'.repeat(1000000),{}).action,'unknown');
assert.equal(nativeFailureEvidence('capture',{}).action,'capture');
const invalid = ['LN_NATIVE_PHASE:entered|NaN','LN_NATIVE_PHASE:entered|Infinity','LN_NATIVE_PHASE:entered|-1','LN_NATIVE_PHASE:entered|60001','LN_NATIVE_PHASE:entered|0.5'];
assert.deepEqual(nativeFailureEvidence('prepare',{stderr:invalid.join('\n')}).phases,[]);
const timed = nativeFailureEvidence('prepare',{stderr:'LN_NATIVE_PHASE:payload-built|14000\nLN_NATIVE_PHASE:json-serialized|13000\nLN_NATIVE_PHASE:output-emitted|14999'});
assert.deepEqual(timed.phases,[{phase:'payload-built',elapsed_ms:14000},{phase:'output-emitted',elapsed_ms:14999}]);
"""], cwd=ROOT, check=True, timeout=10)

    def test_prepare_payload_and_output_remain_equivalent(self):
        helper = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        payload = helper.split('$payload = ', 1)[1].split('\n    Write-NativePhase "payload-built"', 1)[0]
        self.assertEqual(payload, '@{ owned_pid = $OwnedBrowserPid; window = $window.ToInt64(); action = "prepare";\n       method = "maximize-owned-window-before-baseline"; before = $initialGeometry;\n       after = (Describe-Geometry $rect) }')
        self.assertIn('$json = $payload | ConvertTo-Json -Depth 5 -Compress', helper)
        self.assertIn('Write-NativePhase "json-serialized"\n    $json\n    Write-NativePhase "output-emitted"\n    exit 0', helper)
        self.assertIn('[Diagnostics.Stopwatch]::StartNew()', helper)
        self.assertIn('[Math]::Min(60000, [Math]::Max(0, $phaseClock.ElapsedMilliseconds))', helper)
        self.assertNotIn('[Console]::Out', helper)
        self.assertNotIn('[Environment]::Exit', helper)

    def test_translation_dismissal_is_exact_owned_and_before_keyboard_baseline(self):
        helper = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        action = helper.split('if ($Zoom -eq "dismiss-translation") {', 1)[1].split('if ($Zoom -in', 1)[0]
        for required in ('FromHandle($window)', '"Not now"', '"Translate"',
                         'Translate page from Chinese (Simplified)?', '$candidates.Count -ne 1',
                         'Compare($ancestor, $root)', '$ancestor.Current.ControlType -eq $documentType',
                         '$depth -lt 32', 'if (-not $reachedRoot)',
                         '$offer.Current.ProcessId -ne $OwnedBrowserPid',
                         '$button.Current.ProcessId -ne $OwnedBrowserPid', '$button.Current.IsOffscreen',
                         '$rootBounds.Contains($offerBounds)', 'Assert-OwnedForeground',
                         'TryGetCurrentPattern', ').Invoke()', '$remaining.Count -ne 0'):
            self.assertIn(required, action)
        for forbidden in ('SendWait', 'Send-OwnedZoomKey', 'WM_CLOSE', 'SetPreference'):
            self.assertNotIn(forbidden, action)
        self.assertLess(action.index('$ancestor.Current.ControlType -eq $documentType'), action.index('foreach ($ancestor in $ancestors)'))
        self.assertLess(action.index('if (-not $reachedRoot)'), action.index('foreach ($ancestor in $ancestors)'))
        ancestry = action.split('$ancestors =', 1)[1].split('foreach ($ancestor in $ancestors)', 1)[0]
        self.assertNotIn('$heading', ancestry, 'Matching a nested web-dialog heading must not short-circuit the Document ancestry rejection')
        source = (ROOT / "scripts/timeline-native-zoom-acceptance.cjs").read_text(encoding="utf-8")
        self.assertLess(source.index('nativeKey("prepare")'), source.index('nativeKey("dismiss-translation")'))
        self.assertLess(source.index('nativeKey("dismiss-translation")'), source.index('nativeKey("reset"); before'))
        self.assertIn('translation_offer:translationOffer', source)

    def test_additional_presets_and_secondary_controls(self):
        subprocess.run(["node", str(ROOT / "scripts/tests/timeline-native-zoom-matrix.cjs")], check=True, timeout=30)
        helper = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        self.assertIn('"90", "125", "150", "200"', helper)
        self.assertIn('Send-OwnedZoomKey "^{SUBTRACT}"', helper)
        self.assertIn('"125" = 2; "150" = 3; "200" = 5', helper)
        source = (ROOT / "scripts/timeline-native-zoom-acceptance.cjs").read_text(encoding="utf-8")
        self.assertIn("report.baseline_restored = restored", source)
        self.assertIn("additional_native_zoom_cases:zoomCases", source)

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
