from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPERS_PATH = ROOT / "scripts" / "e2e-extension-smoke.py"
DEFAULT_BACKEND_PORT = 8765
DIRECT_MEDIA_KINDS = {"video", "audio", "hls", "dash"}
PLAY_API_TOKENS = [
    "playurl",
    "play_url",
    "playurls",
    "video_url",
    "media_url",
    "/play",
    "/stream",
    "/source",
    "ananas",
]
LEARNING_PLATFORM_TOKENS = [
    "chaoxing",
    "xuexitong",
    "mooc1",
    "mooc2",
    "fanya",
    "ananas",
    "objectid",
    "dtoken",
]


def load_helpers():
    spec = importlib.util.spec_from_file_location("learnnote_e2e_helpers", HELPERS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load helper module: {HELPERS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = load_helpers()


def redact_url(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if text.startswith("blob:http://") or text.startswith("blob:https://"):
        return f"blob:{redact_url(text[5:])}"
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return text
    if parsed.scheme not in {"http", "https"}:
        return text
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = urllib.parse.urlencode([(key, "<redacted>") for key, _ in query])
    fragment = "<redacted>" if parsed.fragment else ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, fragment))


def compact_url(value: str, limit: int = 120) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    keep = max(20, (limit - 3) // 2)
    return f"{text[:keep]}...{text[-keep:]}"


def resource_haystack(resources: list[dict], *, limit: int = 30) -> str:
    return " ".join(
        str(value or "")
        for item in resources[:limit]
        for value in [
            item.get("url"),
            item.get("resolved_url"),
            item.get("frame_url"),
            item.get("label"),
            item.get("kind"),
            item.get("source"),
            item.get("request_type"),
            (item.get("request_body") or {}).get("content"),
        ]
    ).lower()


def resource_kind_counts(resources: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in resources:
        kind = str(item.get("kind") or "unknown").lower()
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def request_context_flags(resources: list[dict]) -> dict:
    header_names: set[str] = set()
    body_fields: set[str] = set()
    methods: set[str] = set()
    for item in resources:
        methods.add(str(item.get("method") or "GET").upper())
        headers = item.get("request_headers") or {}
        header_names.update(str(name).lower() for name in headers.keys())
        body = request_body_evidence(item.get("request_body") or {})
        body_fields.update(str(field).lower() for field in body.get("field_names") or [])
    return {
        "methods": sorted(methods),
        "has_referer": "referer" in header_names or "referrer" in header_names,
        "has_origin": "origin" in header_names,
        "has_x_requested_with": "x-requested-with" in header_names,
        "has_user_agent": "user-agent" in header_names,
        "has_request_body": any(bool((item.get("request_body") or {}).get("content")) for item in resources),
        "request_body_fields": sorted(body_fields)[:24],
    }


def preflight_report(preflight: dict | None) -> dict:
    if not preflight:
        return {}
    if isinstance(preflight.get("report"), dict):
        return preflight["report"]
    if isinstance(preflight.get("preflight"), dict):
        return preflight["preflight"]
    return preflight


def derive_failure_reason(profile: dict) -> str:
    if profile["readiness"] == "ready_to_download":
        return ""
    if profile["constraints"]["drm_detected"]:
        return "drm_or_encrypted"
    if profile["constraints"]["blob_or_mse"] and not profile["signals"]["direct_media"] and not profile["signals"]["playback_api"]:
        return "blob_without_manifest"
    if profile["learning_platform"]["detected"] and not profile["auth_context"]["cookie_count"]:
        return "auth_required"
    if not profile["signals"]["direct_media"] and not profile["signals"]["playback_api"]:
        return "no_media_found"
    if profile["preflight"]["ran"] and not profile["preflight"]["downloadable"]:
        return "download_forbidden"
    return "preflight_not_run"


def derive_next_step(profile: dict) -> str:
    reason = profile["failure_reason"]
    if profile["readiness"] == "ready_to_download":
        return "Start the current-page task; the browser has a downloadable candidate."
    if reason == "drm_or_encrypted":
        return "Use a non-DRM source or upload a local video; this tool does not bypass encrypted media."
    if reason == "blob_without_manifest":
        return "Keep the video playing and rerun detection; if no manifest/API appears, use local upload."
    if reason == "auth_required":
        return "Open the page with the logged-in D-drive audit profile, play the video, then rerun with -Preflight."
    if reason == "no_media_found":
        return "Play the target video for a few seconds, switch chapters if needed, then refresh detection."
    if reason == "download_forbidden":
        return "Inspect the top resource headers/body below; the server may require missing Referer/Origin/cookie or reject direct download."
    return "Rerun audit-real-site with -Preflight to test whether the captured candidate is actually downloadable."


def signal_profile(context: dict, preflight: dict | None = None) -> dict:
    resources = context.get("resources") or []
    page = context.get("page") or {}
    active = page.get("active_video") or {}
    haystack = resource_haystack(resources)
    kinds = resource_kind_counts(resources)
    request_flags = request_context_flags(resources)
    direct_media_count = sum(1 for item in resources if str(item.get("kind") or "").lower() in DIRECT_MEDIA_KINDS)
    manifest_count = sum(1 for item in resources if str(item.get("kind") or "").lower() in {"hls", "dash"})
    playback_api_count = sum(1 for item in resources if any(token in str(item.get("url") or "").lower() for token in PLAY_API_TOKENS))
    post_api_count = sum(1 for item in resources if str(item.get("method") or "").upper() == "POST")
    iframe_count = sum(1 for item in resources if item.get("frame_url"))
    blob_or_mse = (
        str(active.get("src") or "").startswith("blob:")
        or any(item.get("blob_url") or str(item.get("kind") or "").lower() in {"blob", "mediasource"} for item in resources)
    )
    report = preflight_report(preflight)
    preflight_ready = bool(report.get("ready") or report.get("downloadable") or report.get("downloadable_count"))
    platform = {
        "detected": any(token in haystack for token in LEARNING_PLATFORM_TOKENS),
        "ananas": "ananas" in haystack,
        "playurl": "playurl" in haystack or "play_url" in haystack,
        "objectid": "objectid" in haystack,
        "dtoken": "dtoken" in haystack,
        "iframe": iframe_count > 0,
        "cookie": int(context.get("cookie_count") or 0) > 0,
    }
    signals = {
        "direct_media": direct_media_count > 0,
        "manifest": manifest_count > 0,
        "playback_api": playback_api_count > 0,
        "post_api": post_api_count > 0,
        "request_body": bool(request_flags["has_request_body"]),
        "iframe": iframe_count > 0,
    }
    constraints = {
        "blob_or_mse": bool(blob_or_mse),
        "drm_detected": bool(page.get("drm_detected")),
    }
    preflight_state = {
        "ran": bool(preflight),
        "ready": preflight_ready,
        "downloadable": preflight_ready,
        "candidate_count": report.get("candidate_count"),
        "probed_count": report.get("probed_count"),
        "downloadable_count": report.get("downloadable_count"),
        "failure_reason": report.get("failure_reason") or report.get("reason"),
    }
    readiness = "ready_to_download" if preflight_ready else "needs_preflight" if (signals["direct_media"] or signals["playback_api"]) else "needs_playback"
    profile = {
        "readiness": readiness,
        "failure_reason": "",
        "next_step": "",
        "signals": signals,
        "counts": {
            "resources": len(resources),
            "captured_requests": int(context.get("captured_count") or 0),
            "direct_media": direct_media_count,
            "manifest": manifest_count,
            "playback_api": playback_api_count,
            "post_api": post_api_count,
            "iframe": iframe_count,
            "kinds": kinds,
        },
        "auth_context": {
            "cookie_count": int(context.get("cookie_count") or 0),
            "cookie_domain_count": int(context.get("cookie_domain_count") or 0),
            "cookie_domains": list(context.get("cookie_domains") or [])[:12],
        },
        "request_context": request_flags,
        "learning_platform": platform,
        "constraints": constraints,
        "preflight": preflight_state,
        "missing_steps": [],
    }
    if constraints["drm_detected"]:
        readiness = "blocked"
    elif preflight_ready:
        readiness = "ready_to_download"
    elif constraints["blob_or_mse"] and not signals["direct_media"] and not signals["playback_api"]:
        readiness = "blocked"
    elif platform["detected"] and not platform["cookie"]:
        readiness = "needs_auth_context"
    elif signals["direct_media"] or signals["playback_api"]:
        readiness = "needs_preflight" if not preflight else "candidate_not_downloadable"
    else:
        readiness = "needs_playback"
    profile["readiness"] = readiness

    missing: list[str] = []
    if not (signals["direct_media"] or signals["playback_api"] or constraints["blob_or_mse"]):
        missing.append("page_playback")
    if not (signals["direct_media"] or signals["playback_api"]):
        missing.append("media_candidate")
    if platform["detected"] and not platform["cookie"]:
        missing.append("auth_context")
    if signals["playback_api"] and not (signals["request_body"] or signals["direct_media"]):
        missing.append("request_replay")
    if not preflight:
        missing.append("download_preflight")
    elif not preflight_ready:
        missing.append("downloadable_candidate")
    profile["missing_steps"] = missing
    profile["failure_reason"] = derive_failure_reason(profile)
    profile["next_step"] = derive_next_step(profile)
    return profile


def request_body_evidence(body: dict | None) -> dict:
    body = body or {}
    content = str(body.get("content") or "")
    content_type = str(body.get("type") or "")
    keys: list[str] = []
    if content:
        if content_type == "json":
            try:
                payload = json.loads(content)
                if isinstance(payload, dict):
                    keys = sorted(str(key) for key in payload.keys())
            except json.JSONDecodeError:
                keys = []
        if not keys:
            keys = sorted({key for key, _ in urllib.parse.parse_qsl(content, keep_blank_values=True)})
    lower = content.lower()
    return {
        "present": bool(content),
        "type": content_type,
        "length": len(content),
        "field_names": keys[:20],
        "has_objectid": "objectid" in lower,
        "has_dtoken": "dtoken" in lower,
        "has_playurl": "playurl" in lower or "play_url" in lower,
    }


def safe_header_names(headers: dict | None) -> list[str]:
    return sorted(
        name for name in (headers or {}).keys()
        if "cookie" not in name.lower() and "authorization" not in name.lower()
    )


def sanitize_header_values(headers: dict | None) -> dict:
    clean = {}
    for name, value in (headers or {}).items():
        lower = str(name).lower()
        if "cookie" in lower or "authorization" in lower:
            continue
        if lower in {"referer", "referrer", "origin", "location"}:
            clean[name] = redact_url(str(value or ""))
        elif isinstance(value, str) and value.startswith(("http://", "https://", "blob:http://", "blob:https://")):
            clean[name] = redact_url(value)
        else:
            clean[name] = value
    return clean


def resource_summary(resources: list[dict], limit: int = 12) -> list[dict]:
    rows: list[dict] = []
    for item in resources[:limit]:
        body = item.get("request_body") or {}
        headers = item.get("request_headers") or {}
        rows.append({
            "kind": item.get("kind") or "",
            "source": item.get("source") or "",
            "method": item.get("method") or "GET",
            "request_type": item.get("request_type") or "",
            "has_body": bool(body.get("content")),
            "body": request_body_evidence(body),
            "frame_url": redact_url(item.get("frame_url") or ""),
            "safe_headers": safe_header_names(headers),
            "url": redact_url(item.get("url") or ""),
        })
    return rows


def sanitize_context(context: dict) -> dict:
    page = context.get("page") or {}
    active = page.get("active_video") or {}
    return {
        "tab": {
            "id": (context.get("tab") or {}).get("id"),
            "url": redact_url((context.get("tab") or {}).get("url") or ""),
            "title": (context.get("tab") or {}).get("title") or "",
            "status": (context.get("tab") or {}).get("status") or "",
        },
        "page": {
            "title": page.get("title") or "",
            "page_url": redact_url(page.get("page_url") or ""),
            "drm_detected": bool(page.get("drm_detected")),
            "browser_subtitle_count": page.get("browser_subtitle_count") or 0,
            "active_video": {
                **active,
                "src": redact_url(active.get("src") or ""),
                "frame_url": redact_url(active.get("frame_url") or ""),
            } if active else {},
        },
        "captured_count": int(context.get("captured_count") or 0),
        "cookie_count": int(context.get("cookie_count") or 0),
        "cookie_domain_count": int(context.get("cookie_domain_count") or 0),
        "cookie_domains": list(context.get("cookie_domains") or [])[:12],
        "resource_count": len(context.get("resources") or []),
        "resources": resource_summary(context.get("resources") or [], limit=30),
    }


def sanitize_json(value):
    if isinstance(value, dict):
        if "request_body" in value:
            value = {**value, "request_body": request_body_evidence(value.get("request_body"))}
        clean = {}
        for key, item in value.items():
            lower = str(key).lower()
            if lower in {"cookies", "cookie"}:
                clean[key] = f"{len(item) if isinstance(item, list) else 0} cookie(s) redacted"
            elif lower in {"headers", "request_headers", "response_headers"} and isinstance(item, dict):
                clean[key] = sanitize_header_values(item)
            elif lower in {"url", "resolved_url", "frame_url", "page_url", "blob_url", "audio_url", "final_url", "src"}:
                clean[key] = redact_url(str(item or ""))
            elif "authorization" in lower or lower == "cookie":
                clean[key] = "<redacted>"
            else:
                clean[key] = sanitize_json(item)
        return clean
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://", "blob:http://", "blob:https://")):
        return redact_url(value)
    return value


def evidence_model(context: dict, preflight: dict | None = None) -> dict:
    resources = context.get("resources") or []
    profile = signal_profile(context, preflight)
    page = context.get("page") or {}
    direct_media = profile["signals"]["direct_media"]
    replay_body = profile["signals"]["request_body"]
    blob = profile["constraints"]["blob_or_mse"]
    platform = profile["learning_platform"]
    has = {
        "direct_media": direct_media,
        "playback_api": profile["signals"]["playback_api"],
        "post_body": replay_body,
        "iframe": profile["signals"]["iframe"],
        "cookie": profile["auth_context"]["cookie_count"] > 0,
        "blob_or_mse": blob,
        "drm": bool(page.get("drm_detected")),
        "ananas": platform["ananas"],
        "playurl": platform["playurl"],
        "objectid": platform["objectid"],
        "dtoken": platform["dtoken"],
    }
    stages = [
        {
            "label": "browser_playback",
            "ok": direct_media or has["playback_api"] or blob,
            "detail": "media/API/blob evidence visible" if direct_media or has["playback_api"] or blob else "play the video for a few seconds and refresh detection",
        },
        {
            "label": "auth_context",
            "ok": has["cookie"] or not platform["detected"],
            "detail": f"{context.get('cookie_count', 0)} cookies visible across {profile['auth_context']['cookie_domain_count']} domain(s)" if has["cookie"] else "logged-in site likely needs cookies" if platform["detected"] else "no site-specific auth evidence required",
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
        "chaoxing_like": platform["detected"],
        "has": has,
        "stages": stages,
        "missing": missing,
        "profile": profile,
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
        profile = evidence.get("profile") or {}
        signals = profile.get("signals") or {}
        counts = profile.get("counts") or {}
        auth = profile.get("auth_context") or {}
        request_context = profile.get("request_context") or {}
        platform = profile.get("learning_platform") or {}
        constraints = profile.get("constraints") or {}
        preflight = audit.get("preflight")
        lines.extend([
            f"## {tab.get('title') or page.get('title') or audit['url']}",
            "",
            f"- URL: {redact_url(audit['url'])}",
            f"- Final tab URL: {tab.get('url') or '-'}",
            f"- Readiness: `{profile.get('readiness', 'unknown')}`",
            f"- Failure reason: `{profile.get('failure_reason') or '-'}`",
            f"- Next step: {profile.get('next_step') or '-'}",
            f"- Cookies visible: {context.get('cookie_count', 0)} across {auth.get('cookie_domain_count', 0)} domain(s)",
            f"- Captured requests: {context.get('captured_count', 0)}",
            f"- Ranked resources: {context.get('resource_count', len(context.get('resources') or []))}",
            "",
            "### Direct-download chain",
            "",
        ])
        for stage in evidence["stages"]:
            state = "PASS" if stage["ok"] else "WARN" if stage.get("warn") else "MISS"
            lines.append(f"- {state} `{stage['label']}`: {stage['detail']}")
        missing_steps = profile.get("missing_steps") or evidence["missing"]
        if missing_steps:
            lines.extend(["", f"Missing chain: {', '.join(missing_steps)}"])
        lines.extend([
            "",
            "### Signal profile",
            "",
            f"- Direct media: {'yes' if signals.get('direct_media') else 'no'} ({counts.get('direct_media', 0)})",
            f"- Manifest: {'yes' if signals.get('manifest') else 'no'} ({counts.get('manifest', 0)})",
            f"- Playback/API endpoint: {'yes' if signals.get('playback_api') else 'no'} ({counts.get('playback_api', 0)})",
            f"- POST API: {'yes' if signals.get('post_api') else 'no'} ({counts.get('post_api', 0)})",
            f"- Replay body captured: {'yes' if signals.get('request_body') else 'no'}",
            f"- Iframe context: {'yes' if signals.get('iframe') else 'no'} ({counts.get('iframe', 0)})",
            f"- Blob/MSE only signal: {'yes' if constraints.get('blob_or_mse') else 'no'}",
            f"- DRM detected: {'yes' if constraints.get('drm_detected') else 'no'}",
            f"- Request headers: Referer={'yes' if request_context.get('has_referer') else 'no'}, Origin={'yes' if request_context.get('has_origin') else 'no'}, XHR={'yes' if request_context.get('has_x_requested_with') else 'no'}",
        ])
        if request_context.get("request_body_fields"):
            lines.append(f"- Request body fields: {', '.join(request_context['request_body_fields'])}")
        if counts.get("kinds"):
            kinds = ", ".join(f"{key}:{value}" for key, value in counts["kinds"].items())
            lines.append(f"- Resource kinds: {kinds}")
        if auth.get("cookie_domains"):
            lines.append(f"- Cookie domains: {', '.join(auth['cookie_domains'])}")
        lines.extend([
            "",
            "### Learning-platform profile",
            "",
            f"- Detected: {'yes' if platform.get('detected') else 'no'}",
            f"- ananas: {'yes' if platform.get('ananas') else 'no'}",
            f"- playurl/play_url: {'yes' if platform.get('playurl') else 'no'}",
            f"- objectid: {'yes' if platform.get('objectid') else 'no'}",
            f"- dtoken: {'yes' if platform.get('dtoken') else 'no'}",
            f"- iframe: {'yes' if platform.get('iframe') else 'no'}",
            f"- cookie: {'yes' if platform.get('cookie') else 'no'}",
            "",
            "### Active video",
            "",
            f"`{json.dumps(page.get('active_video') or {}, ensure_ascii=False)[:500]}`",
        ])
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
    profile_root = ROOT / "data" / "browser-profiles" / "site-audits"
    profile_root.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile_dir).resolve() if args.profile_dir else Path(tempfile.mkdtemp(prefix="learnnote-site-audit-", dir=str(profile_root)))
    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"Browser profile: {profile_dir}")

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
            safe_context = sanitize_context(context)
            safe_preflight = sanitize_json(preflight_payload) if preflight_payload else None
            audits.append({
                "url": redact_url(url),
                "context": safe_context,
                "preflight": safe_preflight,
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
