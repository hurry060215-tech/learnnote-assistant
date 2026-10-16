"""Actual optional host permission lifecycle, in disposable Windows Edge profiles.

The product extension and backend are unmodified. CDP reads evidence and clicks
the product panel; Windows UI Automation invokes the real toolbar/prompt. No
permission API replacement, profile editing, autogrant, or real account is used.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extension_smoke", ROOT / "scripts/e2e-extension-smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
HOST = "learnnote-permission.test"
OTHER_HOST = "learnnote-ungranted.test"
ORIGIN = f"http://{HOST}/*"
OTHER_ORIGIN = f"http://{OTHER_HOST}/*"


def wait_until(read, predicate, label: str, timeout: float = 20):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = read()
        if predicate(latest):
            return latest
        time.sleep(0.2)
    raise AssertionError(f"Timed out: {label}; last evidence={latest}")


def browser_command(browser: Path, profile: Path, debug_port: int) -> list[str]:
    extension = str((ROOT / "extension").resolve()).replace("\\", "/")
    return [str(browser), f"--user-data-dir={profile}", f"--remote-debugging-port={debug_port}",
            f"--disable-extensions-except={extension}", f"--load-extension={extension}",
            f"--host-resolver-rules=MAP {HOST} 127.0.0.1, MAP {OTHER_HOST} 127.0.0.1",
            "--no-first-run", "--disable-first-run-ui", "--lang=en-US",
            "--enable-logging=stderr", "--v=0", "--new-window", "about:blank"]


def assert_ungranted(state: dict) -> None:
    assert not state["granted"], "Synthetic origin was unexpectedly granted"
    assert not state["other_granted"], "The unrelated synthetic origin must stay ungranted"
    assert not set(state["origins"]) & {"http://*/*", "https://*/*", "*://*/*", "<all_urls>"}, "Unexpected blanket grant"


def assert_cleared(state: dict) -> None:
    assert_ungranted(state)
    for field in ("resources", "pages", "capture_active", "persisted_resources", "persisted_site_resources"):
        assert not state[field], f"Revocation retained {field}: {state[field]}"


def assert_populated(state: dict) -> None:
    assert state["granted"] and not state["other_granted"], "Only the selected origin should be granted"
    for field in ("resources", "pages", "capture_active", "persisted_resources", "persisted_site_resources"):
        assert state[field], f"Cleanup cannot be established from an empty pre-revocation {field}"


class Browser:
    def __init__(self, executable: Path, profile: Path, output: Path, backend: str):
        self.output = output
        self.debug_port = smoke.free_port()
        self.process = smoke.start_process(browser_command(executable, profile, self.debug_port),
                                           cwd=ROOT, log_path=output / "browser.log")
        self.worker = None
        self.panel = None
        self.browser_cdp = None
        try:
            self.version = smoke.wait_for_debug(self.debug_port)
            self.browser_cdp = smoke.CdpWebSocket(self.version["webSocketDebuggerUrl"])
            target = smoke.wait_for_service_worker(self.debug_port)
            self.worker = smoke.CdpWebSocket(target["webSocketDebuggerUrl"])
            self.worker.call("Runtime.enable")
            self.extension_id = target["url"].split("/")[2]
            self.run(f"""async () => {{
              await chrome.storage.local.set({{backendUrl: {json.dumps(backend)}, processingMode: 'quick'}});
              globalThis.__permissionAcceptanceRemoved = [];
              chrome.permissions.onRemoved.addListener(details =>
                globalThis.__permissionAcceptanceRemoved.push(...(details.origins || [])));
              return true;
            }}""")
        except Exception:
            self.close()
            raise

    def run(self, expression: str):
        return smoke.eval_service_worker(self.worker, expression)

    def native(self, action: str, label: str):
        prefix = str((self.output / label).resolve())
        completed = subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
            str(ROOT / "scripts/extension-native-ui.ps1"),
            "-BrowserProcessId", str(self.process.pid), "-Action", action,
            "-EvidencePrefix", prefix, "-ExpectedHost", HOST,
        ], capture_output=True, text=True, timeout=30)
        (self.output / f"{label}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"Native {action} failed: {completed.stderr[-1600:]}")

    def snapshot(self, tab_id: int = -1) -> dict:
        return self.run(f"""async () => {{
          const tabId = {tab_id};
          const stored = await chrome.storage.local.get(null);
          return {{
            granted: await chrome.permissions.contains({{origins: [{json.dumps(ORIGIN)}]}}),
            other_granted: await chrome.permissions.contains({{origins: [{json.dumps(OTHER_ORIGIN)}]}}),
            origins: (await chrome.permissions.getAll()).origins || [],
            resources: (resourceByTab.get(tabId) || []).length,
            pages: pageStateByTab.get(tabId)?.size || 0,
            capture_active: captureActive(tabId),
            persisted_resources: stored['captureLog:' + tabId]?.resources?.length || 0,
            persisted_site_resources: Object.entries(stored).filter(([key]) => key.startsWith('captureLog:'))
              .flatMap(([, log]) => log?.resources || []).filter(resource =>
                [resource.url, resource.page_url, resource.frame_url].some(url => permissionPatternMatchesUrl({json.dumps(ORIGIN)}, url))).length,
            removed_events: globalThis.__permissionAcceptanceRemoved
          }};
        }}""")

    def source(self, url: str) -> int:
        result = self.run(f"""async () => {{
          const tab = await chrome.tabs.create({{url: {json.dumps(url)}, active: true}});
          await chrome.windows.update(tab.windowId, {{focused: true}});
          return {{id: tab.id}};
        }}""")
        tab_id = int(result["id"])
        wait_until(lambda: self.run(f"async () => (await chrome.tabs.get({tab_id})).status"),
                   lambda status: status == "complete", "synthetic source loads")
        target = smoke.wait_for_page_target(self.debug_port, url)
        source = smoke.CdpWebSocket(target["webSocketDebuggerUrl"])
        try:
            assert smoke.eval_page(source, "(() => { document.cookie = 'learnnote_fixture=synthetic; SameSite=Lax; Path=/'; return document.cookie.includes('learnnote_fixture='); })()"), 'Synthetic fixture cookie was not set'
        finally:
            source.close()
        return tab_id

    def open_panel(self, label: str):
        self.native("open-extension", label)
        self.attach_panel()
        wait_until(self.panel_state, lambda s: s["ready"] and s["connection"] == "connected", "Side Panel ready")

    def attach_panel(self):
        # Rediscover after tab changes without invoking the extension action or
        # granting activeTab. A missing native panel is an explicit blocker.
        url = f"chrome-extension://{self.extension_id}/sidepanel.html"
        target = wait_until(lambda: next((t for t in smoke.debug_json(self.debug_port, "/json/list")
                                         if t.get("url") == url), None), bool, "real Side Panel target")
        if self.panel:
            self.panel.close()
        self.panel = smoke.CdpWebSocket(target["webSocketDebuggerUrl"])
        self.panel.call("Runtime.enable")

    def panel_state(self) -> dict:
        return smoke.eval_page(self.panel, """(() => ({
          ready: Boolean(document.querySelector('#sendButton') && !document.querySelector('#sendButton').disabled),
          connection: document.querySelector('#connectionCard')?.dataset.state,
          task_id: currentTaskId, sending, context: Boolean(currentContext),
          subtitle_count: currentContext?.page?.browser_subtitles?.length || 0,
          identity: displayedIdentity?.canonical_page_url || '',
          status: document.querySelector('#handoffStatus')?.textContent,
          status_kind: document.querySelector('#handoffStatus')?.dataset.state,
          permission_status: document.querySelector('#permissionStatus')?.textContent
        }))()""")

    def click(self, selector: str):
        # Real trusted input into the product document, not Runtime's userGesture override.
        point = smoke.eval_page(self.panel, f"""(() => {{
          const button = document.querySelector({json.dumps(selector)});
          if (!button || button.disabled) throw new Error('Product control is unavailable');
          button.scrollIntoView({{block: 'center', behavior: 'instant'}});
          const r = button.getBoundingClientRect();
          return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
        }})()""")
        for event in ("mousePressed", "mouseReleased"):
            self.panel.call("Input.dispatchMouseEvent", {"type": event, **point, "button": "left", "clickCount": 1})

    def screenshot(self, label: str):
        data = self.panel.call("Page.captureScreenshot", {"format": "png"})
        (self.output / f"{label}.png").write_bytes(base64.b64decode(data["data"]))

    def close(self):
        if self.panel:
            self.panel.close()
        if self.worker:
            self.worker.close()
        if self.browser_cdp:
            try:
                self.browser_cdp.call("Browser.close", timeout=5)
            except RuntimeError:
                pass  # Browser.close can close its socket before replying.
            finally:
                self.browser_cdp.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            smoke.stop_process(self.process)


def task_count(backend: str) -> int:
    return len(smoke.request_json("GET", f"{backend}/api/tasks")["tasks"])


def blocked_handoffs(browser: Browser, tab_id: int, backend: str) -> dict:
    # Send through the real runtime listener after closing the formerly authorized
    # tab. This does not grant activeTab or collect new page/cookie evidence.
    result = smoke.eval_service_worker(browser.panel, f"""async () => {{
      const result = {{}};
      for (const type of ['inspect-cookie-context', 'preflight-current-page', 'start-current-task']) {{
        result[type] = await chrome.runtime.sendMessage({{type, targetTabId: {tab_id},
          backendUrl: {json.dumps(backend)}, mode: 'video', defer: true}});
      }}
      return result;
    }}""")
    assert all(item.get("code") == "site_permission_required" for item in result.values()), result
    return {key: value["code"] for key, value in result.items()}


def run_scenario(executable: Path, profile: Path, output: Path, backend: str, samples_port: int,
                 decision: str, result: dict) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    source_url = f"http://{HOST}:{samples_port}/mp4.html?lesson={decision}"
    baseline_tasks = task_count(backend)
    result.update({"initial_decision": decision, "steps": [], "profile_is_fresh": True})
    browser = Browser(executable, profile, output, backend)
    try:
        result["browser_version"] = browser.version["Browser"]
        assert_ungranted(browser.snapshot())
        browser.source(f"http://{OTHER_HOST}:{samples_port}/mp4.html")
        tab_id = browser.source(source_url)
        browser.open_panel("toolbar-action")
        assert browser.panel_state()["subtitle_count"] == 0, "This fixture must use the deferred no-subtitle path"
        assert_ungranted(browser.snapshot(tab_id))
        assert task_count(backend) == baseline_tasks
        browser.click("#sendButton")
        browser.native(decision, f"native-{decision}")
        state = wait_until(browser.panel_state, lambda s: not s["sending"], "permission decision completes")
        browser.screenshot(f"after-{decision}")
        result["steps"].append({"native_prompt": decision, "panel": state})
        if decision == "deny":
            assert_ungranted(browser.snapshot(tab_id))
            assert not state["task_id"] and state["status_kind"] == "error", state
            assert task_count(backend) == baseline_tasks
        else:
            granted = wait_until(lambda: browser.snapshot(tab_id),
                                 lambda s: s["granted"] and all(s[k] for k in
                                     ("resources", "pages", "capture_active", "persisted_resources", "persisted_site_resources")),
                                 "real captured source evidence before revocation")
            assert_populated(granted)
            assert state["task_id"], state
            assert task_count(backend) == baseline_tasks + 1
            task = smoke.request_json("GET", f"{backend}/api/tasks/{state['task_id']}")["task"]
            assert task["page_url"] == source_url and task.get("awaiting_confirmation") is True, task
            assert not task.get("media_path"), "Permission gate must not start a download"
            # This is a deferred quick-mode handoff, never model work or a download.
            result["steps"].append({"granted_state": granted, "created_task": state["task_id"]})
            cookies = browser.run(f"""async () => ({{
              allowed: (await chrome.cookies.getAll({{url: {json.dumps(source_url)}}})).length,
              unrelated: (await chrome.cookies.getAll({{url: 'http://{OTHER_HOST}:{samples_port}/'}}).catch(() => [])).length
            }})""")
            assert cookies["allowed"] >= 1 and cookies["unrelated"] == 0, cookies
            smoke.eval_page(browser.panel, "(() => { document.querySelector('#permissionDetails').open = true; return true; })()")
            selector = f'#permissionList button[aria-label*="{HOST}"]'
            wait_until(lambda: smoke.eval_page(browser.panel, f"Boolean(document.querySelector({json.dumps(selector)}))"), bool, "origin revoke button")
            browser.click(selector)
            revoked = wait_until(lambda: browser.snapshot(tab_id),
                                 lambda s: not s["granted"] and ORIGIN in s["removed_events"] and
                                 not any(s[k] for k in ("resources", "pages", "capture_active", "persisted_resources")),
                                 "real onRemoved and cache cleanup")
            assert_cleared(revoked)
            assert not browser.panel_state()["context"], "Revoked Side Panel retained page context"
            browser.screenshot("after-revoke")
            browser.run(f"async () => {{ await chrome.tabs.remove({tab_id}); return true; }}")
            new_tab = browser.source(source_url + "-after-revoke")
            browser.attach_panel()
            blocked = blocked_handoffs(browser, new_tab, backend)
            fresh_denied = browser.snapshot(new_tab)
            assert_ungranted(fresh_denied)
            assert not any(fresh_denied[k] for k in ("resources", "pages", "persisted_site_resources")), fresh_denied
            assert task_count(backend) == baseline_tasks + 1
            result["steps"].append({"revoked_state": revoked, "old_tab_closed": True,
                                    "new_tab_denied_state": fresh_denied, "blocked_handoffs": blocked})
    finally:
        browser.close()

    # Restart the same disposable profile to verify the native persisted state.
    restarted_output = output / "restart"
    restarted_output.mkdir()
    browser = Browser(executable, profile, restarted_output, backend)
    try:
        persisted = browser.snapshot()
        assert_ungranted(persisted)
        result["steps"].append({"restart_ungranted": persisted})
        if decision == "allow":
            assert_cleared(persisted)
            browser.source(source_url + "-reauthorize")
            browser.open_panel("toolbar-reauthorize")
            before = task_count(backend)
            browser.click("#sendButton")
            # Chromium remembers permissions removed by the extension. It may
            # legitimately regrant after this explicit click without a new prompt.
            time.sleep(1)
            prompt = False
            if browser.panel_state()["sending"] and not browser.snapshot()["granted"]:
                browser.native("allow", "native-reauthorize")
                prompt = True
            state = wait_until(browser.panel_state, lambda s: not s["sending"], "explicit reauthorization")
            assert browser.snapshot()["granted"] and state["task_id"], state
            assert task_count(backend) == before + 1
            browser.screenshot("after-reauthorize")
            result["steps"].append({"explicit_reauthorization": True, "new_native_prompt": prompt,
                                    "browser_reused_previous_grant": not prompt, "panel": state})
    finally:
        browser.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/extension-permissions")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Native optional-permission acceptance requires Windows Edge and UI Automation; no mock fallback is available.")
    executable = smoke.browser_path("edge")
    if not executable:
        raise SystemExit("Microsoft Edge was not found; no other browser/profile is substituted.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="learnnote-permission-"))
    backend_port, samples_port = smoke.free_port(), smoke.free_port()
    backend = f"http://127.0.0.1:{backend_port}"
    env = dict(os.environ, LEARNNOTE_DATA_DIR=str(work / "data"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               ORT_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_TELEMETRY="1")
    backend_process = samples_process = None
    report = {"passed": False,
              "commit": os.getenv("GITHUB_SHA") or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "manifest_sha256": hashlib.sha256((ROOT / "extension/manifest.json").read_bytes()).hexdigest(),
              "extension_version": json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))["version"],
              "data": "synthetic loopback fixtures, fresh profiles, no credentials",
              "excluded": ["store installation or upgrade", "browser-settings hard revoke", "real accounts", "Chrome-specific acceptance"],
              "scenarios": []}
    try:
        backend_process = smoke.start_process([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
                                              cwd=ROOT / "backend", log_path=output / "backend.log", env=env)
        samples_process = smoke.start_process([sys.executable, str(ROOT / "scripts/serve-samples.py"), "--port", str(samples_port),
                                              "--data-dir", str(work / "samples")], cwd=ROOT, log_path=output / "samples.log", env=env)
        smoke.wait_for_json(f"{backend}/health")
        wait_until(lambda: smoke.port_is_open(samples_port), bool, "synthetic sample server", timeout=45)
        for decision in ("deny", "allow"):
            profile = work / f"profile-{decision}"
            scenario = {}
            report["scenarios"].append(scenario)
            run_scenario(executable, profile, output / decision, backend, samples_port, decision, scenario)
        report["passed"] = True
        print("PASS real Edge optional origin deny/allow/revoke/restart/explicit reauthorization")
    except Exception as exc:
        report["blocker"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        smoke.stop_process(samples_process)
        smoke.stop_process(backend_process)
        shutil.rmtree(work, ignore_errors=True)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
