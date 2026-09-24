from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_PATH = ROOT / "scripts" / "e2e-extension-smoke.py"
SPEC = importlib.util.spec_from_file_location("learnnote_browser_smoke_support", SMOKE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("browser smoke helpers could not be loaded")
SMOKE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SMOKE
SPEC.loader.exec_module(SMOKE)


def main() -> None:
    browser = SMOKE.browser_path("chrome")
    if not browser:
        raise RuntimeError("Chrome for Testing or Chrome executable not found; set LEARNNOTE_E2E_BROWSER")
    python = SMOKE.project_python()
    data_root = Path(os.getenv("LEARNNOTE_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
    log_dir = data_root / "test-runs" / "document-encoding-logs"
    profile_root = data_root / "browser-profiles" / "document-encoding"
    profile_root.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix="learnnote-document-encoding-", dir=str(profile_root)))
    fixture_dir = data_root / "test-runs" / "document-encoding-inputs"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fd, sample_name = tempfile.mkstemp(prefix="course-gb18030-", suffix=".txt", dir=str(fixture_dir))
    sample_path = Path(sample_name)
    sample = "# 编码导入验收\n\n这份资料用 GB18030 编码保存，导入后需要完整显示中文段落。\n\n研究人员应按原始记录核对数值和结论。\n"
    with os.fdopen(fd, "wb") as output:
        output.write(sample.encode("gb18030"))

    backend_port = SMOKE.free_port()
    debug_port = SMOKE.free_port()
    app_url = f"http://127.0.0.1:{backend_port}/"
    backend_process = None
    browser_process = None
    page_cdp = None
    try:
        backend_process = SMOKE.start_process(
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
            cwd=ROOT / "backend",
            log_path=log_dir / "encoding-backend.log",
        )
        health = SMOKE.wait_for_json(f"http://127.0.0.1:{backend_port}/health")
        if health.get("service") != "learnnote":
            raise RuntimeError(f"isolated LearnNote backend was not ready: {health}")

        browser_process = SMOKE.start_process([
            str(browser),
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={debug_port}",
            "--no-first-run",
            "--disable-first-run-ui",
            "--new-window",
            app_url,
        ], cwd=ROOT, log_path=log_dir / "encoding-browser.log")
        SMOKE.wait_for_debug(debug_port)
        target = SMOKE.wait_for_page_target(debug_port, app_url)
        page_cdp = SMOKE.CdpWebSocket(target["webSocketDebuggerUrl"])
        page_cdp.call("Runtime.enable")
        page_cdp.call("DOM.enable")

        ready = SMOKE.eval_page(page_cdp, """(() => ({
          title: document.title,
          create: Boolean(document.querySelector('#welcomeNew')),
          form: Boolean(document.querySelector('#createForm'))
        }))()""")
        if not ready.get("create") or not ready.get("form"):
            raise RuntimeError(f"LearnNote first-run workspace did not render: {ready}")
        SMOKE.eval_page(page_cdp, """(() => {
          document.querySelector('#welcomeNew').click();
          document.querySelector('[data-input="file"]').click();
          return { opened: document.querySelector('#createDialog').open };
        })()""")
        document = page_cdp.call("DOM.getDocument", {"depth": 1, "pierce": True})["root"]
        file_node = page_cdp.call("DOM.querySelector", {"nodeId": document["nodeId"], "selector": "#file"}).get("nodeId")
        if not file_node:
            raise RuntimeError("workspace local-file input was not found")
        page_cdp.call("DOM.setFileInputFiles", {"nodeId": file_node, "files": [str(sample_path)]})
        state = SMOKE.eval_page(page_cdp, """(() => {
          const file = document.querySelector('#file');
          file.dispatchEvent(new Event('change', { bubbles: true }));
          return {
            fileName: file.files?.[0]?.name || '',
            encodingVisible: !document.querySelector('#materialEncodingChoice').hidden
          };
        })()""")
        if state.get("fileName") != sample_path.name or not state.get("encodingVisible"):
            raise RuntimeError(f"manual encoding choice did not appear for a text document: {state}")
        SMOKE.eval_page(page_cdp, """(() => {
          const select = document.querySelector('#materialEncoding');
          select.value = 'gb18030';
          select.dispatchEvent(new Event('change', { bubbles: true }));
          document.querySelector('#createSubmit').click();
          return { submitted: true };
        })()""")

        deadline = time.time() + 40
        latest: dict = {}
        while time.time() < deadline:
            latest = SMOKE.eval_page(page_cdp, """(() => ({
              dialogOpen: document.querySelector('#createDialog')?.open || false,
              status: document.querySelector('#createStatus')?.textContent || '',
              document: document.querySelector('#document')?.innerText || '',
              provenance: document.querySelector('.encoding-provenance-note')?.innerText || ''
            }))()""")
            if "GB18030" in latest.get("provenance", "") and "原始文件已保留" in latest.get("provenance", ""):
                break
            if not latest.get("dialogOpen") and "编码导入验收" in latest.get("document", ""):
                break
            time.sleep(0.25)
        full_text = latest.get("document", "")
        provenance = latest.get("provenance", "")
        if "这份资料用 GB18030 编码保存，导入后需要完整显示中文段落。" not in full_text:
            raise RuntimeError(f"imported material did not preserve Chinese text: {latest}")
        if "gb18030" not in provenance.lower() or "手动选择" not in provenance:
            raise RuntimeError(f"decoding provenance was not shown in the material reader: {latest}")
        print(f"PASS default workspace GB18030 import: material text and decoding provenance visible; profile={profile_dir}")
    finally:
        if page_cdp:
            page_cdp.close()
        SMOKE.stop_process(browser_process)
        shutil.rmtree(profile_dir, ignore_errors=True)
        SMOKE.stop_process(backend_process)


if __name__ == "__main__":
    main()
