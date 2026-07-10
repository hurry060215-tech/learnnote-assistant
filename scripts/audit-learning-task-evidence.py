from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = ROOT / "data" / "tasks"
AUDIT_DIR = ROOT / "data" / "test-runs" / "site-audits"
LEARNING_RE = re.compile(r"chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|学习通|超星", re.IGNORECASE)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "<redacted>" if parsed.query else "", ""))


def artifact_ready(task: dict, field: str, *, minimum_bytes: int = 1) -> bool:
    raw = str(task.get(field) or "")
    if not raw:
        return False
    path = Path(raw)
    try:
        return path.is_file() and path.stat().st_size >= minimum_bytes
    except OSError:
        return False


def evaluate_task(task: dict) -> dict:
    selected = task.get("selected_resource") or {}
    attempts = task.get("download_attempts") or []
    successful = next((item for item in attempts if item.get("status") == "success"), {})
    evidence_text = " ".join(
        str(value or "")
        for value in (
            task.get("page_url"),
            task.get("title"),
            selected.get("frame_url"),
            selected.get("page_url"),
            selected.get("label"),
            selected.get("source"),
        )
    )
    detected = bool(LEARNING_RE.search(evidence_text))
    media_ready = artifact_ready(task, "media_path", minimum_bytes=1024 * 1024)
    transcript_ready = artifact_ready(task, "transcript_path", minimum_bytes=10)
    note_ready = artifact_ready(task, "note_path", minimum_bytes=10)
    visual_ready = bool(task.get("frame_grids") or task.get("visual_windows"))
    direct_ready = bool(
        successful
        and successful.get("strategy") in {"direct-file", "direct-av-file", "manifest-ffmpeg", "page-ytdlp"}
        and (successful.get("bytes_downloaded") or successful.get("output_path"))
    )
    ready = bool(
        task.get("source_type") == "current_page"
        and task.get("status") == "success"
        and detected
        and direct_ready
        and media_ready
        and transcript_ready
        and note_ready
        and visual_ready
        and not task.get("drm_detected")
    )
    source_text = evidence_text.lower()
    signals = {
        "ananas": "ananas" in source_text,
        "playurl": bool(selected.get("url") or selected.get("resolved_url")),
        "objectid": "objectid" in source_text,
        "dtoken": "dtoken" in source_text,
        "iframe": "ananas/modules/video" in source_text or "iframe" in source_text,
        "cookie": bool((task.get("cookie_summary") or {}).get("count")),
    }
    return {
        "ready": ready,
        "detected": detected,
        "direct_ready": direct_ready,
        "media_ready": media_ready,
        "transcript_ready": transcript_ready,
        "note_ready": note_ready,
        "visual_ready": visual_ready,
        "signals": signals,
        "successful_attempt": successful,
        "selected": selected,
    }


def candidate_tasks(task_id: str = "") -> list[tuple[Path, dict, dict]]:
    paths = [TASK_DIR / task_id / "task.json"] if task_id else list(TASK_DIR.glob("*/task.json"))
    candidates: list[tuple[Path, dict, dict]] = []
    for path in paths:
        task = load_json(path)
        if not task:
            continue
        evaluation = evaluate_task(task)
        if evaluation["ready"]:
            candidates.append((path, task, evaluation))
    return sorted(candidates, key=lambda item: str(item[1].get("updated_at") or ""), reverse=True)


def build_entry(task: dict, evaluation: dict) -> dict:
    selected = evaluation["selected"]
    successful = evaluation["successful_attempt"]
    signals = evaluation["signals"]
    missing = [name for name, present in signals.items() if not present]
    return {
        "url": redact_url(str(task.get("page_url") or "")),
        "context": {
            "tab": {"url": redact_url(str(task.get("page_url") or "")), "title": str(task.get("title") or "")},
            "page": {"title": str(task.get("title") or "")},
        },
        "evidence": {
            "profile": {
                "readiness": "ready_to_download",
                "route": "completed-task-artifact",
                "task_probe": {"ready": True, "task_id": task.get("id"), "status": task.get("status")},
                "learning_platform": {
                    "detected": True,
                    **signals,
                    "missing_signals": missing,
                    "direct_task": {
                        "ready": True,
                        "download_success": evaluation["direct_ready"],
                        "processing_success": all((evaluation["transcript_ready"], evaluation["note_ready"], evaluation["visual_ready"])),
                        "no_tab_recording": True,
                        "no_drm_bypass": True,
                    },
                },
                "direct_download": {
                    "strategy": successful.get("strategy") or "",
                    "bytes_downloaded": successful.get("bytes_downloaded"),
                    "status_code": successful.get("status_code"),
                    "mime": successful.get("mime") or selected.get("mime") or "",
                    "media_host": urlsplit(str(selected.get("url") or selected.get("resolved_url") or "")).hostname or "",
                    "request_header_names": successful.get("request_header_names") or [],
                },
                "artifacts": {
                    "media": evaluation["media_ready"],
                    "transcript": evaluation["transcript_ready"],
                    "visual": evaluation["visual_ready"],
                    "note": evaluation["note_ready"],
                },
                "boundary": "direct download only; no tab recording, progress spoofing, auto-answering, or DRM bypass",
            }
        },
    }


def write_report(task: dict, entry: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "audit.json"
    md_path = output_dir / "audit.md"
    json_path.write_text(json.dumps([entry], ensure_ascii=False, indent=2), encoding="utf-8")
    profile = entry["evidence"]["profile"]
    learning = profile["learning_platform"]
    direct = profile["direct_download"]
    artifacts = profile["artifacts"]
    lines = [
        "# LearnNote learning-platform task evidence",
        "",
        f"- Time: {datetime.now(timezone.utc).isoformat()}",
        f"- Task: `{task.get('id')}`",
        f"- Page: `{entry['url']}`",
        "- Readiness: `ready_to_download`",
        f"- Direct route: `{direct.get('strategy') or '-'}` / HTTP {direct.get('status_code') or '-'} / {direct.get('bytes_downloaded') or 0} bytes",
        f"- Media host: `{direct.get('media_host') or '-'}`",
        f"- Artifacts: media={artifacts['media']}, transcript={artifacts['transcript']}, visual={artifacts['visual']}, note={artifacts['note']}",
        f"- Captured signals: {', '.join(name for name in ('ananas', 'playurl', 'objectid', 'dtoken', 'iframe', 'cookie') if learning.get(name)) or '-'}",
        f"- Optional signals not needed by this successful direct route: {', '.join(learning.get('missing_signals') or []) or '-'}",
        "- Boundary: direct download only; no tab recording, progress spoofing, auto-answering, or DRM bypass.",
        "- Privacy: signed query values, cookie values, authorization values, and request bodies are not included.",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a redacted learning-platform audit from a completed real task.")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    candidates = candidate_tasks(args.task_id)
    if not candidates:
        print("No completed real learning-platform direct task evidence found.")
        return 2 if args.require_ready else 0
    _, task, evaluation = candidates[0]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output) if args.output else AUDIT_DIR / f"learning-task-{stamp}"
    json_path, md_path = write_report(task, build_entry(task, evaluation), output_dir)
    print(f"PASS task={task.get('id')} readiness=ready_to_download")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
