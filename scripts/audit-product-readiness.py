from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SITE_AUDIT_DIR = ROOT / "data" / "test-runs" / "site-audits"
PRODUCT_ACCEPTANCE_DIR = ROOT / "data" / "test-runs" / "product-acceptance"


@dataclass
class Evidence:
    path: str
    detail: str


@dataclass
class ReadinessItem:
    key: str
    title: str
    status: str
    detail: str
    evidence: list[Evidence] = field(default_factory=list)
    next_step: str = ""


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return ""


def has_all(text: str, tokens: Iterable[str]) -> bool:
    lower = text.lower()
    return all(token.lower() in lower for token in tokens)


def has_any(text: str, tokens: Iterable[str]) -> bool:
    lower = text.lower()
    return any(token.lower() in lower for token in tokens)


def item(
    key: str,
    title: str,
    status: str,
    detail: str,
    evidence: Iterable[tuple[Path, str]] = (),
    next_step: str = "",
) -> ReadinessItem:
    return ReadinessItem(
        key=key,
        title=title,
        status=status,
        detail=detail,
        evidence=[Evidence(path=rel(path), detail=detail_text) for path, detail_text in evidence],
        next_step=next_step,
    )


def collect_site_audits() -> list[dict]:
    audits: list[dict] = []
    if not SITE_AUDIT_DIR.exists():
        return audits
    for path in sorted(SITE_AUDIT_DIR.glob("*/audit.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict):
                    audits.append({"path": path, "entry": entry})
    return audits


def profile_for(entry: dict) -> dict:
    return ((entry.get("evidence") or {}).get("profile") or {})


def audit_url_text(entry: dict) -> str:
    parts = [
        entry.get("url") or "",
        ((entry.get("context") or {}).get("tab") or {}).get("url") or "",
        ((entry.get("context") or {}).get("tab") or {}).get("title") or "",
        ((entry.get("context") or {}).get("page") or {}).get("title") or "",
    ]
    return " ".join(str(part) for part in parts).lower()


def is_local_audit(entry: dict) -> bool:
    text = audit_url_text(entry)
    return "127.0.0.1" in text or "localhost" in text


def ready_site_audit(audits: list[dict], tokens: Iterable[str] | None = None, *, include_local: bool = False) -> dict | None:
    wanted = [token.lower() for token in (tokens or [])]
    for audit in audits:
        entry = audit["entry"]
        if not include_local and is_local_audit(entry):
            continue
        if wanted and not any(token in audit_url_text(entry) for token in wanted):
            continue
        profile = profile_for(entry)
        if profile.get("readiness") == "ready_to_download":
            return audit
    return None


def ytdlp_supported_audit(audits: list[dict], *, include_local: bool = False) -> dict | None:
    for audit in audits:
        entry = audit["entry"]
        if not include_local and is_local_audit(entry):
            continue
        profile = profile_for(entry)
        task_probe = profile.get("task_probe") or {}
        ytdlp_probe = profile.get("ytdlp_probe") or {}
        if (
            profile.get("readiness") == "ready_to_download"
            and task_probe.get("ready")
            and ytdlp_probe.get("ready")
            and ytdlp_probe.get("extractor")
        ):
            return audit
    return None


def learning_audit(audits: list[dict], *, include_local: bool = False) -> dict | None:
    required = {"ananas", "playurl", "objectid", "dtoken", "iframe", "cookie"}
    for audit in audits:
        if not include_local and is_local_audit(audit["entry"]):
            continue
        profile = profile_for(audit["entry"])
        platform = profile.get("learning_platform") or {}
        if platform.get("detected") and all(platform.get(name) for name in required):
            return audit
    return None


def local_sample_audit(audits: list[dict]) -> dict | None:
    for audit in audits:
        if is_local_audit(audit["entry"]):
            return audit
    return None


def acceptance_report_ready(text: str) -> bool:
    required = [
        "- PASS doctor",
        "- PASS real browser extension smoke: local MP4/HLS/API/blob/learning mock",
        "- PASS yt-dlp supported real-site task probe",
        "- PASS learning-platform local mock gate",
        "- PASS product readiness matrix",
    ]
    return has_all(text, required) and "- FAIL " not in text


def latest_product_acceptance_report() -> tuple[Path, str] | None:
    if not PRODUCT_ACCEPTANCE_DIR.exists():
        return None
    for path in sorted(PRODUCT_ACCEPTANCE_DIR.glob("*/summary.md"), reverse=True):
        text = read_text(path)
        if text.strip():
            return path, text
    return None


def site_audit_items(audits: list[dict]) -> list[ReadinessItem]:
    rows: list[ReadinessItem] = []
    targets = [
        (
            "real_site_mp4_hls",
            "Public MP4/HLS real page audit",
            ["mp4", "m3u8", "hls"],
            "Run scripts/audit-real-site.ps1 <mp4-or-hls-url> -Preflight -RequireReady with the unpacked extension.",
        ),
    ]
    for key, title, tokens, next_step in targets:
        audit = ready_site_audit(audits, tokens)
        if audit:
            rows.append(item(
                key,
                title,
                "pass",
                "A ready_to_download real-site audit report exists.",
                [(audit["path"], "latest matching audit.json reports ready_to_download")],
            ))
        else:
            rows.append(item(
                key,
                title,
                "manual",
                "No current ready_to_download live-site audit report was found in data/test-runs/site-audits.",
                next_step=next_step,
            ))
    ytdlp = ytdlp_supported_audit(audits)
    if ytdlp:
        rows.append(item(
            "real_site_ytdlp",
            "yt-dlp supported site audit",
            "pass",
            "A real-site audit has both a successful download-only task and a ready yt-dlp extractor probe.",
            [(ytdlp["path"], "task_probe.ready and ytdlp_probe.ready are both true")],
        ))
    else:
        rows.append(item(
            "real_site_ytdlp",
            "yt-dlp supported site audit",
            "manual",
            "No current real-site audit has both task_probe.ready and ytdlp_probe.ready evidence.",
            next_step=(
                "Run scripts/audit-real-site.ps1 <yt-dlp-supported-url> -TaskProbe -YtdlpProbe "
                "-RequireReady -TaskTimeout 180. Use -TaskProbePageOnly to test backend page fallback without captured browser resources."
            ),
        ))
    chaoxing = learning_audit(audits)
    if chaoxing:
        rows.append(item(
            "real_site_chaoxing",
            "Logged-in learning-platform audit",
            "pass",
            "A learning-platform audit contains ananas/playurl/objectid/dtoken/iframe/cookie evidence.",
            [(chaoxing["path"], "learning profile evidence is complete")],
        ))
    else:
        rows.append(item(
            "real_site_chaoxing",
            "Logged-in learning-platform audit",
            "manual",
            "No logged-in learning-platform audit with the full evidence chain was found.",
            next_step="Run scripts/audit-learning-platform.ps1 <learning-url>. Use -Mock to rehearse the same gate locally.",
        ))
    return rows


def build_matrix() -> list[ReadinessItem]:
    sidepanel_html = read_text(ROOT / "extension" / "sidepanel.html")
    sidepanel_js = read_text(ROOT / "extension" / "sidepanel.js")
    sidepanel_css = read_text(ROOT / "extension" / "sidepanel.css")
    backend_main = read_text(ROOT / "backend" / "app" / "main.py")
    processor = read_text(ROOT / "backend" / "app" / "processor.py")
    media = read_text(ROOT / "backend" / "app" / "media.py")
    samples = read_text(ROOT / "scripts" / "serve-samples.py")
    extension_smoke = read_text(ROOT / "scripts" / "e2e-extension-smoke.py")
    local_smoke = read_text(ROOT / "scripts" / "e2e-local-smoke.py")
    audit_real_site = read_text(ROOT / "scripts" / "audit-real-site.py")
    first_run = read_text(ROOT / "scripts" / "first-run-checklist.ps1")
    doctor = read_text(ROOT / "scripts" / "doctor.py")
    launcher = read_text(ROOT / "start-learnnote.ps1")
    web_html = read_text(ROOT / "web" / "index.html")
    web_js = read_text(ROOT / "web" / "app.js")
    web_css = read_text(ROOT / "web" / "styles.css")
    readme = read_text(ROOT / "README.md")
    audits = collect_site_audits()

    rows: list[ReadinessItem] = []
    ui_ready = (
        has_all(sidepanel_html, ["currentStudyCard", "sourceRouteRail", "taskHistory", "result-tab", "diagnosticModeButton"])
        and has_all(sidepanel_js, ["setPanelMode", "study-flow-board", "study-next-step", "panelMode === \"diagnostics\"", "review-command-grid", "review-advanced-row"])
        and has_all(sidepanel_css, ["current-study-card", "study-flow-board", "study-next-step", "review-command-grid", "diagnostics"])
    )
    rows.append(item(
        "side_panel_product_flow",
        "BiliNote-style Side Panel flow",
        "pass" if ui_ready else "fail",
        (
            "Study mode foregrounds current video, next action, slice summary, history, and keeps adapter/resource details behind diagnostics."
            if ui_ready else "Side Panel product-flow tokens are missing."
        ),
        [
            (ROOT / "extension" / "sidepanel.html", "study/diagnostics tabs, current task card, history, result tabs"),
            (ROOT / "extension" / "sidepanel.js", "study-flow board, next-step card, and diagnostics-only adapter/resource details"),
            (ROOT / "extension" / "sidepanel.css", "product-flow, next-step, and diagnostic styling"),
        ],
        "Restore the study/diagnostics split and keep raw resource/adapter details out of the default study view." if not ui_ready else "",
    ))

    direct_ready = has_all(sidepanel_js + audit_real_site + backend_main, [
        "download_only",
        "preflight",
        "yt-dlp",
        "cookie",
        "no tab recording",
    ]) and has_all(audit_real_site, ["require_ready", "ready_to_download"])
    rows.append(item(
        "non_recording_direct_extraction",
        "Current-page direct extraction boundary",
        "pass" if direct_ready else "fail",
        "Direct media/preflight/yt-dlp/cookie handoff is represented without tab recording." if direct_ready else "Direct-extraction boundary evidence is incomplete.",
        [
            (ROOT / "extension" / "sidepanel.js", "download-only and current-page preflight flow"),
            (ROOT / "scripts" / "audit-real-site.py", "ready_to_download gate and no-recording boundary"),
            (ROOT / "backend" / "app" / "main.py", "download/preflight/task APIs"),
        ],
    ))

    local_video_ready = has_all(sidepanel_html + backend_main + processor, [
        "from-local",
        "upload",
        "process_local_video_task",
    ]) or has_all(backend_main + processor, ["api_tasks_from_local", "process_local_video_task"])
    rows.append(item(
        "local_video_pipeline",
        "Local video upload pipeline",
        "pass" if local_video_ready else "fail",
        "Local upload enters the same media/transcript/frame/note pipeline." if local_video_ready else "Local upload task route or processor is missing.",
        [
            (ROOT / "extension" / "sidepanel.html", "local video upload/drop target"),
            (ROOT / "backend" / "app" / "main.py", "local upload API"),
            (ROOT / "backend" / "app" / "processor.py", "local video processor"),
        ],
    ))

    visual_ready = has_all(processor + media + backend_main + sidepanel_js, [
        "visual_index.json",
        "build_frame_grids",
        "build_visual_windows",
        "visualStudyDeck",
        "transcript-window",
    ]) and has_all(web_js + web_css + sidepanel_js + sidepanel_css, [
        "visualStudyOverviewHtml",
        "visualStudyReviewPathHtml",
        "visualStudyHandoutHtml",
        "visual-study-correlation",
    ])
    rows.append(item(
        "visual_slice_notes",
        "Slice and visual-summary result page",
        "pass" if visual_ready else "fail",
        "Frame grids, visual windows, transcript alignment, review path, handout timeline, evidence matrix, and export surface are implemented in the result UIs." if visual_ready else "Visual slice/result-page evidence is incomplete.",
        [
            (ROOT / "backend" / "app" / "processor.py", "visual index and window generation"),
            (ROOT / "backend" / "app" / "media.py", "frame-grid generation"),
            (ROOT / "extension" / "sidepanel.js", "visual study deck, transcript windows, review path, handout"),
            (ROOT / "web" / "app.js", "Web visual study overview, review path, handout, evidence matrix"),
        ],
    ))

    learning_ready = (
        has_all(audit_real_site, ["ananas", "playurl", "objectid", "dtoken", "iframe", "cookie", "require_learning_profile"])
        and has_all(sidepanel_js + sidepanel_css, ["chaoxingProfileHtml", "chaoxing-profile", "chaoxing-mode-flow"])
    )
    rows.append(item(
        "learning_platform_diagnostics",
        "Learning-platform diagnostic mode",
        "pass" if learning_ready else "fail",
        "Learning profile exposes ananas/playurl/objectid/dtoken/iframe/cookie and missing-step guidance." if learning_ready else "Learning-platform diagnostic evidence is incomplete.",
        [
            (ROOT / "scripts" / "audit-real-site.py", "learning profile and gate signals"),
            (ROOT / "extension" / "sidepanel.js", "Side Panel learning-platform diagnosis"),
            (ROOT / "extension" / "sidepanel.css", "learning-platform diagnostic styling"),
        ],
    ))

    samples_ready = has_all(samples + extension_smoke + local_smoke, [
        "mp4.html",
        "hls.html",
        "blob-iframe.html",
        "post-api.html",
        "generic-player.html",
        "/api/lesson/resolve",
        "chaoxing-mock.html",
        "ananas/status/play",
    ])
    rows.append(item(
        "local_regression_samples",
        "Local regression samples",
        "pass" if samples_ready else "fail",
        "MP4, HLS, blob iframe, generic/POST play APIs, and Chaoxing-style mock are covered by local and extension smoke gates." if samples_ready else "Local sample or smoke coverage is incomplete.",
        [
            (ROOT / "scripts" / "serve-samples.py", "sample pages and generated fixtures"),
            (ROOT / "scripts" / "e2e-local-smoke.py", "backend/sample smoke"),
            (ROOT / "scripts" / "e2e-extension-smoke.py", "real MV3 extension smoke"),
        ],
    ))

    startup_ready = (
        has_all(first_run + doctor + launcher + readme, [
            "first-run-guide.md",
            "ffmpeg",
            "yt-dlp",
            "faster-whisper",
            "extension",
            "LEARNNOTE_LLM_API_KEY",
            "D:\\Projects\\learnnote-assistant",
            "audit-learning-platform.ps1",
            "audit-product-acceptance.ps1",
        ])
        and has_all(web_html + web_js + backend_main, ["startupReadiness", "startupReadinessItems", "yt_dlp_available"])
        and has_all(doctor, ["project location", "backend runtime", "script_check"])
    )
    rows.append(item(
        "startup_onboarding",
        "Startup and installation experience",
        "pass" if startup_ready else "fail",
        "D-drive paths, ffmpeg/yt-dlp/faster-whisper checks, extension loading, backend startup, API key setup, and guide output are documented/checkable." if startup_ready else "Startup/onboarding readiness is incomplete.",
        [
            (ROOT / "scripts" / "first-run-checklist.ps1", "machine-specific first-run guide"),
            (ROOT / "scripts" / "doctor.py", "runtime and dependency checks"),
            (ROOT / "scripts" / "audit-product-acceptance.ps1", "product acceptance gate"),
            (ROOT / "start-learnnote.ps1", "D-drive launcher"),
            (ROOT / "web" / "index.html", "startup readiness card"),
            (ROOT / "web" / "app.js", "startup readiness health rendering"),
            (ROOT / "README.md", "Quick Start and real-site audit instructions"),
        ],
    ))

    generic_ready = has_all(sidepanel_js + audit_real_site + samples, [
        "playUrl",
        "streamUrl",
        "manifestUrl",
        "generic-player.html",
        "MediaSource",
        "iframe",
        "request_body",
        "referer",
        "workbenchUniversalAdapterItems",
        "workbench-adapter-ladder",
    ]) and has_any(sidepanel_js + samples, ["videoUrl", "hls", "dashUrl", "play_url", "/api/lesson/resolve"])
    rows.append(item(
        "generic_adapter_direction",
        "Generic website adapter direction",
        "pass" if generic_ready else "fail",
        "Generic direct-download routes cover DOM/performance/webRequest/page-hook/API/body/iframe/blob-MSE clues plus a non-Chaoxing nested player API sample instead of a single site-only path." if generic_ready else "Generic adapter evidence is too site-specific or incomplete.",
        [
            (ROOT / "extension" / "sidepanel.js", "candidate ranking and preflight source switching"),
            (ROOT / "scripts" / "audit-real-site.py", "generic signal profile"),
            (ROOT / "scripts" / "serve-samples.py", "site-agnostic regression mocks"),
        ],
    ))

    acceptance = latest_product_acceptance_report()
    if acceptance and acceptance_report_ready(acceptance[1]):
        rows.append(item(
            "product_acceptance_gate",
            "Full product acceptance gate",
            "pass",
            "Latest product acceptance report proves doctor, real Edge/Chrome extension smoke, yt-dlp real-site probe, local learning-platform mock, and readiness matrix.",
            [(acceptance[0], "summary.md has all required PASS rows; logged-in learning-platform real gate may remain manual without -LearningUrl")],
        ))
    elif acceptance:
        rows.append(item(
            "product_acceptance_gate",
            "Full product acceptance gate",
            "warn",
            "A product acceptance report exists, but it does not prove all required local/real-browser gates passed.",
            [(acceptance[0], "summary.md is missing one or more required PASS rows")],
            next_step="Run scripts/audit-product-acceptance.ps1 -Browser edge. Provide -LearningUrl for the logged-in learning-platform real gate.",
        ))
    else:
        rows.append(item(
            "product_acceptance_gate",
            "Full product acceptance gate",
            "warn",
            "No product acceptance report exists under data/test-runs/product-acceptance.",
            next_step="Run scripts/audit-product-acceptance.ps1 -Browser edge. Provide -LearningUrl for the logged-in learning-platform real gate.",
        ))

    rows.extend(site_audit_items(audits))

    local_audit = local_sample_audit(audits)
    if local_audit:
        rows.append(item(
            "recent_local_audit_report",
            "Recent local browser audit artifact",
            "pass",
            "At least one local browser audit report exists under data/test-runs/site-audits.",
            [(local_audit["path"], "local audit artifact")],
        ))
    else:
        rows.append(item(
            "recent_local_audit_report",
            "Recent local browser audit artifact",
            "warn",
            "No local site-audit artifact exists yet; this is expected on a fresh clone but useful before handoff.",
            next_step="Run scripts/audit-real-site.ps1 http://127.0.0.1:8777/chaoxing-mock.html -Preflight -RequireReady -RequireLearningProfile after starting samples.",
        ))

    return rows


def status_counts(rows: list[ReadinessItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return dict(sorted(counts.items()))


def markdown(rows: list[ReadinessItem]) -> str:
    counts = status_counts(rows)
    lines = [
        "# LearnNote product readiness audit",
        "",
        f"- Time: {datetime.now().isoformat(timespec='seconds')}",
        f"- Project: `{ROOT}`",
        f"- Status counts: {', '.join(f'{key}={value}' for key, value in counts.items()) or '-'}",
        "- Boundary: pass here proves code/local evidence only; `manual` rows require real browser/login evidence.",
        "",
        "| Status | Area | Evidence | Next step |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        evidence = "<br>".join(f"`{item.path}`: {item.detail}" for item in row.evidence) or "-"
        next_step = row.next_step or "-"
        lines.append(f"| `{row.status}` | **{row.title}**<br>{row.detail} | {evidence} | {next_step} |")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit LearnNote product readiness against the current product objective.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    parser.add_argument("--output", default="", help="Optional output path for the report.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on fail/warn/manual rows.")
    parser.add_argument("--require-real-site-audits", action="store_true", help="Return non-zero if any real-site audit row is manual.")
    args = parser.parse_args()

    rows = build_matrix()
    payload = {
        "project": str(ROOT),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "counts": status_counts(rows),
        "items": [asdict(row) for row in rows],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) if args.json else markdown(rows)
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)

    statuses = {row.status for row in rows}
    if "fail" in statuses:
        return 1
    if args.require_real_site_audits and any(row.status == "manual" and row.key.startswith("real_site_") for row in rows):
        return 3
    if args.strict and statuses.intersection({"warn", "manual"}):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
