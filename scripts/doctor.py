from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DATA_DIR = ROOT / "data"
EXTENSION_DIR = ROOT / "extension"
DEFAULT_CHROME = [
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
]
DEFAULT_EDGE = [
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
]


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def project_python() -> Path:
    override = os.getenv("LEARNNOTE_VENV_DIR")
    venv_dir = Path(override) if override else ROOT / ".venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    resolved = shutil.which("python")
    return Path(resolved) if resolved else Path(sys.executable)


def status_line(check: Check) -> str:
    symbols = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    fix = f"\n       fix: {check.fix}" if check.fix else ""
    return f"{symbols.get(check.status, '[INFO]')} {check.name}: {check.detail}{fix}"


def run_python_snippet(code: str, timeout: int = 20) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    python = project_python()
    proc = subprocess.run(
        [str(python), "-c", code],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def import_check(module: str, *, optional: bool = False, package_label: str | None = None) -> Check:
    code = (
        "import importlib, json\n"
        f"mod = importlib.import_module({module!r})\n"
        "version = getattr(mod, '__version__', '')\n"
        "print(json.dumps({'version': version}))\n"
    )
    rc, out, err = run_python_snippet(code)
    label = package_label or module
    if rc != 0:
        return Check(
            label,
            "WARN" if optional else "FAIL",
            "not importable in the selected Python environment",
            f"run .\\start-learnnote.ps1{' -InstallAsr' if optional else ''}" if optional else "run .\\start-learnnote.ps1 to create the D-drive venv and install backend requirements",
        )
    try:
        payload = json.loads(out or "{}")
    except json.JSONDecodeError:
        payload = {}
    version = payload.get("version") or "installed"
    return Check(label, "PASS", str(version))


def runtime_check() -> Check:
    code = (
        "import json\n"
        "from app.config import DATA_DIR, MODEL_CACHE_DIR, TASK_DIR, TEMP_DIR, UPLOAD_DIR, ensure_dirs\n"
        "from app.runtime import ffmpeg_bin, ffprobe_bin\n"
        "ensure_dirs()\n"
        "paths = {'data': DATA_DIR, 'uploads': UPLOAD_DIR, 'tasks': TASK_DIR, 'model_cache': MODEL_CACHE_DIR, 'temp': TEMP_DIR}\n"
        "print(json.dumps({\n"
        "  'ffmpeg': ffmpeg_bin() or '',\n"
        "  'ffprobe': ffprobe_bin() or '',\n"
        "  'paths': {key: str(value.resolve()) for key, value in paths.items()},\n"
        "  'drives': {key: value.resolve().drive for key, value in paths.items()},\n"
        "}, ensure_ascii=False))\n"
    )
    rc, out, err = run_python_snippet(code)
    if rc != 0:
        return Check("backend runtime", "FAIL", (err or out or "runtime import failed")[:300], "run .\\start-learnnote.ps1")
    payload = json.loads(out)
    ffmpeg = payload.get("ffmpeg") or ""
    paths = payload.get("paths", {})
    drives = set(payload.get("drives", {}).values())
    root_drive = ROOT.resolve().drive
    bad_drive = any(drive and drive != root_drive for drive in drives)
    if not ffmpeg:
        return Check("backend runtime", "FAIL", f"data={paths.get('data', DATA_DIR)}; ffmpeg not found", "run .\\start-learnnote.ps1 or install ffmpeg / imageio-ffmpeg")
    if bad_drive:
        return Check("backend runtime", "FAIL", f"runtime paths are not all on {root_drive}: {paths}", "keep LEARNNOTE_VENV_DIR and project data on the D-drive project path")
    return Check("backend runtime", "PASS", f"ffmpeg={ffmpeg}; data={paths.get('data', DATA_DIR)}")


def backend_import_check() -> Check:
    rc, out, err = run_python_snippet("import app.main\nprint('ok')", timeout=30)
    if rc == 0:
        return Check("FastAPI app import", "PASS", "app.main imports successfully")
    return Check("FastAPI app import", "FAIL", (err or out or "import failed")[:300], "run .\\start-learnnote.ps1 and inspect backend dependency errors")


def browser_check(name: str, paths: list[Path]) -> Check:
    env_name = f"LEARNNOTE_{name.upper()}_PATH"
    explicit = os.getenv(env_name)
    candidates = [Path(explicit)] if explicit else []
    candidates.extend(paths)
    found = next((path for path in candidates if str(path) and path.exists()), None)
    if found:
        return Check(name, "PASS", str(found))
    return Check(name, "WARN", "not found in common Windows install paths", f"install {name} or set {env_name}")


def manifest_check() -> Check:
    manifest_path = EXTENSION_DIR / "manifest.json"
    if not manifest_path.exists():
        return Check("browser extension", "FAIL", "extension/manifest.json is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("browser extension", "FAIL", f"manifest is invalid JSON: {exc}")
    version = manifest.get("manifest_version")
    permissions = set(manifest.get("permissions") or [])
    required = {"activeTab", "tabs", "scripting", "webRequest", "cookies", "storage", "sidePanel"}
    missing = sorted(required - permissions)
    if version != 3 or missing:
        return Check("browser extension", "FAIL", f"MV{version}; missing permissions: {', '.join(missing) or '-'}")
    return Check("browser extension", "PASS", f"MV3; load unpacked from {EXTENSION_DIR}")


def llm_check() -> Check:
    api_key = os.getenv("LEARNNOTE_LLM_API_KEY", "")
    base = os.getenv("LEARNNOTE_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("LEARNNOTE_LLM_MODEL", "gpt-4.1-mini")
    if api_key:
        return Check("multimodal API", "PASS", f"key configured; base={base}; model={model}")
    return Check("multimodal API", "WARN", f"no LEARNNOTE_LLM_API_KEY; local fallback notes will be used; model default={model}", "set LEARNNOTE_LLM_API_KEY for visual LLM summaries")


def project_location_check() -> Check:
    root = ROOT.resolve()
    if root.drive.upper().startswith("C:"):
        return Check("project location", "FAIL", str(root), "move the project to D:\\Projects\\learnnote-assistant")
    return Check("project location", "PASS", str(root))


def venv_check() -> Check:
    python = project_python()
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    override = os.getenv("LEARNNOTE_VENV_DIR")
    if override:
        override_python = Path(override) / "Scripts" / "python.exe"
        if override_python.exists():
            return Check("Python environment", "PASS", f"{override_python} via LEARNNOTE_VENV_DIR")
        return Check("Python environment", "FAIL", f"{override_python} does not exist", "run .\\start-learnnote.ps1 after setting LEARNNOTE_VENV_DIR")
    if venv_python.exists():
        return Check("Python environment", "PASS", str(venv_python))
    return Check("Python environment", "WARN", f"project venv missing; using {python}", "run .\\start-learnnote.ps1 to create .venv under the D-drive project")


def script_check() -> Check:
    required = [
        ROOT / "start-learnnote.ps1",
        ROOT / "start-backend.ps1",
        ROOT / "scripts" / "serve-samples.ps1",
        ROOT / "scripts" / "first-run-checklist.ps1",
        ROOT / "scripts" / "verify-product.ps1",
        ROOT / "scripts" / "audit-product-acceptance.ps1",
        ROOT / "scripts" / "e2e-local-smoke.ps1",
        ROOT / "scripts" / "e2e-extension-smoke.ps1",
        ROOT / "scripts" / "audit-real-site.ps1",
        ROOT / "scripts" / "audit-learning-platform.ps1",
        ROOT / "scripts" / "audit-product-readiness.ps1",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        return Check("local scripts", "FAIL", f"missing: {', '.join(missing)}")
    return Check("local scripts", "PASS", "launcher, first-run checklist, sample server, product verifier, acceptance gate, smoke gates, real-site/learning-platform audit, and product-readiness audit scripts are present")


def collect_checks() -> list[Check]:
    return [
        project_location_check(),
        venv_check(),
        import_check("fastapi", package_label="FastAPI"),
        import_check("uvicorn", package_label="uvicorn"),
        import_check("yt_dlp", package_label="yt-dlp"),
        import_check("openai", package_label="OpenAI SDK"),
        import_check("imageio_ffmpeg", package_label="imageio-ffmpeg"),
        import_check("faster_whisper", optional=True, package_label="faster-whisper ASR"),
        runtime_check(),
        backend_import_check(),
        manifest_check(),
        browser_check("chrome", DEFAULT_CHROME),
        browser_check("edge", DEFAULT_EDGE),
        llm_check(),
        script_check(),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether LearnNote can run locally from the D-drive project.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Treat WARN as a non-zero exit.")
    args = parser.parse_args()

    checks = collect_checks()
    if args.json:
        print(json.dumps([asdict(check) for check in checks], ensure_ascii=False, indent=2))
    else:
        print(f"LearnNote local doctor\nProject: {ROOT.resolve()}\nPython:  {project_python()}\n")
        for check in checks:
            print(status_line(check))
        print("")
        print("Next:")
        print("  .\\scripts\\first-run-checklist.ps1")
        print("  .\\start-learnnote.ps1")
        print("  .\\scripts\\serve-samples.ps1")
        print("  .\\scripts\\e2e-local-smoke.ps1 -OpenBrowser")
        print("  .\\scripts\\e2e-extension-smoke.ps1")
        print("  .\\scripts\\audit-product-acceptance.ps1 -Browser edge")
        print("  .\\scripts\\audit-real-site.ps1 <url> -Preflight")
        print("  .\\scripts\\audit-learning-platform.ps1 <learning-url>")
        print("  .\\scripts\\audit-product-readiness.ps1")
    statuses = {check.status for check in checks}
    if "FAIL" in statuses:
        return 1
    if args.strict and "WARN" in statuses:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
