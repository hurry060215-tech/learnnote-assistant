from __future__ import annotations

import tempfile
from pathlib import Path

from .config import TEMP_DIR
from .downloader import MediaDownloader, effective_resource_kind, fallback_page_contexts, preflight_media_resource, rank_media_candidates
from .models import MediaPreflightResult, PagePreflightRequest, ResourceCandidate
from .processor import enrich_resource_candidates_with_active_video


def resource_with_preflight_result(candidate: ResourceCandidate, result: MediaPreflightResult) -> ResourceCandidate:
    resource = candidate.model_copy(deep=True)
    if result.resolved_url:
        resource.resolved_url = result.resolved_url
    if result.kind and result.kind != "unknown":
        resource.kind = result.kind
    if result.content_type:
        resource.mime = result.content_type
    if result.content_length:
        resource.content_length = result.content_length
    if result.status_code:
        resource.status_code = result.status_code
    return resource


def _should_scan_page_for_preflight(request: PagePreflightRequest, ranked: list[ResourceCandidate], *, after_failed_probe: bool = False) -> bool:
    if request.probe_limit <= 0 or not request.page_url:
        return False
    if len(ranked) >= request.probe_limit and not after_failed_probe:
        return False
    if not request.resources:
        return True
    if request.drm_detected and all(effective_resource_kind(item) == "blob" for item in request.resources):
        return False
    for item in request.resources:
        kind = effective_resource_kind(item)
        if kind == "blob":
            continue
        if kind == "unknown":
            return True
        if item.frame_url or item.page_url or item.request_headers.get("Referer") or item.initiator:
            return True
    return False


def _preflight_page_scan_resources(request: PagePreflightRequest, ranked: list[ResourceCandidate], *, after_failed_probe: bool = False) -> tuple[list[ResourceCandidate], list[dict]]:
    if not _should_scan_page_for_preflight(request, ranked, after_failed_probe=after_failed_probe):
        return [], []
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    discovered: list[ResourceCandidate] = []
    seen = {item.url for item in request.resources if item.url}
    with tempfile.TemporaryDirectory(prefix="page-preflight-", dir=str(TEMP_DIR)) as workspace:
        downloader = MediaDownloader(Path(workspace))
        for fallback_url, context_candidate in fallback_page_contexts(request.page_url, request.resources):
            for item in downloader._discover_page_resources(fallback_url, request.cookies, context_candidate):
                if not item.url or item.url in seen:
                    continue
                seen.add(item.url)
                discovered.append(item)
    attempts = [attempt.model_dump(mode="json") for attempt in downloader.attempts]
    return discovered, attempts


def page_preflight_report(request: PagePreflightRequest) -> dict:
    request.resources = enrich_resource_candidates_with_active_video(request.active_video, request.resources)
    initial_ranked = rank_media_candidates(request.resources)
    discovered_resources, discovery_attempts = _preflight_page_scan_resources(request, initial_ranked)
    ranked = rank_media_candidates([*request.resources, *discovered_resources]) if discovered_resources else initial_ranked
    preflight_cache: dict[str, MediaPreflightResult] = {}

    def evaluate_candidates(
        candidate_list: list[ResourceCandidate],
        *,
        extra_probe_urls: set[str] | None = None,
    ) -> tuple[int, int, str, list[dict]]:
        probed = 0
        downloadable_count = 0
        selected_url = ""
        candidates: list[dict] = []
        extra_probe_urls = extra_probe_urls or set()

        for index, candidate in enumerate(candidate_list, start=1):
            should_probe = probed < request.probe_limit or candidate.url in extra_probe_urls
            if should_probe:
                result = preflight_cache.get(candidate.url)
                if result is None:
                    result = preflight_media_resource(candidate, request.cookies, request.page_url)
                    preflight_cache[candidate.url] = result
                probed += 1
                resource = resource_with_preflight_result(candidate, result)
                if result.downloadable:
                    downloadable_count += 1
                    if not selected_url:
                        selected_url = resource.url
                        resource.user_selected = True
                        resource.score = 100
            else:
                result = MediaPreflightResult(
                    ok=True,
                    downloadable=False,
                    strategy="not-probed",
                    kind=effective_resource_kind(candidate),
                    url=candidate.url,
                    resolved_url=candidate.resolved_url or candidate.url,
                    code="not_probed",
                    message="候选排序靠后，本次整页预检未发起网络探测；启动任务时仍可作为后续下载候选。",
                )
                resource = resource_with_preflight_result(candidate, result)

            candidates.append({
                "rank": index,
                "resource": resource.model_dump(mode="json"),
                "preflight": result.model_dump(mode="json"),
            })
        return probed, downloadable_count, selected_url, candidates

    probed, downloadable_count, selected_url, candidates = evaluate_candidates(ranked)
    if not selected_url:
        fallback_resources, fallback_attempts = _preflight_page_scan_resources(request, ranked, after_failed_probe=True)
        if fallback_resources:
            existing_urls = {item.url for item in discovered_resources}
            new_resources = [item for item in fallback_resources if item.url not in existing_urls]
            discovered_resources.extend(new_resources)
            discovery_attempts.extend(fallback_attempts)
            ranked = rank_media_candidates([*request.resources, *discovered_resources])
            probed, downloadable_count, selected_url, candidates = evaluate_candidates(
                ranked,
                extra_probe_urls={item.url for item in new_resources if item.url},
            )

    direct_candidate_count = sum(1 for item in ranked if effective_resource_kind(item) in {"video", "hls", "dash"})
    has_drm_boundary = request.drm_detected

    if selected_url:
        code = ""
        message = f"整页预检通过：{downloadable_count} 个候选可访问，默认选择排序最靠前的可下载资源。"
    elif has_drm_boundary and not direct_candidate_count:
        code = "drm_or_encrypted"
        message = "页面只暴露 blob/DRM 播放线索，没有可交给后端下载的 mp4、m3u8 或 mpd。"
    elif ranked:
        preflight_codes = [str(item["preflight"].get("code") or "") for item in candidates]
        code = (
            "no_media_found"
            if preflight_codes and all(item in {"no_media_found", "not_probed"} for item in preflight_codes)
            else "download_forbidden"
        )
        message = "整页预检没有发现可直接下载的候选；可继续播放后重新检测，或改用本地视频上传。"
    elif has_drm_boundary:
        code = "drm_or_encrypted"
        message = "页面只暴露 blob/DRM 播放线索，没有可交给后端下载的 mp4、m3u8 或 mpd。"
    else:
        code = "no_media_found"
        message = "当前页没有发现可预检的 mp4、m3u8 或 mpd 候选。"

    return {
        "ok": True,
        "ready": bool(selected_url),
        "code": code,
        "message": message,
        "selected_url": selected_url,
        "candidate_count": len(ranked),
        "probed_count": probed,
        "downloadable_count": downloadable_count,
        "page_scan": {
            "attempted": bool(discovery_attempts),
            "discovered_count": len(discovered_resources),
            "attempts": discovery_attempts,
        },
        "candidates": candidates,
    }
