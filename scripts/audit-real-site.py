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
LEARNING_PROFILE_SIGNALS = {"ananas", "playurl", "objectid", "dtoken", "iframe", "cookie"}
DEFAULT_LEARNING_REQUIRED_SIGNALS = "ananas,playurl,objectid,dtoken,iframe,cookie"


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


def task_probe_report(task_probe: dict | None) -> dict:
    if not task_probe:
        return {}
    task = task_probe.get("task") if isinstance(task_probe.get("task"), dict) else task_probe
    attempts = task.get("download_attempts") or []
    strategies = [str(item.get("strategy") or "") for item in attempts if isinstance(item, dict) and item.get("strategy")]
    return {
        "ran": True,
        "ready": bool(task_probe.get("ready") or (task.get("status") == "success" and task.get("media_path"))),
        "task_id": task.get("id") or task_probe.get("task_id") or "",
        "status": task.get("status") or task_probe.get("status") or "",
        "phase": task.get("phase") or "",
        "mode": task.get("mode") or "",
        "source_type": task.get("source_type") or "",
        "media_path_present": bool(task.get("media_path")),
        "error_code": task.get("error_code") or task_probe.get("error_code") or "",
        "error_detail": task.get("error_detail") or task_probe.get("error_detail") or "",
        "download_strategies": strategies,
    }


def derive_failure_reason(profile: dict) -> str:
    if profile["readiness"] == "ready_to_download":
        return ""
    task_probe = profile.get("task_probe") or {}
    if task_probe.get("ran") and not task_probe.get("ready") and task_probe.get("error_code"):
        return str(task_probe.get("error_code"))
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
    if reason == "task_probe_timeout":
        return "The real download-only task did not finish in time; inspect the task diagnostics or rerun with a longer --TaskTimeout."
    if reason == "task_create_failed":
        return "The extension could not create the backend task; confirm the local backend and extension are both reachable."
    return "Rerun audit-real-site with -Preflight to test whether the captured candidate is actually downloadable."


def ytdlp_probe_report(probe: dict | None) -> dict:
    if not probe:
        return {}
    return {
        "ran": True,
        "ready": bool(probe.get("ready")),
        "extractor": str(probe.get("extractor") or ""),
        "title": str(probe.get("title") or ""),
        "id": str(probe.get("id") or ""),
        "webpage_url": str(probe.get("webpage_url") or ""),
        "error_code": str(probe.get("error_code") or ""),
        "error_detail": str(probe.get("error_detail") or ""),
    }


def signal_profile(
    context: dict,
    preflight: dict | None = None,
    task_probe: dict | None = None,
    ytdlp_probe: dict | None = None,
) -> dict:
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
    task_report = task_probe_report(task_probe)
    ytdlp_report = ytdlp_probe_report(ytdlp_probe)
    preflight_ready = bool(report.get("ready") or report.get("downloadable") or report.get("downloadable_count"))
    task_ready = bool(task_report.get("ready"))
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
        "task_probe": task_report,
        "ytdlp_probe": ytdlp_report,
        "missing_steps": [],
    }
    if task_ready:
        readiness = "ready_to_download"
    elif task_report.get("ran"):
        readiness = "task_probe_failed"
    elif constraints["drm_detected"]:
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
    if task_ready:
        pass
    elif task_report.get("ran"):
        missing.append("download_task_probe")
    elif not preflight:
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
    payload = {
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
    if context.get("collection_error"):
        payload["collection_error"] = str(context.get("collection_error"))[:500]
    return payload


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


def evidence_model(
    context: dict,
    preflight: dict | None = None,
    task_probe: dict | None = None,
    ytdlp_probe: dict | None = None,
) -> dict:
    resources = context.get("resources") or []
    profile = signal_profile(context, preflight, task_probe, ytdlp_probe)
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
            "label": "download_task_probe",
            "ok": bool(profile.get("task_probe", {}).get("ready")),
            "warn": not bool(profile.get("task_probe", {}).get("ran")),
            "detail": "download-only task saved media locally" if profile.get("task_probe", {}).get("ready") else "not run" if not profile.get("task_probe", {}).get("ran") else "download-only task did not save media",
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


def parse_learning_required_signals(value: str) -> list[str]:
    signals = [item.strip().lower() for item in str(value or "").split(",") if item.strip()]
    unknown = sorted(set(signals) - LEARNING_PROFILE_SIGNALS)
    if unknown:
        raise ValueError(f"Unknown learning profile signal(s): {', '.join(unknown)}")
    return signals


def audit_gate_failures(
    audits: list[dict],
    *,
    require_ready: bool = False,
    learning_required_signals: list[str] | None = None,
) -> list[dict]:
    failures: list[dict] = []
    for audit in audits:
        profile = ((audit.get("evidence") or {}).get("profile") or {})
        platform = profile.get("learning_platform") or {}
        url = audit.get("url") or ""
        if require_ready and profile.get("readiness") != "ready_to_download":
            failures.append({
                "url": url,
                "gate": "require_ready",
                "readiness": profile.get("readiness") or "unknown",
                "failure_reason": profile.get("failure_reason") or "unknown",
                "missing_steps": profile.get("missing_steps") or [],
                "next_step": profile.get("next_step") or "",
            })
        if learning_required_signals is not None:
            missing = []
            if not platform.get("detected"):
                missing.append("learning_platform_detected")
            missing.extend(signal for signal in learning_required_signals if not platform.get(signal))
            if missing:
                failures.append({
                    "url": url,
                    "gate": "require_learning_profile",
                    "missing_signals": missing,
                    "readiness": profile.get("readiness") or "unknown",
                    "failure_reason": profile.get("failure_reason") or "unknown",
                    "next_step": profile.get("next_step") or "",
                })
    return failures


def markdown_report(audits: list[dict], backend: str, gate_failures: list[dict] | None = None) -> str:
    lines = [
        "# LearnNote real-site browser audit",
        "",
        f"- Time: {datetime.now().isoformat(timespec='seconds')}",
        f"- Backend: {backend}",
        "- Boundary: no tab recording, no DRM bypass, no progress spoofing, no auto-answering.",
        "",
    ]
    if gate_failures:
        lines.extend([
            "## Gate failures",
            "",
        ])
        for failure in gate_failures:
            if failure["gate"] == "require_ready":
                lines.append(
                    f"- `{failure['gate']}` {redact_url(failure['url'])}: readiness={failure['readiness']}, "
                    f"reason={failure['failure_reason']}, missing={', '.join(failure.get('missing_steps') or []) or '-'}"
                )
            else:
                lines.append(
                    f"- `{failure['gate']}` {redact_url(failure['url'])}: "
                    f"missing={', '.join(failure.get('missing_signals') or []) or '-'}"
                )
        lines.append("")
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
        task_probe = profile.get("task_probe") or {}
        ytdlp_probe = profile.get("ytdlp_probe") or {}
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
            f"- Download task probe: {'ready' if task_probe.get('ready') else 'not ready' if task_probe.get('ran') else 'not run'}",
            f"- yt-dlp probe: {'ready' if ytdlp_probe.get('ready') else 'not ready' if ytdlp_probe.get('ran') else 'not run'}",
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
        if task_probe.get("ran"):
            lines.extend([
                "",
                "### Download task probe",
                "",
                f"- Ready: {task_probe.get('ready')}",
                f"- Task: {task_probe.get('task_id') or '-'}",
                f"- Status: {task_probe.get('status') or '-'} / {task_probe.get('phase') or '-'}",
                f"- Mode/source: {task_probe.get('mode') or '-'} / {task_probe.get('source_type') or '-'}",
                f"- Media saved: {task_probe.get('media_path_present')}",
                f"- Download strategies: {', '.join(task_probe.get('download_strategies') or []) or '-'}",
                f"- Error: {task_probe.get('error_code') or '-'} {task_probe.get('error_detail') or ''}".rstrip(),
            ])
        if ytdlp_probe.get("ran"):
            lines.extend([
                "",
                "### yt-dlp probe",
                "",
                f"- Ready: {ytdlp_probe.get('ready')}",
                f"- Extractor: {ytdlp_probe.get('extractor') or '-'}",
                f"- ID: {ytdlp_probe.get('id') or '-'}",
                f"- Title: {ytdlp_probe.get('title') or '-'}",
                f"- Webpage URL: {redact_url(ytdlp_probe.get('webpage_url') or '') or '-'}",
                f"- Error: {ytdlp_probe.get('error_code') or '-'} {ytdlp_probe.get('error_detail') or ''}".rstrip(),
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


def collect_minimal_context(cdp, tab_id: int, collection_error: str = "") -> dict:
    expression = f"""
async () => {{
  const tab = await chrome.tabs.get({int(tab_id)});
  return {{
    tab: {{ id: tab.id, url: tab.url || "", title: tab.title || "", status: tab.status || "" }},
    page: {{
      title: tab.title || "",
      page_url: tab.url || "",
      drm_detected: false,
      browser_subtitle_count: 0,
      active_video: {{}}
    }},
    resources: [],
    captured_count: 0,
    cookie_count: 0,
    cookie_domain_count: 0,
    cookie_domains: [],
    collection_error: {json.dumps(collection_error[:500])}
  }};
}}
"""
    return helpers.eval_service_worker(cdp, expression, timeout=30)


def start_download_task_probe(cdp, backend: str, tab_id: int, resources: list[dict], timeout_seconds: float, *, minimal: bool = False) -> dict:
    if minimal:
        expression = f"""
async () => {{
  const tab = await chrome.tabs.get({int(tab_id)});
  const cookies = await chrome.cookies.getAll({{ url: tab.url || "" }}).catch(() => []);
  const res = await fetch({json.dumps(f"{backend}/api/tasks/from-current-page")}, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{
      mode: "download_only",
      page_url: tab.url || "",
      title: tab.title || tab.url || "",
      page_text: "",
      active_video: null,
      browser_subtitles: [],
      drm_detected: false,
      drm_signals: [],
      resources: [],
      cookies,
      options: {{
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
    }})
  }});
  return await res.json();
}}
"""
        payload = helpers.eval_service_worker(cdp, expression, timeout=30)
    else:
        expression = f"""
async () => {{
  return await globalThis.__learnnoteE2E.startCurrentPageTaskForTab(
    {int(tab_id)},
    {json.dumps(backend)},
    {json.dumps(resources[:20])},
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
}}
"""
        payload = helpers.eval_service_worker(cdp, expression)
    if payload.get("error") or not payload.get("task_id"):
        return {"ready": False, "error_code": "task_create_failed", "error_detail": payload.get("error") or json.dumps(payload, ensure_ascii=False)}
    deadline = time.time() + max(1, timeout_seconds)
    latest: dict = {}
    last_error = ""
    while time.time() < deadline:
        try:
            latest = helpers.request_json("GET", f"{backend}/api/tasks/{payload['task_id']}", timeout=8)
        except Exception as exc:  # noqa: BLE001 - live-site downloads can temporarily occupy the backend
            last_error = str(exc)
            time.sleep(1.0)
            continue
        task = latest.get("task", latest)
        if task.get("status") in {"success", "failed"}:
            return {"ready": bool(task.get("status") == "success" and task.get("media_path")), "task": task}
        time.sleep(0.8)
    return {
        "ready": False,
        "task_id": payload.get("task_id"),
        "status": "timeout",
        "error_code": "task_probe_timeout",
        "error_detail": f"Timed out after {timeout_seconds:.0f}s waiting for download-only task.{f' Last poll error: {last_error}' if last_error else ''}",
        "task": latest.get("task", latest) if isinstance(latest, dict) else {},
    }


def run_ytdlp_metadata_probe(url: str, timeout_seconds: float = 45) -> dict:
    cmd = [
        helpers.project_python(),
        "-m",
        "yt_dlp",
        "--simulate",
        "--skip-download",
        "--no-warnings",
        "--no-progress",
        "--print",
        "%(extractor)s\t%(id)s\t%(title)s\t%(webpage_url)s",
        url,
    ]
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stderr or exc.stdout or "").strip()
        return {
            "ready": False,
            "error_code": "yt_dlp_timeout",
            "error_detail": output[:500] or f"yt-dlp metadata probe timed out after {timeout_seconds:.0f}s",
        }
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        return {
            "ready": False,
            "error_code": "yt_dlp_probe_failed",
            "error_detail": (error or output)[:500],
        }
    first = next((line for line in output.splitlines() if line.strip()), "")
    parts = first.split("\t", 3)
    while len(parts) < 4:
        parts.append("")
    return {
        "ready": True,
        "extractor": parts[0],
        "id": parts[1],
        "title": parts[2],
        "webpage_url": parts[3],
    }


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
    parser.add_argument("--task-probe", action="store_true", help="Create a real download-only current-page task and wait for local media output.")
    parser.add_argument("--task-probe-page-only", action="store_true", help="Create the download-only task with page URL, cookies, and no captured resources to test backend page fallback.")
    parser.add_argument("--ytdlp-probe", action="store_true", help="Run a metadata-only yt-dlp probe and record extractor evidence in the audit report.")
    parser.add_argument("--task-timeout", type=float, default=90, help="Seconds to wait for --task-probe.")
    parser.add_argument("--keep-browser", action="store_true")
    parser.add_argument("--require-ready", action="store_true", help="Exit non-zero unless every audited URL is ready_to_download.")
    parser.add_argument(
        "--require-learning-profile",
        action="store_true",
        help="Exit non-zero unless every audited URL has the required learning-platform evidence signals.",
    )
    parser.add_argument(
        "--learning-required-signals",
        default=DEFAULT_LEARNING_REQUIRED_SIGNALS,
        help=f"Comma-separated learning-platform signals to require. Allowed: {', '.join(sorted(LEARNING_PROFILE_SIGNALS))}.",
    )
    args = parser.parse_args()
    try:
        learning_required_signals = parse_learning_required_signals(args.learning_required_signals)
    except ValueError as exc:
        parser.error(str(exc))

    browser = helpers.browser_path(args.browser)
    if not browser:
        raise RuntimeError(f"{args.browser} executable not found. Set LEARNNOTE_E2E_BROWSER.")
    debug_port = args.debug_port if args.debug_port > 0 else helpers.free_port()
    if helpers.port_is_open(debug_port):
        raise RuntimeError(f"Debug port {debug_port} is already in use.")

    if args.backend_port <= 0:
        args.backend_port = helpers.free_port()
    elif helpers.port_is_open(args.backend_port):
        replacement = helpers.free_port()
        print(f"INFO backend port {args.backend_port} is busy; using {replacement} for this audit run.")
        args.backend_port = replacement
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
            minimal_context = False
            try:
                context = helpers.collect_extension_context(cdp, url, tab_ids[url], wait_ms=args.wait_ms)
            except Exception as exc:
                if not args.task_probe:
                    raise
                minimal_context = True
                context = collect_minimal_context(cdp, tab_ids[url], str(exc))
            preflight_payload = None
            if args.preflight and not minimal_context:
                preflight_payload = preflight_current_page(cdp, backend, tab_ids[url], context.get("resources") or [], args.probe_limit)
            task_probe_payload = None
            if args.task_probe:
                task_probe_payload = start_download_task_probe(
                    cdp,
                    backend,
                    tab_ids[url],
                    context.get("resources") or [],
                    args.task_timeout,
                    minimal=minimal_context or args.task_probe_page_only,
                )
            ytdlp_probe_payload = run_ytdlp_metadata_probe(url) if args.ytdlp_probe else None
            evidence = evidence_model(
                context,
                preflight_payload.get("report") if preflight_payload else None,
                task_probe_payload,
                ytdlp_probe_payload,
            )
            safe_context = sanitize_context(context)
            safe_preflight = sanitize_json(preflight_payload) if preflight_payload else None
            safe_task_probe = sanitize_json(task_probe_payload) if task_probe_payload else None
            safe_ytdlp_probe = sanitize_json(ytdlp_probe_payload) if ytdlp_probe_payload else None
            audits.append({
                "url": redact_url(url),
                "context": safe_context,
                "preflight": safe_preflight,
                "task_probe": safe_task_probe,
                "ytdlp_probe": safe_ytdlp_probe,
                "evidence": evidence,
            })
            profile = evidence.get("profile") or {}
            missing = profile.get("missing_steps") or evidence["missing"]
            print(
                f"AUDIT {url}: readiness={profile.get('readiness', 'unknown')} "
                f"reason={profile.get('failure_reason') or '-'} "
                f"resources={len(context.get('resources') or [])} "
                f"cookies={context.get('cookie_count', 0)} missing={','.join(missing) or '-'}"
            )

        gate_failures = audit_gate_failures(
            audits,
            require_ready=args.require_ready,
            learning_required_signals=learning_required_signals if args.require_learning_profile else None,
        )
        (out_dir / "audit.json").write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "audit.md").write_text(markdown_report(audits, backend, gate_failures), encoding="utf-8")
        if gate_failures:
            (out_dir / "gate-failures.json").write_text(json.dumps(gate_failures, ensure_ascii=False, indent=2), encoding="utf-8")
            for failure in gate_failures:
                if failure["gate"] == "require_ready":
                    print(
                        f"GATE FAIL require_ready {failure['url']}: "
                        f"readiness={failure['readiness']} reason={failure['failure_reason']}"
                    )
                else:
                    print(
                        f"GATE FAIL require_learning_profile {failure['url']}: "
                        f"missing={','.join(failure.get('missing_signals') or []) or '-'}"
                    )
        print(f"Report: {out_dir / 'audit.md'}")
        if gate_failures:
            raise SystemExit(3)
    finally:
        if cdp:
            cdp.close()
        if not args.keep_browser:
            helpers.stop_process(browser_process)
        helpers.stop_process(backend_process)


if __name__ == "__main__":
    main()
