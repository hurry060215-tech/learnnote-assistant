"""Pure recovery guidance: TaskRecord + explicit artifact/media evidence -> JSON.

No I/O or mutation: API adapters supply artifacts; outputs retain the wire schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from .models import TaskRecord


@dataclass(frozen=True)
class RecoveryEvidence:
    inventory: dict = field(default_factory=dict)
    preflight: dict = field(default_factory=dict)
    media_exists: bool = False
    media_name: str = "本地媒体"
    mse_boundary_summary: str = ""


def _safe_header_names(values: dict[str, str]) -> str:
    names = sorted(name for name in values if "cookie" not in name.lower() and "authorization" not in name.lower())
    return ", ".join(names) or "-"


def _has_range_header(values: dict[str, str]) -> bool:
    return any(name.lower() == "range" for name in values)


def _safe_request_header_names(names) -> list[str]:
    return [
        name
        for name in sorted(str(name) for name in names if str(name or "").strip())
        if not re.search(r"cookie|authorization", name, re.I)
    ]


def _is_chaoxing_task(task: TaskRecord) -> bool:
    values = [
        task.page_url,
        task.title,
        task.error_detail,
        task.selected_resource.url if task.selected_resource else "",
        task.selected_resource.resolved_url if task.selected_resource else "",
        task.selected_resource.initiator if task.selected_resource else "",
        task.selected_resource.label if task.selected_resource else "",
    ]
    for attempt in task.download_attempts:
        values.extend([attempt.url, attempt.resolved_url, attempt.source, attempt.message])
    text = " ".join(str(value or "").lower() for value in values)
    return bool(re.search(r"chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|学习通|超星", text, re.I))


def _string_contains_chaoxing_signal(value: object) -> bool:
    return bool(re.search(r"chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|objectid|dtoken|httpmd", str(value or ""), re.I))


def _candidate_entries_for_site_profile(task: TaskRecord, evidence: RecoveryEvidence) -> list[dict]:
    entries: list[dict] = []

    def add(value: object, source: str) -> None:
        if not value:
            return
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="json")
        elif isinstance(value, dict):
            payload = dict(value)
        else:
            return
        payload["_profile_source"] = source
        entries.append(payload)

    add(task.selected_resource, "selected_resource")
    for attempt in task.download_attempts or []:
        add(attempt, "download_attempt")

    inventory = evidence.inventory
    for candidate in inventory.get("candidates") or []:
        add(candidate, "resource_inventory")

    page_preflight = evidence.preflight
    for item in page_preflight.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        resource = item.get("resource") or {}
        if isinstance(resource, dict):
            payload = dict(resource)
            preflight = item.get("preflight") or {}
            payload["_profile_source"] = "page_preflight"
            payload["_preflight_rank"] = item.get("rank")
            payload["_preflight_code"] = preflight.get("code") if isinstance(preflight, dict) else ""
            payload["_preflight_strategy"] = preflight.get("strategy") if isinstance(preflight, dict) else ""
            entries.append(payload)

    return entries


def chaoxing_evidence_profile(task: TaskRecord, evidence: RecoveryEvidence) -> dict:
    entries = _candidate_entries_for_site_profile(task, evidence)
    page_preflight = evidence.preflight
    cookie_summary = task.cookie_summary or {}
    text_parts = [
        task.page_url,
        task.title,
        task.error_detail,
        json.dumps(page_preflight, ensure_ascii=False) if page_preflight else "",
        json.dumps(cookie_summary, ensure_ascii=False) if cookie_summary else "",
    ]
    text_parts.extend(json.dumps(entry, ensure_ascii=False) for entry in entries)
    all_text = " ".join(text_parts).lower()
    detected = _is_chaoxing_task(task) or _string_contains_chaoxing_signal(all_text)

    safe_header_names: set[str] = set()
    all_header_names: set[str] = set()
    candidate_sources: set[str] = set()
    candidate_kinds: set[str] = set()
    ananas_candidate_count = 0
    replay_body_count = 0
    iframe_context_count = 0

    for entry in entries:
        url_text = " ".join(str(entry.get(key) or "") for key in ("url", "resolved_url", "frame_url", "page_url", "initiator", "label"))
        if re.search(r"ananas|objectid|dtoken|httpmd", url_text, re.I):
            ananas_candidate_count += 1
        if entry.get("request_body"):
            replay_body_count += 1
        if entry.get("frame_url") or entry.get("frame_id") is not None or entry.get("initiator"):
            iframe_context_count += 1
        source = str(entry.get("source") or entry.get("strategy") or entry.get("_profile_source") or "")
        kind = str(entry.get("kind") or "")
        if source:
            candidate_sources.add(source)
        if kind:
            candidate_kinds.add(kind)
        request_headers = entry.get("request_headers") or {}
        if isinstance(request_headers, dict):
            all_header_names.update(str(name) for name in request_headers)
            safe_header_names.update(_safe_request_header_names(request_headers.keys()))
        request_header_names = entry.get("request_header_names") or []
        if isinstance(request_header_names, list):
            all_header_names.update(str(name) for name in request_header_names)
            safe_header_names.update(_safe_request_header_names(request_header_names))

    lower_header_names = {name.lower() for name in all_header_names}
    page_scan = page_preflight.get("page_scan") if isinstance(page_preflight, dict) else {}
    if not isinstance(page_scan, dict):
        page_scan = {}

    issue = "no_chaoxing_signal"
    codes = _task_failure_codes(task)
    if detected:
        if not ananas_candidate_count and not page_preflight:
            issue = "playback_api_not_observed"
        elif not cookie_summary.get("total"):
            issue = "login_cookie_not_synced"
        elif "download_forbidden" in codes:
            issue = "anti_hotlink_or_expired_signature"
        elif "auth_required" in codes:
            issue = "auth_required"
        elif task.error_code:
            issue = task.error_code
        else:
            issue = "evidence_ready"

    return {
        "detected": bool(detected),
        "candidate_count": len(entries),
        "ananas_candidate_count": ananas_candidate_count,
        "has_ananas_candidate": ananas_candidate_count > 0,
        "has_playurl": bool(re.search(r"play_?url|playURL", all_text, re.I)),
        "has_objectid": "objectid" in all_text,
        "has_dtoken": "dtoken" in all_text,
        "has_httpmd": "httpmd" in all_text,
        "has_replay_body": replay_body_count > 0,
        "replay_body_count": replay_body_count,
        "has_referer": "referer" in lower_header_names,
        "has_origin": "origin" in lower_header_names,
        "has_x_requested_with": "x-requested-with" in lower_header_names,
        "has_iframe_context": iframe_context_count > 0,
        "iframe_context_count": iframe_context_count,
        "cookie_count": int(cookie_summary.get("total") or 0),
        "cookie_domain_count": int(cookie_summary.get("domain_count") or 0),
        "partitioned_cookie_count": int(cookie_summary.get("partitioned_count") or 0),
        "partition_key_count": int(cookie_summary.get("partition_key_count") or 0),
        "has_partitioned_cookies": int(cookie_summary.get("partitioned_count") or 0) > 0,
        "safe_request_header_names": sorted(safe_header_names),
        "candidate_sources": sorted(candidate_sources),
        "candidate_kinds": sorted(candidate_kinds),
        "page_preflight": {
            "present": bool(page_preflight),
            "ready": bool(page_preflight.get("ready")) if isinstance(page_preflight, dict) else False,
            "candidate_count": int(page_preflight.get("candidate_count") or 0) if isinstance(page_preflight, dict) else 0,
            "probed_count": int(page_preflight.get("probed_count") or 0) if isinstance(page_preflight, dict) else 0,
            "downloadable_count": int(page_preflight.get("downloadable_count") or 0) if isinstance(page_preflight, dict) else 0,
            "page_scan_attempted": bool(page_scan.get("attempted")),
            "page_scan_discovered_count": int(page_scan.get("discovered_count") or 0),
        },
        "likely_issue": issue,
        "boundary": "no_recording_no_progress_forgery",
    }


def _task_failure_codes(task: TaskRecord) -> set[str]:
    codes = {task.error_code} if task.error_code else set()
    codes.update(attempt.code for attempt in task.download_attempts if attempt.code)
    return codes


def diagnostic_recovery_steps(task: TaskRecord, evidence: RecoveryEvidence) -> list[str]:
    codes = _task_failure_codes(task)
    steps: list[str] = []

    def add(text: str) -> None:
        if text and text not in steps:
            steps.append(text)

    if _is_chaoxing_task(task):
        add("检测到学习通/超星页面线索：请先在原课程页真实播放几秒，让 ananas/播放接口暴露 m3u8、mp4 或带 Referer 的媒体请求；本工具只复用你当前登录态可访问的资源，不刷课、不伪造进度、不自动答题。")
    if "drm_or_encrypted" in codes or task.drm_detected:
        add("页面触发 DRM/EME 或只暴露不可还原 blob 时，本工具不会录制、破解或绕过 DRM；请改用本地视频入口。")
    mse_boundary_summary = evidence.mse_boundary_summary
    if mse_boundary_summary:
        add(f"{mse_boundary_summary} 请继续播放几秒并重新检测真实 manifest/mp4 请求；如果仍只有 blob/MSE 证据，就使用本地视频入口。")
    if "auth_required" in codes:
        add("重新打开课程页面并确认登录有效，播放几秒后立刻从扩展侧栏重新创建任务，让 Cookie 和媒体请求保持新鲜。")
    if "network_tls_error" in codes:
        add("视频服务器的 TLS 连接被提前断开；后端已自动重试。请稍后重试一次，并检查代理、网络过滤或安全软件是否中断大文件 HTTPS 连接。")
    if "download_forbidden" in codes:
        add("媒体服务器拒绝下载时，优先检查 Referer/Origin、登录态和时效签名；回到原页面继续播放后重新检测，或选择另一个候选资源。")
    if "unsupported_manifest" in codes:
        add("如果只有分片或无法合并的 manifest，继续播放后重新检测，优先选择完整 mp4/FLV/m3u8/mpd 候选。")
    if "no_media_found" in codes or (task.status == "failed" and not task.download_attempts):
        add("当前页没有暴露可直取媒体时，先让视频实际播放几秒再重检；仍失败就使用本地视频上传。")
    if task.selected_resource and task.selected_resource.request_headers:
        add(f"已捕获可复用请求头名：{_safe_header_names(task.selected_resource.request_headers)}；诊断中不会保存 Cookie 或 Authorization 值。")
    if task.selected_resource and _has_range_header(task.selected_resource.request_headers):
        add("Range 只作为浏览器播放证据；正式下载会去掉播放 Range，避免只保存一个视频片段。")
    if len(task.download_attempts) > 1:
        add(f"后端已尝试 {len(task.download_attempts)} 条路线；查看上方下载尝试，优先处理第一个失败的直接媒体候选。")
    if task.status == "failed" and task.note_path:
        add("视频直取失败但已有兜底笔记时，可先导出 Markdown/资料包复习，再根据诊断重新尝试直取。")
    if not steps:
        add("如果任务未完成，先查看下载尝试的错误码；当前页直取失败时可以改用本地视频入口走同一套切片总结。")
    return steps


# Shared action specifications avoid rebuilding every label for each action.
_ACTION_SPECS = {
    'local_upload': ('上传本地视频', 'local_upload',
        '改用本地文件，继续走同一套转写、切片、视觉窗口和总结管线。'),
    'refresh_login_and_retry': ('重新登录后重检', 'retry_current_page',
        '回到原课程页确认登录有效，播放几秒后从扩展重新检测并创建任务。'),
    'refresh_playback_and_retry': ('继续播放后重检', 'retry_current_page',
        '回到原页面继续播放，让 Referer、Cookie 和时效签名保持新鲜后重试。'),
    'play_longer_and_redetect': ('播放更久后重检', 'retry_current_page',
        '让播放器继续加载完整 manifest，再从扩展重新检测候选资源。'),
    'play_and_redetect': ('播放几秒后重检', 'retry_current_page',
        '先让视频真实播放，等待 mp4、m3u8、mpd 或播放接口请求暴露。'),
    'inspect_diagnostics': ('查看下载诊断', 'inspect_diagnostics',
        '查看每条下载路线的 URL、状态码、错误码和请求头证据。'),
    'continue_from_media': ('继续切片总结', 'continue_from_media',
        '复用已下载到本地的 {media_name}，继续生成字幕、画面网格和笔记。'),
    'inspect_audit': ('查看阶段审计', 'inspect_audit',
        '检查媒体、转写、切片、总结各阶段产物是否齐全。'),
    'export_markdown': ('导出 Markdown', 'export_markdown',
        '先导出现有笔记复习，再按诊断重新尝试直取。'),
    'export_diagnostics': ('导出诊断', 'export_diagnostics',
        '导出诊断文件，便于复现登录态、签名或 manifest 问题。'),
    'export_audit': ('导出审计', 'export_audit',
        '导出阶段门报告，确认失败发生在哪个处理阶段。'),
}


def _recovery_action(action: str, *, detail: str = "", priority: str = "secondary", media_name: str = "本地媒体") -> dict[str, str]:
    label, intent, description = _ACTION_SPECS.get(action, _ACTION_SPECS["inspect_diagnostics"])
    if action == "continue_from_media":
        description = description.format(media_name=media_name)
    return {"label": label, "ui_intent": intent, "detail": detail or description,
            "key": action, "priority": priority}


def _diagnostic_recovery_actions(task: TaskRecord, primary_action_key: str, evidence: RecoveryEvidence) -> list[dict[str, str]]:
    actions = [_recovery_action(primary_action_key, priority="primary", media_name=evidence.media_name)]
    existing = {primary_action_key}
    codes = _task_failure_codes(task)

    def add(action_key: str) -> None:
        if action_key not in existing:
            actions.append(_recovery_action(action_key, media_name=evidence.media_name))
            existing.add(action_key)

    if (task.status in {"success", "failed"} and evidence.media_exists):
        add("continue_from_media")
    if primary_action_key == "export_markdown":
        if "auth_required" in codes:
            add("refresh_login_and_retry")
        elif "unsupported_manifest" in codes:
            add("play_longer_and_redetect")
        elif "no_media_found" in codes:
            add("play_and_redetect")
        else:
            add("refresh_playback_and_retry")
    if primary_action_key != "local_upload":
        add("local_upload")
    add("inspect_diagnostics")
    if task.note_path:
        add("export_markdown")
    add("export_audit")
    if task.summary_diagnostics_path or task.download_attempts or task.selected_resource or task.error_code:
        add("export_diagnostics")
    return actions


def diagnostic_recovery_profile(task: TaskRecord, evidence: RecoveryEvidence) -> dict:
    codes = _task_failure_codes(task)
    selected = task.selected_resource
    selected_kind = selected.kind if selected else ""
    selected_source = selected.source if selected else ""
    selected_url = selected.resolved_url or selected.url if selected else ""
    latest_attempt = task.download_attempts[-1] if task.download_attempts else None
    chaoxing_profile = chaoxing_evidence_profile(task, evidence)
    is_chaoxing = bool(chaoxing_profile.get("detected"))
    boundary_notes: list[str] = []
    primary_code = task.error_code or (latest_attempt.code if latest_attempt else "")
    media_ready_for_rerun = (task.status in {"success", "failed"} and not task.note_path and evidence.media_exists)
    mse_boundary_summary = evidence.mse_boundary_summary

    if task.mode == "download_only" and evidence.media_exists:
        primary_code = "download_ready"
        diagnosis = f"{evidence.media_name} 已按只下载模式保存到本地；下一步可复用该视频生成字幕、画面网格和图文笔记。"
        confidence = "high"
        severity = "ok"
        next_action = "continue_from_media"
    elif media_ready_for_rerun:
        primary_code = "media_ready_for_rerun"
        diagnosis = f"视频已保存到本地，但完整笔记尚未生成；优先复用 {evidence.media_name} 继续转写、切片和图文总结。"
        confidence = "high"
        severity = "recoverable" if task.status == "failed" else "ok"
        next_action = "continue_from_media"
    elif task.status == "failed" and task.note_path and task.summary_diagnostics.get("used_page_text_fallback"):
        primary_code = "fallback_note_ready"
        diagnosis = "视频直取失败，但已用页面文本和浏览器字幕生成兜底学习笔记；可以先导出 Markdown 复习，再按诊断重新尝试直取或改用本地视频。"
        confidence = "high"
        severity = "partial"
        next_action = "export_markdown"
    elif "drm_or_encrypted" in codes or task.drm_detected:
        primary_code = "drm_or_encrypted"
        diagnosis = (
            f"{mse_boundary_summary} 需要继续播放并重新检测真实 manifest/mp4 请求，"
            "否则改用本地视频入口。"
        ) if mse_boundary_summary else "页面没有暴露可还原的直接媒体资源，或触发了 DRM/EME 边界。"
        confidence = "high" if task.drm_detected else "medium"
        severity = "hard_boundary"
        next_action = "local_upload"
    elif "auth_required" in codes:
        primary_code = "auth_required"
        diagnosis = "登录态或 Cookie 已失效，后端无法复用浏览器当前权限下载。"
        confidence = "high"
        severity = "recoverable"
        next_action = "refresh_login_and_retry"
    elif "network_tls_error" in codes:
        primary_code = "network_tls_error"
        diagnosis = "视频服务器的 TLS 连接在下载过程中被提前断开；这不是 HTTP 拒绝，通常可以重试。"
        confidence = "high"
        severity = "recoverable"
        next_action = "refresh_playback_and_retry"
    elif "download_forbidden" in codes:
        primary_code = "download_forbidden"
        diagnosis = "媒体地址被防盗链、时效签名、Referer/Origin 或服务端策略拒绝。"
        confidence = "medium"
        severity = "recoverable"
        next_action = "refresh_playback_and_retry"
    elif "unsupported_manifest" in codes:
        primary_code = "unsupported_manifest"
        diagnosis = "已看到媒体线索，但 manifest 或分片不足以在本地合并。"
        confidence = "medium"
        severity = "recoverable"
        next_action = "play_longer_and_redetect"
    elif selected_kind == "blob":
        primary_code = "no_media_found"
        diagnosis = (
            f"{mse_boundary_summary} 需要继续播放并重新检测真实 manifest/mp4 请求。"
            if mse_boundary_summary
            else "当前只有 blob 播放线索，尚未发现可直接下载的 manifest 或媒体文件。"
        )
        confidence = "high" if mse_boundary_summary else "medium"
        severity = "recoverable"
        next_action = "play_and_redetect"
    elif "no_media_found" in codes or (task.status == "failed" and not task.download_attempts):
        primary_code = "no_media_found"
        diagnosis = "当前页还没有暴露 mp4、m3u8、mpd 或 yt-dlp 可解析的下载入口。"
        confidence = "medium"
        severity = "recoverable"
        next_action = "play_and_redetect"
    elif task.status == "failed":
        primary_code = primary_code or "processing_failed"
        diagnosis = task.error_detail or "任务失败，需要查看下载尝试和阶段审计定位。"
        confidence = "low"
        severity = "recoverable"
        next_action = "inspect_diagnostics"
    else:
        primary_code = primary_code or ""
        diagnosis = "任务仍可继续按阶段审计检查媒体、转写、切片和总结产物。"
        confidence = "medium"
        severity = "ok"
        next_action = "inspect_audit"

    if is_chaoxing:
        boundary_notes.append("学习通/超星第一版只复用当前页面暴露的真实媒体 URL、Referer 和 Cookie，不刷课、不伪造学习进度、不自动答题。")
    if "drm_or_encrypted" in codes or task.drm_detected:
        boundary_notes.append("不会录制、破解或绕过 DRM/EME；blob 只有在扩展捕获到真实 manifest/媒体请求时才可直取。")
    if mse_boundary_summary:
        boundary_notes.append(f"{mse_boundary_summary} 这只能作为播放证据，不能替代直接媒体下载。")
    if selected and selected.request_headers:
        boundary_notes.append(f"已捕获可复用请求头名：{_safe_header_names(selected.request_headers)}；不会保存 Cookie 或 Authorization 值。")
    if selected and _has_range_header(selected.request_headers):
        boundary_notes.append("Range 请求只作为播放证据，正式下载会去掉 Range，避免只保存片段。")
    if not boundary_notes:
        boundary_notes.append("当前页直取失败时，本地视频上传会复用同一套转写、切片和图文总结管线。")

    actions = _diagnostic_recovery_actions(task, next_action, evidence)

    return {
        "code": primary_code,
        "diagnosis": diagnosis,
        "severity": severity,
        "confidence": confidence,
        "next_action": next_action,
        "primary_action": actions[0],
        "actions": actions,
        "is_chaoxing": is_chaoxing,
        "chaoxing_profile": chaoxing_profile,
        "selected_kind": selected_kind,
        "selected_source": selected_source,
        "selected_url": selected_url,
        "checkpoint": task.checkpoint,
        "checkpoint_updated_at": task.checkpoint_updated_at,
        "attempt_count": len(task.download_attempts),
        "latest_attempt": {
            "strategy": latest_attempt.strategy,
            "code": latest_attempt.code,
            "status": latest_attempt.status,
            "status_code": latest_attempt.status_code,
            "message": latest_attempt.message,
        } if latest_attempt else None,
        "steps": diagnostic_recovery_steps(task, evidence),
        "boundary_notes": boundary_notes,
    }
