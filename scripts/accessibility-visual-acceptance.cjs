const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

async function auditViewport(page, width, height, output) {
  await page.setViewportSize({ width, height });
  await page.waitForTimeout(250);
  const result = await page.evaluate(() => {
    const settings = document.querySelector("#settingsView");
    const menu = document.querySelector(".settings-menu");
    const scale = document.querySelector('[data-setting="uiScale"]');
    const focusables = [...document.querySelectorAll("button, a, input, select, textarea, [tabindex]")]
      .filter(element => !element.disabled && !element.hidden && element.getClientRects().length > 0);
    return {
      viewport: { width: innerWidth, height: innerHeight },
      lang: document.documentElement.lang,
      uiDensity: document.body.dataset.uiDensity || "",
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      bodyWidth: document.body.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      settingsVisible: Boolean(settings && !settings.hidden),
      menuWidth: menu?.getBoundingClientRect().width || 0,
      menuScrollWidth: menu?.scrollWidth || 0,
      scaleColumns: scale ? getComputedStyle(scale).gridTemplateColumns : "",
      focusableCount: focusables.length
    };
  });
  if (!result.settingsVisible) throw new Error(`Settings view is hidden at ${width}x${height}`);
  if (result.horizontalOverflow || result.menuScrollWidth > result.menuWidth + 1) {
    throw new Error(`Horizontal overflow at ${width}x${height}: ${JSON.stringify(result)}`);
  }
  await page.screenshot({ path: path.join(output, `settings-${width}x${height}-200.png`), fullPage: true });
  return result;
}

async function main() {
  const baseUrl = process.argv[2] || "http://127.0.0.1:8765/web/";
  const output = path.resolve(process.argv[3] || "build/accessibility-visual");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);
  if (await page.locator("#onboardingOverlay:not([hidden])").count()) {
    await page.locator("#skipOnboardingButton").click();
    await page.waitForTimeout(200);
  }
  await page.locator('[data-app-view="settings"]').click();
  await page.waitForTimeout(250);

  const english = await page.evaluate(() => {
    const selector = document.querySelector("#settingLocale");
    if (!selector) throw new Error("Locale selector is missing");
    selector.value = "en-US";
    selector.dispatchEvent(new Event("change", { bubbles: true }));
    return {
      lang: document.documentElement.lang,
      title: document.querySelector(".settings-header h2")?.textContent || "",
      nav: document.querySelector("#settingsNav span")?.textContent || "",
      close: document.querySelector("#settingsCloseButton")?.textContent || ""
    };
  });
  await page.waitForTimeout(200);
  if (english.lang !== "en-US" || english.title !== "Settings" || english.nav !== "Settings" || !english.close.includes("Back")) {
    throw new Error(`English locale contract failed: ${JSON.stringify(english)}`);
  }

  await page.locator('[data-setting="uiScale"] button[data-value="200"]').click();
  await page.waitForTimeout(200);
  const wide = await auditViewport(page, 1440, 900, output);
  const tablet = await auditViewport(page, 768, 1024, output);
  const mobile = await auditViewport(page, 390, 844, output);

  const keyboard = [];
  await page.locator("body").click({ position: { x: 6, y: 6 } });
  for (let i = 0; i < 12; i += 1) {
    await page.keyboard.press("Tab");
    keyboard.push(await page.evaluate(() => document.activeElement?.id || document.activeElement?.getAttribute("data-settings-tab") || document.activeElement?.tagName || ""));
  }
  if (!keyboard.length) throw new Error("Keyboard focus contract did not find focusable controls");

  const chinese = await page.evaluate(() => {
    const selector = document.querySelector("#settingLocale");
    selector.value = "zh-CN";
    selector.dispatchEvent(new Event("change", { bubbles: true }));
    return {
      lang: document.documentElement.lang,
      title: document.querySelector(".settings-header h2")?.textContent || "",
      nav: document.querySelector("#settingsNav span")?.textContent || ""
    };
  });
  if (chinese.lang !== "zh-CN" || chinese.title !== "设置" || chinese.nav !== "设置") {
    throw new Error(`Chinese locale fallback failed: ${JSON.stringify(chinese)}`);
  }
  await browser.close();
  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  process.stdout.write(JSON.stringify({ ok: true, english, chinese, wide, tablet, mobile, keyboard }));
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
