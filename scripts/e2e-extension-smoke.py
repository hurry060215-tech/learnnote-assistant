from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_PORT = 8765
SAMPLES_PORT = 8777
DEBUG_PORT = 9223


def project_python() -> str:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 20) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def wait_for_json(url: str, timeout_seconds: float = 45) -> dict:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return request_json("GET", url, timeout=3)
        except Exception as exc:  # noqa: BLE001 - startup diagnostics below
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def start_process(command: list[str], *, cwd: Path, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True)


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def browser_path(kind: str) -> Path | None:
    explicit = os.getenv("LEARNNOTE_E2E_BROWSER")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    chrome = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    edge = [
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    paths = edge if kind == "edge" else chrome
    return next((path for path in paths if path.exists()), None)


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CdpWebSocket:
    def __init__(self, websocket_url: str) -> None:
        parsed = urllib.parse.urlparse(websocket_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = int(parsed.port or 80)
        self.path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.next_id = 1
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"CDP websocket handshake failed: {response[:200]!r}")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise RuntimeError("CDP websocket closed")
            data += chunk
        return data

    def _recv_message(self) -> dict:
        fragments: list[bytes] = []
        while True:
            first, second = self._recv_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("CDP websocket closed by peer")
            if opcode in {0x1, 0x0}:
                fragments.append(payload)
                if fin:
                    return json.loads(b"".join(fragments).decode("utf-8"))

    def call(self, method: str, params: dict | None = None, timeout: float = 20) -> dict:
        message_id = self.next_id
        self.next_id += 1
        self._send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.sock.settimeout(max(0.5, deadline - time.time()))
            try:
                message = self._recv_message()
            except socket.timeout as exc:
                raise RuntimeError(f"Timed out waiting for CDP {method}") from exc
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})
        raise RuntimeError(f"Timed out waiting for CDP {method}")


def debug_json(debug_port: int, path: str, *, method: str = "GET", timeout: float = 10) -> dict | list:
    request = urllib.request.Request(f"http://127.0.0.1:{debug_port}{path}", method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_debug(debug_port: int) -> dict:
    return wait_for_json(f"http://127.0.0.1:{debug_port}/json/version", timeout_seconds=45)


def wait_for_service_worker(debug_port: int, timeout_seconds: float = 30) -> dict:
    deadline = time.time() + timeout_seconds
    seen: list[str] = []
    while time.time() < deadline:
        targets = debug_json(debug_port, "/json/list")
        for target in targets:
            url = target.get("url", "")
            if target.get("type") == "service_worker" and url.startswith("chrome-extension://"):
                seen_label = url
                probe: CdpWebSocket | None = None
                try:
                    probe = CdpWebSocket(target["webSocketDebuggerUrl"])
                    probe.call("Runtime.enable", timeout=5)
                    result = probe.call("Runtime.evaluate", {
                        "expression": "chrome.runtime.getManifest()",
                        "returnByValue": True,
                    }, timeout=5)
                    manifest = result.get("result", {}).get("value", {})
                    name = str(manifest.get("name", "")) if isinstance(manifest, dict) else ""
                    seen_label = f"{url} name={name}"
                    side_panel = manifest.get("side_panel", {}) if isinstance(manifest, dict) else {}
                    if (
                        name.startswith("LearnNote")
                        and manifest.get("manifest_version") == 3
                        and side_panel.get("default_path") == "sidepanel.html"
                    ):
                        return target
                except Exception as exc:
                    seen_label = f"{url} probe_error={exc}"
                finally:
                    if seen_label not in seen:
                        seen.append(seen_label)
                    if probe:
                        probe.close()
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for LearnNote extension service worker target. Saw: {seen}")


def eval_service_worker(cdp: CdpWebSocket, expression: str, timeout: float = 90) -> dict:
    wrapped = f"(async () => JSON.stringify(await ({expression})()))()"
    result = cdp.call("Runtime.evaluate", {
        "expression": wrapped,
        "awaitPromise": True,
        "returnByValue": True,
    }, timeout=timeout)
    if result.get("exceptionDetails"):
        raise RuntimeError(f"CDP evaluation failed: {result['exceptionDetails']}")
    value = result.get("result", {}).get("value")
    if value is None:
        raise RuntimeError(f"CDP evaluation returned no value: {result}")
    return json.loads(value)


def open_extension_tabs(cdp: CdpWebSocket, urls: list[str]) -> dict[str, int]:
    expression = f"""
async () => {{
  const urls = {json.dumps(urls)};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const opened = {{}};
  for (const url of urls) {{
    const tab = await chrome.tabs.create({{ url, active: true }});
    opened[url] = tab.id;
    await sleep(350);
  }}
  return {{ opened }};
}}
"""
    result = eval_service_worker(cdp, expression)
    opened = result.get("opened") or {}
    if len(opened) != len(urls):
        raise RuntimeError(f"Extension tab open mismatch: {result}")
    return {url: int(tab_id) for url, tab_id in opened.items()}


def collect_extension_context(cdp: CdpWebSocket, page_url: str, tab_id: int, wait_ms: int = 1200) -> dict:
    expression = f"""
async () => {{
  const targetUrl = {json.dumps(page_url)};
  const tabId = {int(tab_id)};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  let tab = null;
  for (let i = 0; i < 40; i++) {{
    try {{
      tab = await chrome.tabs.get(tabId);
    }} catch (error) {{
      tab = null;
    }}
    if (tab && tab.status === "complete") break;
    await sleep(250);
  }}
  if (!tab) {{
    const tabs = await chrome.tabs.query({{}});
    throw new Error("tab not found: " + targetUrl + " tabId=" + tabId + " open=" + tabs.map(item => item.id + ":" + (item.url || item.pendingUrl || "")).join(","));
  }}
  await chrome.tabs.update(tab.id, {{ active: true }});
  let response = {{}};
  let page = {{}};
  let resources = [];
  let captureLog = {{}};
  const deadline = Date.now() + Math.max({int(wait_ms)}, 1600) + 4200;
  while (Date.now() < deadline) {{
    await sleep(Math.min(Math.max({int(wait_ms)}, 400), 1000));
    response = await globalThis.__learnnoteE2E.collectContextForTab(tab.id);
    page = response.page || {{}};
    resources = response.resources || [];
    captureLog = response.capture_log || {{}};
    if (resources.length || page.active_video || Number(captureLog.restored || captureLog.total || 0)) break;
  }}
  const cookies = await chrome.cookies.getAll({{ url: targetUrl }}).catch(() => []);
  const cookieDomains = Array.from(new Set(cookies.map(item => item.domain).filter(Boolean))).sort();
  return {{
    tab: {{ id: tab.id, url: tab.url, title: tab.title, status: tab.status }},
    page: {{
      title: page.title,
      page_url: page.page_url,
      active_video: page.active_video,
      drm_detected: page.drm_detected,
      browser_subtitle_count: (page.browser_subtitles || []).length,
    }},
    resources: resources.slice(0, 30),
    captured_count: Number(captureLog.restored || captureLog.total || 0),
    cookie_count: cookies.length,
    cookie_domain_count: cookieDomains.length,
    cookie_domains: cookieDomains.slice(0, 12),
  }};
}}
"""
    return eval_service_worker(cdp, expression)


def assert_resource(context: dict, label: str, predicate) -> dict:
    for resource in context.get("resources", []):
        if predicate(resource):
            return resource
    summary = [
        {
            "url": item.get("url"),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "method": item.get("method"),
            "request_type": item.get("request_type"),
        }
        for item in context.get("resources", [])[:10]
    ]
    raise AssertionError(f"{label} resource not found. Top resources: {summary}")


def preflight(backend: str, page_url: str, resource: dict, label: str) -> dict:
    result = request_json("POST", f"{backend}/api/media/preflight", {
        "page_url": page_url,
        "resource": resource,
        "cookies": [],
    })["preflight"]
    if not result.get("downloadable"):
        raise AssertionError(f"{label} preflight failed: {result}")
    print(f"PASS browser preflight {label}: {result.get('kind') or resource.get('kind')} / {result.get('strategy')}")
    return result


def wait_for_task_media(backend: str, task_id: str, timeout_seconds: float = 70) -> dict:
    deadline = time.time() + timeout_seconds
    latest: dict = {}
    while time.time() < deadline:
        latest = request_json("GET", f"{backend}/api/tasks/{task_id}")
        task = latest.get("task", latest)
        if task.get("status") in {"success", "failed"}:
            if task.get("status") == "success" and task.get("media_path"):
                return task
            raise AssertionError(f"extension-started task failed: {task}")
        time.sleep(0.8)
    raise AssertionError(f"Timed out waiting for extension-started task {task_id}: {latest}")


def start_extension_download_only_task(cdp: CdpWebSocket, backend: str, tab_id: int, resource: dict) -> dict:
    expression = f"""
async () => {{
  const payload = await globalThis.__learnnoteE2E.startCurrentPageTaskForTab(
    {int(tab_id)},
    {json.dumps(backend)},
    [{json.dumps(resource)}],
    "download_only",
    {{
      visual_understanding: false,
      frame_interval: 20,
      grid_columns: 3,
      grid_rows: 3,
      transcriber: "faster-whisper",
      whisper_model: "small",
      note_style: "study",
      note_template: "standard",
      summary_depth: "brief"
    }}
  );
  return payload;
}}
"""
    payload = eval_service_worker(cdp, expression)
    if payload.get("error") or not payload.get("task_id"):
        raise AssertionError(f"extension background did not create download-only task: {payload}")
    return wait_for_task_media(backend, payload["task_id"])


def run_browser_checks(cdp: CdpWebSocket, backend: str, samples: str) -> None:
    mp4_page = f"{samples}/mp4.html"
    hls_page = f"{samples}/hls.html"
    post_page = f"{samples}/post-api.html"
    generic_page = f"{samples}/generic-player.html"
    blob_page = f"{samples}/blob-iframe.html"
    chaoxing_page = f"{samples}/chaoxing-mock.html"
    tab_ids = open_extension_tabs(cdp, [mp4_page, hls_page, post_page, generic_page, blob_page, chaoxing_page])

    mp4_context = collect_extension_context(cdp, mp4_page, tab_ids[mp4_page])
    mp4 = assert_resource(mp4_context, "mp4", lambda item: "/media/sample.mp4" in item.get("url", "") and item.get("kind") == "video")
    preflight(backend, mp4_page, mp4, "mp4")
    print(f"PASS extension collect mp4: resources={len(mp4_context['resources'])} captured={mp4_context['captured_count']}")
    mp4_task = start_extension_download_only_task(cdp, backend, tab_ids[mp4_page], mp4)
    print(f"PASS extension start download_only mp4: {mp4_task.get('id')} -> {mp4_task.get('media_path')}")

    hls_context = collect_extension_context(cdp, hls_page, tab_ids[hls_page])
    hls = assert_resource(hls_context, "hls", lambda item: "/hls/master.m3u8" in item.get("url", "") and item.get("kind") == "hls")
    preflight(backend, hls_page, hls, "hls")
    print(f"PASS extension collect hls: resources={len(hls_context['resources'])} captured={hls_context['captured_count']}")

    post_context = collect_extension_context(cdp, post_page, tab_ids[post_page], wait_ms=1800)
    post = assert_resource(post_context, "post-play-api", lambda item: "/api/play" in item.get("url", "") and item.get("method") == "POST")
    if not post.get("request_body", {}).get("content"):
        raise AssertionError(f"POST play API request body was not captured: {post}")
    preflight(backend, post_page, post, "post-play-api")
    print(f"PASS extension collect post-play-api: body={post.get('request_body', {}).get('type') or 'captured'} captured={post_context['captured_count']}")

    generic_context = collect_extension_context(cdp, generic_page, tab_ids[generic_page], wait_ms=1800)
    generic_api = next(
        (
            item for item in generic_context.get("resources", [])
            if "/api/lesson/resolve" in item.get("url", "")
        ),
        None,
    )
    generic_decoded = next(
        (
            item for item in generic_context.get("resources", [])
            if (
                ("/hls/master.m3u8" in item.get("url", "") or "/media/sample.mp4" in item.get("url", ""))
                and item.get("source") in {"pageHookGlobal", "scriptHint"}
            )
        ),
        None,
    )
    generic = generic_decoded or generic_api
    if generic is None:
        assert_resource(generic_context, "generic-player-api", lambda item: False)
    generic_body = (generic_api or generic).get("request_body", {}).get("content", "")
    if generic_api is None and generic.get("source") != "pageHookGlobal":
        raise AssertionError(f"Generic player API did not expose the endpoint or decoded response media: {generic_context}")
    if generic_body and ("generic-lesson-001" not in generic_body or "streamUrl" not in generic_body):
        raise AssertionError(f"Generic player API request body was malformed: {generic_api or generic}")
    preflight(backend, generic_page, generic, "generic-player-api")
    print(
        "PASS extension collect generic-player-api: "
        f"endpoint={'yes' if generic_api else 'no'} "
        f"body={(generic_api or generic).get('request_body', {}).get('type') or 'response-media'} "
        f"captured={generic_context['captured_count']}"
    )

    blob_context = collect_extension_context(cdp, blob_page, tab_ids[blob_page], wait_ms=2000)
    frame = assert_resource(blob_context, "blob iframe", lambda item: "/player/blob-source.html" in item.get("url", "") or "/player/blob-source.html" in item.get("frame_url", ""))
    frame_url = frame.get("frame_url") if "/player/blob-source.html" in frame.get("frame_url", "") else frame.get("url", "")
    fallback_frame = {
        **frame,
        "url": frame_url,
        "kind": "unknown",
        "source": "frame-context",
        "request_type": "page-scan-fallback",
        "page_url": blob_page,
        "frame_url": frame_url,
        "request_headers": {"Referer": blob_page},
    }
    report = request_json("POST", f"{backend}/api/media/preflight-current-page", {
        "page_url": blob_page,
        "resources": [fallback_frame],
        "cookies": [],
        "probe_limit": 3,
    })["report"]
    if not (report.get("candidate_count", 0) or report.get("page_scan", {}).get("attempted")):
        raise AssertionError(f"blob iframe fallback did not scan page/frame context: {report}")
    print(f"PASS extension collect blob-iframe: candidates={report.get('candidate_count')} ready={report.get('ready')}")

    chaoxing_context = collect_extension_context(cdp, chaoxing_page, tab_ids[chaoxing_page], wait_ms=2200)
    chaoxing = assert_resource(
        chaoxing_context,
        "chaoxing-mock",
        lambda item: "/ananas/status/play" in item.get("url", "") and item.get("method") == "POST",
    )
    body = chaoxing.get("request_body", {}).get("content", "")
    if "objectid=local-object-001" not in body or "dtoken=local-dtoken-001" not in body:
        raise AssertionError(f"Chaoxing mock request body did not include objectid/dtoken: {chaoxing}")
    if not chaoxing.get("frame_url") or "/chaoxing/player.html" not in chaoxing.get("frame_url", ""):
        raise AssertionError(f"Chaoxing mock did not preserve iframe context: {chaoxing}")
    if chaoxing_context.get("cookie_count", 0) < 1:
        raise AssertionError(f"Chaoxing mock cookie was not visible to extension context: {chaoxing_context}")
    cookie_summary = eval_service_worker(cdp, f"""
async () => {{
  return await globalThis.__learnnoteE2E.inspectCookieContextForTab({int(tab_ids[chaoxing_page])}, [{json.dumps(chaoxing)}]);
}}
""")
    if cookie_summary.get("count", 0) < 1 or cookie_summary.get("domain_count", 0) < 1:
        raise AssertionError(f"Chaoxing mock cookie diagnostic did not find login context: {cookie_summary}")
    preflight(backend, chaoxing_page, chaoxing, "chaoxing-mock")
    print(
        "PASS extension collect chaoxing-mock: "
        f"cookies={chaoxing_context.get('cookie_count')} "
        f"diagnostic_cookies={cookie_summary.get('count')} "
        f"body={chaoxing.get('request_body', {}).get('type') or 'captured'} "
        f"frame={chaoxing.get('frame_url')}"
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Run real Chrome/Edge LearnNote extension smoke checks against local sample pages.")
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT)
    parser.add_argument("--samples-port", type=int, default=SAMPLES_PORT)
    parser.add_argument("--debug-port", type=int, default=0, help="Chrome remote debugging port. Use 0 to pick a free port.")
    parser.add_argument("--browser", choices=["chrome", "edge"], default="edge")
    parser.add_argument("--keep-browser", action="store_true", help="Leave the temporary browser open after checks.")
    args = parser.parse_args()
    backend_port_explicit = "--backend-port" in sys.argv and args.backend_port != BACKEND_PORT
    samples_port_explicit = "--samples-port" in sys.argv and args.samples_port != SAMPLES_PORT

    browser = browser_path(args.browser)
    if not browser:
        raise RuntimeError(f"{args.browser} executable not found. Set LEARNNOTE_E2E_BROWSER to a Chrome/Edge executable.")
    if args.backend_port <= 0:
        args.backend_port = free_port()
    elif port_is_open(args.backend_port):
        if backend_port_explicit:
            raise RuntimeError(f"Backend port {args.backend_port} is already in use. Pass --backend-port 0 or choose another port.")
        replacement = free_port()
        print(f"INFO backend port {args.backend_port} is busy; using {replacement} for this smoke run.")
        args.backend_port = replacement
    if args.samples_port <= 0:
        args.samples_port = free_port()
    elif port_is_open(args.samples_port):
        if samples_port_explicit:
            raise RuntimeError(f"Samples port {args.samples_port} is already in use. Pass --samples-port 0 or choose another port.")
        replacement = free_port()
        print(f"INFO samples port {args.samples_port} is busy; using {replacement} for this smoke run.")
        args.samples_port = replacement
    if args.debug_port <= 0:
        args.debug_port = free_port()
    elif port_is_open(args.debug_port):
        raise RuntimeError(f"Debug port {args.debug_port} is already in use. Pass -DebugPort 0 or choose another port.")

    python = project_python()
    log_dir = ROOT / "data" / "test-runs" / "e2e-logs"
    backend = f"http://127.0.0.1:{args.backend_port}"
    samples = f"http://127.0.0.1:{args.samples_port}"
    profile_root = ROOT / "data" / "browser-profiles" / "e2e"
    profile_root.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix="learnnote-extension-e2e-", dir=str(profile_root)))
    backend_process: subprocess.Popen | None = None
    samples_process: subprocess.Popen | None = None
    browser_process: subprocess.Popen | None = None
    cdp: CdpWebSocket | None = None

    try:
        backend_process = start_process(
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.backend_port)],
            cwd=ROOT / "backend",
            log_path=log_dir / "extension-backend.log",
        )
        samples_process = start_process(
            [python, str(ROOT / "scripts" / "serve-samples.py"), "--port", str(args.samples_port)],
            cwd=ROOT,
            log_path=log_dir / "extension-samples.log",
        )
        health = wait_for_json(f"{backend}/health")
        if not health.get("ffmpeg"):
            raise RuntimeError(f"Backend health missing ffmpeg: {health}")
        urllib.request.urlopen(f"{samples}/", timeout=10).read()
        print(f"PASS extension smoke prerequisites: backend={backend} samples={samples}")

        extension_path = (ROOT / "extension").resolve()
        extension_arg = str(extension_path).replace("\\", "/")
        browser_process = subprocess.Popen([
            str(browser),
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={args.debug_port}",
            "--disable-component-extensions-with-background-pages",
            f"--disable-extensions-except={extension_arg}",
            f"--load-extension={extension_arg}",
            "--no-first-run",
            "--disable-first-run-ui",
            "--new-window",
            f"{samples}/mp4.html",
        ])
        wait_for_debug(args.debug_port)
        service_worker = wait_for_service_worker(args.debug_port)
        cdp = CdpWebSocket(service_worker["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        print(f"PASS extension service worker: {service_worker.get('url')}")

        run_browser_checks(cdp, backend, samples)
        print(f"PASS real browser extension smoke: browser={browser} profile={profile_dir}")
    finally:
        if cdp:
            cdp.close()
        if not args.keep_browser:
            stop_process(browser_process)
        stop_process(samples_process)
        stop_process(backend_process)


if __name__ == "__main__":
    main()
