from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("permission_acceptance", ROOT / "scripts/extension-permission-acceptance.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class PermissionAcceptanceContracts(unittest.TestCase):
    def clean_state(self):
        return dict(granted=False, other_granted=False, origins=["http://127.0.0.1/*", "http://localhost/*"],
                    resources=0, pages=0, capture_active=False, persisted_resources=0, persisted_site_resources=0)

    def test_ungranted_origin_is_distinct_from_required_loopback_hosts(self):
        manifest = __import__("json").loads((ROOT / "extension/manifest.json").read_text())
        self.assertNotIn(gate.ORIGIN, manifest["host_permissions"])
        self.assertNotIn(gate.OTHER_ORIGIN, manifest["host_permissions"])
        gate.assert_ungranted(self.clean_state())
        for change in ({"granted": True}, {"other_granted": True}, {"origins": ["http://*/*"]},
                       {"origins": ["https://*/*"]}, {"origins": ["<all_urls>"]}, {"origins": ["*://*/*"]}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                gate.assert_ungranted({**self.clean_state(), **change})

    def test_clearance_rejects_every_stale_evidence_store(self):
        gate.assert_cleared(self.clean_state())
        for field in ("resources", "pages", "capture_active", "persisted_resources", "persisted_site_resources"):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                gate.assert_cleared({**self.clean_state(), field: 1})

    def test_population_requires_every_store_before_cleanup(self):
        state = {**self.clean_state(), "granted": True, "resources": 1, "pages": 1,
                 "capture_active": True, "persisted_resources": 1, "persisted_site_resources": 1}
        gate.assert_populated(state)
        for field in ("granted", "resources", "pages", "capture_active", "persisted_resources", "persisted_site_resources"):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                gate.assert_populated({**state, field: 0})

    def test_browser_command_only_maps_the_two_synthetic_hosts(self):
        command = gate.browser_command(Path("edge.exe"), Path("temporary-profile"), 19234)
        self.assertIn("--user-data-dir=temporary-profile", command)
        self.assertIn("--remote-debugging-port=19234", command)
        self.assertIn(f"--host-resolver-rules=MAP {gate.HOST} 127.0.0.1, MAP {gate.OTHER_HOST} 127.0.0.1", command)
        for unsafe in ("no-sandbox", "disable-web-security", "ignore-certificate-errors", "auto-accept", "unsafe-extension-debugging"):
            self.assertFalse(any(unsafe in arg for arg in command))

    def test_native_driver_identifies_the_process_and_real_prompt(self):
        source = (ROOT / "scripts/extension-native-ui.ps1").read_text()
        self.assertIn("ProcessIdProperty, $BrowserProcessId", source)
        self.assertIn("$current.ControlType -eq $control::Document", source)
        self.assertIn("$text.Contains($ExpectedHost)", source)
        self.assertIn("$allow.Count -eq 1 -and $deny.Count -eq 1", source)
        self.assertIn("InvokePattern", source)
        self.assertIn("CopyFromScreen", source)
        self.assertIn("GetSupportedPatterns()", source)
        self.assertIn("the gate will not dismiss or bypass it", source)
        self.assertLess(source.index("$securityWarning ="), source.index("if ($Action -eq 'open-extension')"))
        self.assertNotIn("SendKeys", source)
        self.assertNotIn("mouse_event", source)

    def test_reauthorization_does_not_claim_a_guaranteed_second_prompt(self):
        source = (ROOT / "scripts/extension-permission-acceptance.py").read_text()
        self.assertIn('"browser_reused_previous_grant": not prompt', source)
        self.assertIn('"new_native_prompt": prompt', source)
        self.assertIn("chrome.permissions.onRemoved.addListener", source)
        self.assertIn('"Input.dispatchMouseEvent"', source)
        self.assertIn("await chrome.tabs.remove", source)
        for mock in ("chrome.permissions.request =", "chrome.permissions.contains =", "grantPermissions", '"userGesture": True'):
            self.assertNotIn(mock, source)

    def test_partial_native_scenario_is_retained_on_blocker(self):
        source = (ROOT / "scripts/extension-permission-acceptance.py").read_text()
        self.assertLess(source.index('report["scenarios"].append(scenario)'),
                        source.index('run_scenario(executable, profile, output / decision'))
        self.assertIn('result["browser_version"] = browser.version["Browser"]', source)

    def test_native_gate_is_manual_only_and_automatic_smoke_is_unchanged(self):
        source = (ROOT / ".github/workflows/ui-visual.yml").read_text()
        job = source.split("  extension-runtime:", 1)[1].split("  public-site:", 1)[0]
        self.assertNotIn("extension-permission-acceptance.py", source)
        self.assertNotIn("extension-native-ui.ps1", source)
        self.assertNotIn("build/extension-permissions", job)
        self.assertIn("python scripts/e2e-extension-smoke.py", job)
        native = (ROOT / ".github/workflows/native-permission-acceptance.yml").read_text()
        self.assertIn("  workflow_dispatch:", native)
        for automatic in ("  push:", "  pull_request:", "  schedule:", "  workflow_run:", "  repository_dispatch:"):
            self.assertNotIn(automatic, native)
        self.assertIn("contents: read", native)
        self.assertIn("timeout-minutes: 15", native)
        self.assertIn("python scripts/extension-permission-acceptance.py", native)
        self.assertIn("build/extension-permissions", native)
        self.assertNotIn("secrets.", native)
        self.assertNotIn("profile-allow", native)
        self.assertNotIn("continue-on-error", native)
        self.assertIn("Do not bypass browser security warnings", native)
        self.assertIn("timeout-minutes: 15", job)


if __name__ == "__main__":
    unittest.main()
