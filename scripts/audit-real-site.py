from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPERS_PATH = ROOT / "scripts" / "e2e-extension-smoke.py"
DEFAULT_BACKEND_PORT = 8765


def load_helpers():
    spec = importlib.util.spec_from_file_location("learnnote_e2e_helpers", HELPERS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load helper module: {HELPERS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = load_helpers()


def compact_url(value: str, limit: int = 120) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    keep = max(20, (limit - 3) // 2)
    return f"{text[:keep]}...{text[-keep:]}"


def resource_summary(resources: list[dict], limit: int = 12) -> list[dict]:
    rows: list[dict] = []
    for item in resources[:limit]:
        body = item.get("request_body") or {}
        headers = item.get("request_headers") or {}
        safe_header_names = sorted(name for name in headers.keys() if "cookie" not in name.lower() and "authorization" not in name.lower())
        rows.append({
            "kind": item.get("kind") or "",
            "source": item.get("source") or "",
            "method": item.get("method") or "GET",
            "request_type": item.get("request_type") or "",
            "has_body": bool(body.get("content")),
            "frame_url": item.get("frame_url") or "",
            "safe_headers": safe_header_names,
            "url": item.get("url") or "",
        })
    return rows


def evidence_model(context: dict, preflight: dict | None = None) -> dict:
    resources = context.get("resources") or []
    page = context.get("page") or {}
    active = page.get("active_video") or {}
    haystack = " ".join(
        str(value or "")
        for item in resources[:30]
        for value in [
            item.get("url"),
            item.get("resolved_url"),
            item.get("frame_url"),
            item.get("label"),
            (item.get("request_body") or {}).get("content"),
        ]
    ).lower()
    direct_media = any(str(item.get("kind") or "").lower() in {"video", "audio", "hls", "dash"} for item in resources)
    replay_body = any(bool((item.get("request_body") or {}).get("content")) for item in resources)
    post_api = any(str(item.get("method") or "").upper() == "POST" for item in resources)
    iframe = any(bool(item.get("frame_url")) for item in resources)
    blob = str(active.get("src") or "").startswith("blob:") or any(item.get("blob_url") or item.get("kind") == "blob" for item in resources)
    chaoxing = any(token in haystack for token in ["chaoxing", "xuexitong", "mooc1", "mooc2", "fanya", "ananas", "objectid", "dtoken"])
    has = {
        "direct_media": direct_media,
        "playback_api": any(token in haystack for token in ["playurl", "play_url", "/play", "/stream", "ananas"]),
        "post_body": replay_body,
        "iframe": iframe,
        "cookie": int(context.get("cookie_count") or 0) > 0,
        "blob_or_mse": blob,
        "drm": bool(page.get("drm_detected")),
        "ananas": "ananas" in haystack,
        "playurl": "playurl" in haystack or "play_url" in haystack,
        "objectid": "objectid" in haystack,
        "dtoken": "dtoken" in haystack,
    }
    stages = [
        {
            "label": "browser_playback",
            "ok": direct_media or has["playback_api"] or blob,
            "detail": "media/API/blob evidence visible" if direct_media or has["playback_api"] or blob else "play the video for a few seconds and refresh detection",
        },
        {
            "label": "auth_context",
            "ok": has["cookie"] or not chaoxing,
            "detail": f"{context.get('cookie_count', 0)} cookies visible" if has["cookie"] else "logged-in site likely needs cookies" if chaoxing else "no site-specific auth evidence required",
        },
        {
            "label": "api_replay",
            "ok": replay_body or direct_media,
            "detail": "POST body/direct media available" if replay_body or direct_media else "no replayable POST body or direct media yet",
        },
        {
            "label": "download_preflight",
            "ok": bool((preflight or {}).get("ready") or (preflight or {}).get("downloadable")),
            "warn": preflight is None,
            "detail": "preflight ready" if preflight and (preflight.get("ready") or preflight.get("downloadable")) else "not run" if preflight is None else "preflight found no downloadable candidate",
        },
    ]
    missing = [stage["label"] for stage in stages if not stage["ok"] and not stage.get("warn")]
    return {
        "chaoxing_like": chaoxing,
        "has": has,
        "stages": stages,
        "missing": missing,
        "top_resources": resource_summary(resources),
    }


def markdown_report(audits: list[dict], backend: str) -> str:
    lines = [
        "# LearnNote real-site browser audit",
        "",
        f"- Time: {datetime.now().isoformat(timespec='seconds')}",
        f"- Backend: {backend}",
        "- Boundary: no tab recording, no DRM bypass, no progress spoofing, no auto-answering.",
        "",
    ]
    for audit in audits:
        context = audit["context"]
        page = context.get("page") or {}
        tab = context.get("tab") or {}
        evidence = audit["evidence"]
        preflight = audit.get("preflight")
        lines.extend([
            f"## {tab.get('title') or page.get('title') or audit['url']}",
            "",
            f"- URL: {audit['url']}",
            f"- Final tab URL: {tab.get('url') or '-'}",
            f"- Cookies visible: {context.get('cookie_count', 0)}",
            f"- Captured requests: {context.get('captured_count', 0)}",
            f"- Ranked resources: {len(context.get('resources') or [])}",
            f"- Active video: `{json.dumps(page.get('active_video') or {}, ensure_ascii=False)[:500]}`",
            f"- DRM detected: {'yes' if page.get('drm_detected') else 'no'}",
            f"- Chaoxing-like evidence: {'yes' if evidence['chaoxing_like'] else 'no'}",
            "",
            "### Evidence stages",
            "",
        ])
        for stage in evidence["stages"]:
            state = "PASS" if stage["ok"] else "WARN" if stage.get("warn") else "MISS"
            lines.append(f"- {state} `{stage['label']}`: {stage['detail']}")
        if evidence["missing"]:
            lines.extend(["", f"Missing chain: {', '.join(evidence['missing'])}"])
        if preflight:
            report = preflight.get("report") or preflight.get("preflight") or preflight
            lines.extend([
                "",
                "### Preflight",
                "",
                f"- Ready: {report.get('ready', report.get('downloadable', False))}",
                f"- Candidates: {report.get('candidate_count', '-')}",
                f"- Probed: {report.get('probed_count', '-')}",
                f"- Downloadable: {report.get('downloadable_count', '-')}",
                f"- E2E cookies handed off: {preflight.get('e2e_cookie_count', '-')}",
            ])
        lines.extend(["", "### Top resources", ""])
        for item in evidence["top_resources"]:
            flags = [
                item["kind"] or "unknown",
                item["source"] or "-",
                item["method"],
                "body" if item["has_body"] else "",
                "frame" if item["frame_url"] else "",
            ]
            lines.append(f"- {' / '.join(flag for flag in flags if flag)}: `{compact_url(item['url'], 140)}`")
            if item["safe_headers"]:
                lines.append(f"  - headers: {', '.join(item['safe_headers'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def preflight_current_page(cdp, backend: str, tab_id: int, resources: list[dict], probe_limit: int) -> dict:
    expression = f"""
async () => {{
  return await globalThis.__learnnoteE2E.preflightCurrentPageForTab(
    {int(tab_id)},
    {json.dumps(backend)},
    {json.dumps(resources[:20])},
    {int(probe_limit)}
  );
}}
"""
    return helpers.eval_service_worker(cdp, expression)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit real websites with the LearnNote MV3 extension and local backend.")
    parser.add_argument("urls", nargs="+", help="Real page URLs to open and audit.")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--debug-port", type=int, default=0)
    parser.add_argument("--browser", choices=["chrome", "edge"], default="edge")
    parser.add_argument("--profile-dir", default="", help="Optional D-drive browser profile for logged-in audits.")
    parser.add_argument("--wait-ms", type=int, default=3500, help="Wait after page load before collecting evidence.")
    parser.add_argument("--interactive-login", action="store_true", help="Pause so you can log in/play video before collection.")
    parser.add_argument("--preflight", action="store_true", help="Run backend preflight with extension-collected cookies.")
    parser.add_argument("--probe-limit", type=int, default=5)
    parser.add_argument("--keep-browser", action="store_true")
    args = parser.parse_args()

    browser = helpers.browser_path(args.browser)
    if not browser:
        raise RuntimeError(f"{args.browser} executable not found. Set LEARNNOTE_E2E_BROWSER.")
    debug_port = args.debug_port if args.debug_port > 0 else helpers.free_port()
    if helpers.port_is_open(debug_port):
        raise RuntimeError(f"Debug port {debug_port} is already in use.")

    backend = f"http://127.0.0.1:{args.backend_port}"
    python = helpers.project_python()
    out_dir = ROOT / "data" / "test-runs" / "site-audits" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile_dir).resolve() if args.profile_dir else Path(tempfile.mkdtemp(prefix="learnnote-site-audit-"))
    profile_dir.mkdir(parents=True, exist_ok=True)

    backend_process: subprocess.Popen | None = None
    browser_process: subprocess.Popen | None = None
    cdp = None
    try:
        backend_process = helpers.start_process(
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.backend_port)],
            cwd=ROOT / "backend",
            log_path=log_dir / "backend.log",
        )
        helpers.wait_for_json(f"{backend}/health")

        extension_path = (ROOT / "extension").resolve()
        extension_arg = str(extension_path).replace("\\", "/")
        browser_process = subprocess.Popen([
            str(browser),
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={debug_port}",
            "--disable-component-extensions-with-background-pages",
            f"--disable-extensions-except={extension_arg}",
            f"--load-extension={extension_arg}",
            "--no-first-run",
            "--disable-first-run-ui",
            "--new-window",
            args.urls[0],
        ])
        helpers.wait_for_debug(debug_port)
        service_worker = helpers.wait_for_service_worker(debug_port)
        cdp = helpers.CdpWebSocket(service_worker["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        tab_ids = helpers.open_extension_tabs(cdp, args.urls)

        if args.interactive_login:
            print("Log in if needed, play each target video for a few seconds, then press Enter to collect evidence.")
            input()
        else:
            time.sleep(max(0, args.wait_ms) / 1000)

        audits: list[dict] = []
        for url in args.urls:
            context = helpers.collect_extension_context(cdp, url, tab_ids[url], wait_ms=args.wait_ms)
            preflight_payload = None
            if args.preflight:
                preflight_payload = preflight_current_page(cdp, backend, tab_ids[url], context.get("resources") or [], args.probe_limit)
            evidence = evidence_model(context, preflight_payload.get("report") if preflight_payload else None)
            audits.append({
                "url": url,
                "context": context,
                "preflight": preflight_payload,
                "evidence": evidence,
            })
            print(f"AUDIT {url}: resources={len(context.get('resources') or [])} cookies={context.get('cookie_count', 0)} missing={','.join(evidence['missing']) or '-'}")

        (out_dir / "audit.json").write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "audit.md").write_text(markdown_report(audits, backend), encoding="utf-8")
        print(f"Report: {out_dir / 'audit.md'}")
    finally:
        if cdp:
            cdp.close()
        if not args.keep_browser:
            helpers.stop_process(browser_process)
        helpers.stop_process(backend_process)


if __name__ == "__main__":
    main()
