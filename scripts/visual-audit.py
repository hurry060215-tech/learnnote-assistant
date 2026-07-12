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
    page.wait_for_timeout(4200)
    onboarding = page.locator("#onboardingOverlay:not([hidden])")
    if onboarding.count():
        page.locator("#skipOnboardingButton").click()
        page.wait_for_timeout(250)
    if page.locator("#onboardingOverlay:not([hidden])").count():
        raise RuntimeError("Onboarding overlay still intercepts the workspace after dismissal.")
    capture(page, output, "client-current-page", report, errors)
    page.evaluate("() => fetch('/api/extension/heartbeat', { method: 'POST' }).then(() => checkHealth())")
    page.wait_for_timeout(300)
    capture(page, output, "client-current-page-connected", report, errors)

    for source, name in (("url", "client-video-link"), ("local", "client-local-video")):
        page.locator(f'button[data-source="{source}"]').click()
        page.wait_for_timeout(350)
        capture(page, output, name, report, errors)

    page.locator("#settingsNav").click()
    page.wait_for_timeout(350)
    capture(page, output, "client-settings-general", report, errors)
    for setting, name in (
        ("model", "client-settings-model"),
        ("transcriber", "client-settings-transcriber"),
        ("processing", "client-settings-processing"),
        ("connection", "client-settings-connection"),
        ("privacy", "client-settings-privacy"),
    ):
        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_timeout(650)
        page.locator("#settingsNav").click()
        page.locator(f'button[data-settings-tab="{setting}"]').click()
        page.wait_for_timeout(220)
        capture(page, output, name, report, errors)

    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(650)
    page.locator("#settingsNav").click()
    page.locator('[data-setting="textSize"] button[data-value="large"]').click()
    page.locator('[data-setting="defaultSource"] button[data-value="local"]').click()
    page.locator('[data-setting="colorTheme"] button[data-value="ocean"]').click()
    page.locator("#saveSettingsButton").click()
    page.wait_for_timeout(500)
    saved_settings = page.evaluate("() => JSON.parse(localStorage.getItem('learnnote_app_settings') || '{}')")
    if saved_settings.get("textSize") != "large" or saved_settings.get("defaultSource") != "local" or saved_settings.get("colorTheme") != "ocean":
        raise RuntimeError("General settings did not persist text size, default source, and color theme.")
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    restored_state = page.evaluate("""() => ({
      textSize: document.body.dataset.textSize,
      colorTheme: document.body.dataset.colorTheme,
      activeSource: document.querySelector('button[data-source].active')?.dataset.source || '',
      saved: JSON.parse(localStorage.getItem('learnnote_app_settings') || '{}')
    })""")
    if restored_state["textSize"] != "large" or restored_state["activeSource"] != "local" or restored_state["colorTheme"] != "ocean":
        raise RuntimeError(f"Saved general settings were not restored after reload: {restored_state}")
    page.locator("#settingsNav").click()
    page.locator("#resetSettingsButton").click()
    page.wait_for_timeout(250)
    page.locator("#settingsCloseButton").click()
    page.wait_for_timeout(250)

    page.locator('[data-app-view="notes"]').click()
    page.wait_for_timeout(250)

    for tab in ("note", "transcript", "slices", "frames", "qa", "diagnostics"):
        locator = page.locator(f'button[data-tab="{tab}"]')
        if not locator.is_visible() and page.locator("#resultAdvancedMenu").count():
            page.locator("#resultAdvancedMenu").evaluate("element => element.open = true")
        if locator.is_visible():
            locator.click()
            page.locator("#resultPanel").evaluate("element => element.scrollIntoView({ block: 'start' })")
            page.wait_for_timeout(350)
            if tab == "diagnostics" and page.locator("[data-diagnostic-font-size]").count():
                page.locator("[data-diagnostic-font-size]").fill("21")
                page.locator('[data-diagnostic-density="compact"]').click()
                page.locator('[data-diagnostic-detail="full"]').click()
                page.wait_for_timeout(250)
                state = page.evaluate("""() => ({
                  font: document.querySelector('[data-diagnostic-font-size]')?.value,
                  density: document.querySelector('.diagnostic-summary-panel')?.dataset.diagnosticDensity,
                  technicalOpen: document.querySelector('.diagnostic-technical')?.open,
                  pipelineStages: document.querySelectorAll('.diagnostic-pipeline li').length
                })""")
                if state != {"font": "21", "density": "compact", "technicalOpen": True, "pipelineStages": 4}:
                    raise RuntimeError(f"Diagnostic controls did not apply correctly: {state}")
            capture(page, output, f"client-result-{tab}", report, errors)

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    page.evaluate("() => scrollTo(0, 0)")
    capture(page, output, "client-mobile", report, errors)
    page.locator("#settingsNav").click()
    page.wait_for_timeout(300)
    page.evaluate("() => scrollTo(0, 0)")
    capture(page, output, "client-settings-mobile", report, errors)
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
