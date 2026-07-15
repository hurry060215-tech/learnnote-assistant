from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def page_health(page: Page) -> dict:
    return page.evaluate(
        """() => ({
          url: location.href,
          title: document.title,
          viewport: { width: innerWidth, height: innerHeight },
          document: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
          horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          broken_images: [...document.images]
            .filter(image => {
              const rect = image.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && (!image.complete || image.naturalWidth === 0);
            })
            .map(image => ({ src: image.currentSrc || image.src, alt: image.alt })),
          clipped_controls: [...document.querySelectorAll('button, a, input, select, summary')]
            .filter(element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) return false;
              return rect.width < 20 || rect.height < 20;
            })
            .slice(0, 20)
            .map(element => ({ tag: element.tagName, text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 80) }))
        })"""
    )


def capture(page: Page, output: Path, name: str, report: list[dict], errors: list[str]) -> None:
    full_page = name.startswith("client-settings-") and (page.viewport_size or {}).get("width", 0) > 600
    page.screenshot(path=output / f"{name}.png", full_page=full_page, animations="disabled")
    state = page_health(page)
    state["name"] = name
    state["console_errors"] = list(errors)
    report.append(state)
    errors.clear()


def audit_workspace(browser, base_url: str, output: Path, report: list[dict]) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    onboarding = page.locator("#onboardingOverlay:not([hidden])")
    if onboarding.count():
        page.locator("#skipOnboardingButton").click()
        page.wait_for_timeout(250)
    if page.locator("#onboardingOverlay:not([hidden])").count():
        raise RuntimeError("Onboarding overlay still intercepts the workspace after dismissal.")
    if page.locator("#aiAssistantDrawer").is_visible():
        raise RuntimeError("AI assistant must not cover the create workspace by default.")
    capture(page, output, "client-create-1440", report, errors)

    page.set_viewport_size({"width": 1024, "height": 768})
    page.wait_for_timeout(250)
    capture(page, output, "client-create-1024", report, errors)

    page.locator('[data-app-view="notes"]').click()
    page.wait_for_timeout(450)
    tasks = page.locator("#tasks .task")
    if not tasks.count():
        raise RuntimeError("Visual audit needs at least one task in the configured D: audit data directory.")
    layout = page.evaluate("""() => {
      const task = document.querySelector('#tasks .task');
      const list = document.querySelector('#tasks');
      const nav = document.querySelector('.nav-rail');
      const before = task.getBoundingClientRect();
      const original = task.querySelector('.task-headline > strong')?.textContent || '';
      const title = task.querySelector('.task-headline > strong');
      if (title) title.textContent = '这是一个非常长的学习视频标题，用来验证不同长度字段不会撑开左侧笔记列表或改变选中框宽度';
      const after = task.getBoundingClientRect();
      if (title) title.textContent = original;
      return {
        beforeWidth: before.width,
        afterWidth: after.width,
        listWidth: list.getBoundingClientRect().width,
        navWidth: nav.getBoundingClientRect().width,
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
      };
    }""")
    if abs(layout["beforeWidth"] - layout["afterWidth"]) > 0.5 or layout["horizontalOverflow"]:
        raise RuntimeError(f"Long left-column labels changed the layout: {layout}")
    capture(page, output, "client-notes-1024", report, errors)

    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(250)
    page.locator("#openAiAssistantButton").click()
    page.wait_for_timeout(250)
    overlap = page.evaluate("""() => {
      const result = document.querySelector('.result-panel')?.getBoundingClientRect();
      const drawer = document.querySelector('#aiAssistantDrawer')?.getBoundingClientRect();
      return result && drawer ? Math.max(0, result.right - drawer.left) : 0;
    }""")
    if overlap > 1:
        raise RuntimeError(f"AI assistant overlaps the note reader by {overlap}px.")
    capture(page, output, "client-notes-ai-1440", report, errors)

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    capture(page, output, "client-mobile", report, errors)
    page.close()


def audit_site(browser, site_url: str, output: Path, report: list[dict]) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(site_url, wait_until="networkidle")
    capture(page, output, "site-desktop", report, errors)
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="networkidle")
    capture(page, output, "site-mobile", report, errors)
    page.close()


def audit_sidepanel(browser, output: Path, report: list[dict]) -> None:
    page = browser.new_page(viewport={"width": 440, "height": 900}, device_scale_factor=1)
    file_url = (ROOT / "extension" / "sidepanel.html").as_uri()
    page.goto(file_url, wait_until="domcontentloaded")
    page.wait_for_timeout(600)
    page.screenshot(path=output / "extension-sidepanel.png", full_page=False)
    state = page_health(page)
    state["name"] = "extension-sidepanel"
    state["console_errors"] = []
    report.append(state)
    page.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture and audit all LearnNote visual surfaces.")
    parser.add_argument("--client-url", default="http://127.0.0.1:8785")
    parser.add_argument("--site-url", default="http://127.0.0.1:8790")
    parser.add_argument("--skip-site", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "visual-audit")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    report: list[dict] = []
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    if not edge.exists():
        edge = Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe")
    if not edge.exists():
        raise RuntimeError("Microsoft Edge is required for the visual audit.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(edge),
            headless=True,
            args=["--disable-gpu", "--disable-gpu-compositing"],
        )
        audit_workspace(browser, args.client_url, args.output, report)
        if not args.skip_site:
            audit_site(browser, args.site_url, args.output, report)
        audit_sidepanel(browser, args.output, report)
        browser.close()

    summary = {
        "screens": len(report),
        "failures": [
            entry for entry in report
            if entry["horizontal_overflow"] or entry["broken_images"] or entry["console_errors"]
        ],
        "screenshots": report,
    }
    (args.output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"screens": summary["screens"], "failures": len(summary["failures"]), "output": str(args.output)}, ensure_ascii=False))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
