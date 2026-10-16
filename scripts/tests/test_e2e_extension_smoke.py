from __future__ import annotations

import unittest
import importlib.util
import inspect
import json
import subprocess
from unittest.mock import Mock, patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


spec = importlib.util.spec_from_file_location("extension_smoke", ROOT / "scripts/e2e-extension-smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class ExtensionSmokeIsolationTests(unittest.TestCase):
    def test_browser_profile_and_logs_follow_the_isolated_data_directory(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("LEARNNOTE_DATA_DIR", str(ROOT / "data"))', source)
        self.assertIn('data_root / "browser-profiles" / "e2e"', source)
        self.assertIn('data_root / "test-runs" / "e2e-logs"', source)

    def test_temporary_browser_profile_is_removed_after_the_browser_stops(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        stop_browser = source.index("stop_process(browser_process)")
        remove_profile = source.index("shutil.rmtree(profile_dir, ignore_errors=True)")
        stop_samples = source.index("stop_process(samples_process)", stop_browser)

        self.assertGreater(remove_profile, stop_browser)
        self.assertLess(remove_profile, stop_samples)
        self.assertIn("if not args.keep_browser:", source[max(0, stop_browser - 120):stop_browser])

    def test_extension_smoke_reports_removed_chrome_cli_flags(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        self.assertIn("--(?:load-extension|disable-extensions-except)", source)
        self.assertIn("Chrome for Testing", source)
        self.assertIn("extension-browser.log", source)

    def test_hosted_real_extension_gate_uses_fresh_synthetic_profile_and_no_secrets(self) -> None:
        workflow = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")
        job = workflow.split("  extension-runtime:", 1)[1].split("  public-site:", 1)[0]
        self.assertIn("runs-on: windows-latest", job)
        self.assertIn("--browser edge --backend-port 0 --samples-port 0 --debug-port 0", job)
        self.assertIn("LEARNNOTE_DATA_DIR:", job)
        self.assertIn("unpacked checkout", job)
        self.assertIn("excluded =", job)
        self.assertNotIn("secrets.", job)
        self.assertNotIn("--keep-browser", job)
        self.assertNotIn("--no-sandbox", job)
        self.assertNotIn("browser-profiles", job.split("path:", 1)[1])
        self.assertIn("contents: read", workflow)

    def test_extension_smoke_requires_backend_protocol_compatibility(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        self.assertIn('heartbeat_health.get("extension_protocol_version") != heartbeat_health.get("protocol_version")', source)
        self.assertIn('heartbeat_health.get("extension_compatible") is False', source)

class ExtensionSeekSmokeTests(unittest.TestCase):
    def playback(self, seconds=3, **changes):
        return dict(currentTime=seconds, paused=True, seeking=False, currentSrc="http://127.0.0.1:8777/media/sample.mp4",
                    pageUrl="http://127.0.0.1:8777/mp4.html?seek-smoke=1&p=1", plays=0, seeks=1, sameElement=True, **changes)

    def message(self):
        return {"type": "seek-current-video", "seconds": 3, "targetTabId": 11, "sourceIdentity": {
            "tab_id": 11, "page_url": self.playback()["pageUrl"],
            "canonical_page_url": "http://127.0.0.1:8777/mp4.html?p=1", "active_video": {
                "frame_id": 0, "frame_url": self.playback()["pageUrl"],
                "current_src": self.playback()["currentSrc"], "seek_token": "synthetic-memory-only-token"}}}

    def test_positive_state_requires_actual_seek_without_transient_autoplay(self):
        smoke.assert_seek_video(self.playback(), 3, "click")
        for change in ({"currentTime": 0}, {"currentTime": float("nan")}, {"currentTime": float("inf")},
                       {"paused": False}, {"plays": 1}, {"seeking": True}, {"sameElement": False}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                smoke.assert_seek_video({**self.playback(), **change}, 3, "click")

    def test_unchanged_checks_detect_seek_even_when_time_returns_to_same_value(self):
        before = self.playback()
        smoke.assert_seek_unchanged(before, before.copy(), "twin")
        for change in ({"currentTime": 4}, {"seeks": 2}, {"plays": 1}, {"paused": False},
                       {"currentSrc": "other.mp4"}, {"pageUrl": "other.html"}, {"sameElement": False}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                smoke.assert_seek_unchanged(before, {**before, **change}, "twin")

    def test_real_request_must_bind_tab_frame_source_and_token_without_logging_token(self):
        message = self.message()
        args = (11, self.playback()["pageUrl"], self.playback()["currentSrc"])
        smoke.assert_seek_binding(message, *args)
        mutations = [({"targetTabId": 22}, {}, {}), ({"seconds": 0}, {}, {}),
                     ({}, {"tab_id": 22}, {}), ({}, {"page_url": "changed"}, {}),
                     ({}, {"canonical_page_url": "http://127.0.0.1:8777/mp4.html?p=2"}, {}),
                     ({}, {}, {"frame_id": 7}), ({}, {}, {"frame_url": "changed"}),
                     ({}, {}, {"current_src": "changed"}), ({}, {}, {"seek_token": ""})]
        for top, identity, active in mutations:
            changed = {**message, **top, "sourceIdentity": {**message["sourceIdentity"], **identity,
                       "active_video": {**message["sourceIdentity"]["active_video"], **active}}}
            with self.subTest(change=changed), self.assertRaises(AssertionError) as caught:
                smoke.assert_seek_binding(changed, *args)
            self.assertNotIn("synthetic-memory-only-token", str(caught.exception))

    def test_duplicate_url_target_lookup_excludes_original_tab(self):
        targets = [{"type": "page", "id": name, "url": "same", "webSocketDebuggerUrl": name} for name in ("source", "twin")]
        with patch.object(smoke, "debug_json", return_value=targets):
            self.assertEqual(smoke.wait_for_page_target(9223, "same", exclude_target_ids={"source"})["id"], "twin")

    def test_negative_replay_uses_runtime_and_checks_both_media_elements(self):
        watched = {"original": object(), "identical twin": object()}
        with patch.object(smoke, "read_seek_video", side_effect=[self.playback()] * 4) as read, \
                patch.object(smoke, "eval_service_worker", return_value={"ok": False, "code": "stale_source_identity"}) as evaluate:
            smoke.replay_rejected_seek(object(), self.message(), "stale_source_identity", watched)
        self.assertEqual(read.call_count, 4)
        expression = evaluate.call_args.args[1]
        self.assertIn("await chrome.runtime.sendMessage(", expression)
        self.assertNotIn("sendMessage =", expression)
        self.assertIn("ok: result?.ok, code: result?.code", expression)
        for result in ({"ok": True, "code": "stale_source_identity"}, {}, {"ok": False, "code": "other"}):
            with self.subTest(result=result), patch.object(smoke, "read_seek_video", return_value=self.playback()), \
                    patch.object(smoke, "eval_service_worker", return_value=result), self.assertRaises(AssertionError):
                smoke.replay_rejected_seek(object(), self.message(), "stale_source_identity", watched)
        with patch.object(smoke, "read_seek_video", side_effect=[self.playback(), self.playback(), self.playback(), {**self.playback(), "seeks": 2}]), \
                patch.object(smoke, "eval_service_worker", return_value={"ok": False, "code": "stale_source_identity"}), self.assertRaises(AssertionError):
            smoke.replay_rejected_seek(object(), self.message(), "stale_source_identity", watched)

    def run_fake_harness(self, *, clicked=True, cleanup_failure=None):
        # Exercise Python orchestration without opening a socket or browser.
        page_url = self.playback()["pageUrl"]
        message = self.message()
        expressions = []
        def evaluate(_cdp, expression, **_kwargs):
            expressions.append(expression)
            if "removeListener(observer.listener)" in expression:
                return {"cleaned": cleanup_failure != "observer"}
            if "const requests = [];" in expression:
                return {"id": 33, "url": "chrome-extension://synthetic/sidepanel.html?seek-smoke=1"}
            if "button.click()" in expression:
                return {"clicked": clicked}
            if "requests: globalThis.__learnnoteSeekObserver.requests" in expression:
                return {"requests": [message]}
            if "active: twin.active" in expression:
                return {"active": True, "url": page_url}
            return {"ready": True}
        original, twin, panel = Mock(), Mock(), Mock()
        if cleanup_failure == "connection":
            original.close.side_effect = RuntimeError("injected cleanup failure")
        states = [self.playback(0), self.playback(1), self.playback(), self.playback(), self.playback(1), self.playback(0), self.playback(1)]
        with patch.object(smoke, "open_extension_tabs", side_effect=[{page_url: 11}, {page_url: 22}]), \
                patch.object(smoke, "wait_for_page_target", side_effect=[{"id": str(index), "webSocketDebuggerUrl": str(index)} for index in range(3)]), \
                patch.object(smoke, "CdpWebSocket", side_effect=[original, twin, panel]), \
                patch.object(smoke, "prepare_seek_video") as prepare, \
                patch.object(smoke, "read_seek_video", side_effect=states), \
                patch.object(smoke, "eval_service_worker", side_effect=evaluate), \
                patch.object(smoke, "eval_page", return_value={"changed": True}), \
                patch.object(smoke, "replay_rejected_seek") as replay, \
                patch.object(smoke.time, "sleep"), patch("builtins.print") as output:
            if clicked:
                smoke.check_sidepanel_seek(object(), 9223, "http://127.0.0.1:8777")
            else:
                with self.assertRaisesRegex(AssertionError, "not rendered/clickable"):
                    smoke.check_sidepanel_seek(object(), 9223, "http://127.0.0.1:8777")
        return expressions, prepare, replay, output, (original, twin, panel)

    def test_harness_positive_click_precedes_negative_replays_and_cleans_only_owned_tabs(self):
        expressions, prepare, replay, output, connections = self.run_fake_harness()
        self.assertEqual(prepare.call_count, 3)
        self.assertEqual(replay.call_count, 6)
        self.assertEqual([call.args[2] for call in replay.call_args_list],
                         ["invalid_seek_time"] * 3 + ["stale_source_identity"] * 2 + ["source_tab_unavailable"])
        self.assertEqual(list(replay.call_args.args[3]), ["identical twin"])
        self.assertEqual([call.args[1]["seconds"] for call in replay.call_args_list[:3]], [-1, None, "3"])
        self.assertIn("button.getBoundingClientRect()", expressions[1])
        self.assertIn("button.click()", expressions[1])
        self.assertIn("preview.open = true", expressions[1])
        self.assertNotIn("sendMessage", expressions[1])
        self.assertIn("for (const id of [22, 33])", expressions[-1])
        self.assertIn("removeListener(observer.listener)", expressions[-1])
        self.assertNotIn("synthetic-memory-only-token", str(output.call_args_list))
        for connection in connections:
            connection.close.assert_called_once()

    def test_missing_timestamp_fails_without_replay_and_still_closes_owned_tabs(self):
        expressions, _prepare, replay, _output, connections = self.run_fake_harness(clicked=False)
        replay.assert_not_called()
        self.assertIn("for (const id of [11, 22, 33])", expressions[-1])
        for connection in connections:
            connection.close.assert_called_once()

    def test_cleanup_failure_preserves_primary_failure_and_attempts_all_owned_cleanup(self):
        for failure in ("connection", "observer"):
            with self.subTest(failure=failure):
                expressions, _prepare, replay, output, connections = self.run_fake_harness(clicked=False, cleanup_failure=failure)
                replay.assert_not_called()
                self.assertIn("for (const id of [11, 22, 33])", expressions[-1])
                self.assertIn("try { await chrome.tabs.remove(id); } catch", expressions[-1])
                self.assertIn("retaining the primary failure", str(output.call_args_list))
                for connection in connections:
                    connection.close.assert_called_once()

    def test_cleanup_failure_after_success_is_not_reported_as_pass(self):
        for failure in ("connection", "observer"):
            with self.subTest(failure=failure), self.assertRaisesRegex(RuntimeError, "Seek smoke cleanup failed"):
                self.run_fake_harness(cleanup_failure=failure)

    def test_generated_browser_javascript_parses_and_passive_listener_returns_undefined(self):
        expressions, *_ = self.run_fake_harness()
        observer, click = expressions[:2]
        cleanup = expressions[-1]
        with patch.object(smoke, "eval_service_worker", return_value={"ready": True}) as evaluate:
            smoke.prepare_seek_video(object(), 0, captions=True, replace=True)
            expressions.append(evaluate.call_args.args[1])
        with patch.object(smoke, "read_seek_video", return_value=self.playback()), \
                patch.object(smoke, "eval_service_worker", return_value={"ok": False, "code": "stale_source_identity"}) as evaluate:
            smoke.replay_rejected_seek(object(), self.message(), "stale_source_identity", {"twin": object()})
            expressions.append(evaluate.call_args.args[1])
        script = r"""
const assert = require("node:assert/strict"), vm = require("node:vm");
const { expressions, observer, click, cleanup } = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
for (const expression of expressions) new vm.Script("(" + expression + ")");
(async () => {
  let listener, clicks = 0;
  const sandbox = { chrome: { runtime: {
    onMessage: { addListener(value) { listener = value; } },
    getURL(path) { return "chrome-extension://synthetic/" + path; }
  }, tabs: { async update() {}, async create({ url }) { return { id: 33, url }; } } } };
  await vm.runInNewContext("(" + observer + ")()", sandbox);
  const request = { type: "seek-current-video", sourceIdentity: { active_video: { seek_token: "synthetic" } } };
  assert.equal(listener(request), undefined);
  assert.equal(sandbox.__learnnoteSeekObserver.requests.length, 1);
  request.type = "mutated-after-send";
  assert.equal(sandbox.__learnnoteSeekObserver.requests[0].type, "seek-current-video");
  listener({ type: "unrelated" });
  assert.equal(sandbox.__learnnoteSeekObserver.requests.length, 1);
  const preview = { hidden: false, open: false }, details = { open: false };
  const button = { disabled: false, closest() { return details; }, scrollIntoView() {},
    getBoundingClientRect() { return { width: 300, height: 40 }; }, click() { clicks++; } };
  const result = await vm.runInNewContext("(" + click + ")()", {
    document: { querySelector(selector) { return selector === "#sourcePreviewCard" ? preview : button; } }
  });
  assert.equal(result.clicked, true);
  assert.equal(clicks, 1);
  assert.equal(preview.open, true);
  assert.equal(details.open, true);
  const removed = [], cleanupSandbox = {
    __learnnoteSeekObserver: { listener() {} },
    chrome: { runtime: { onMessage: { removeListener() { throw new Error("observer cleanup failure"); } } },
      tabs: { async remove(id) { removed.push(id); if (id === 22) throw new Error("first tab cleanup failure"); } } }
  };
  const cleaned = await vm.runInNewContext("(" + cleanup + ")()", cleanupSandbox);
  assert.equal(cleaned.cleaned, false);
  assert.deepEqual(removed, [22, 33]);
  assert.equal("__learnnoteSeekObserver" in cleanupSandbox, false);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps(dict(expressions=expressions, observer=observer, click=click, cleanup=cleanup)),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_passive_observer_does_not_answer_or_replace_browser_apis(self):
        expressions, *_ = self.run_fake_harness()
        observer = expressions[0].split("const listener = message => {", 1)[1].split("};", 1)[0]
        self.assertIn("requests.push", observer)
        self.assertNotIn("return", observer)
        self.assertNotIn("sendResponse", observer)
        source = inspect.getsource(smoke.check_sidepanel_seek) + inspect.getsource(smoke.prepare_seek_video)
        for forbidden in ("permissions.request", "sendMessage =", "tabs.sendMessage =", ".play(", "fetch(", "request_json(", "--", "grantPermissions"):
            self.assertNotIn(forbidden, source)
        self.assertIn("video.pause()", source)
        self.assertIn('video.removeAttribute("autoplay")', source)
        self.assertIn("new VTTCue", source)
        self.assertIn("cloneNode(true)", source)
        self.assertIn("history.replaceState", source)
        self.assertIn("active.get(\"frame_id\") != 0", inspect.getsource(smoke.assert_seek_binding))


if __name__ == "__main__":
    unittest.main()
