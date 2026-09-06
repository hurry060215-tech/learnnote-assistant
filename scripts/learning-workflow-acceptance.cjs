const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const base = process.argv[2] || "http://127.0.0.1:8765/";
  const output = path.resolve(process.argv[3] || "build/learning-ui");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, timezoneId: "Asia/Shanghai" });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(base, { waitUntil: "networkidle" });
    if (await page.locator("#skipOnboardingButton").isVisible()) await page.locator("#skipOnboardingButton").click();
    if (await page.locator("#confirmReleaseNotesButton").isVisible()) await page.locator("#confirmReleaseNotesButton").click();
    await page.request.put(new URL("/api/study/plan", base).href, { data: { paused: false, daily_target: 10, timezone: "Asia/Shanghai" } });
    const text = "# 回归讲义\n\n学习率决定每一步参数更新的步长，并影响收敛速度。\n\n```python\n# preserve code\nprint(1)\n```\n\n" + Array.from({ length: 105 }, (_, index) => `第${index+1}段：资料必须可以完整阅读，不能静默截断。MARKER_${index+1}`).join("\n\n");
    const response = page.waitForResponse(result => result.url().endsWith("/api/library/materials/import") && result.request().method() === "POST");
    const chooser = page.waitForEvent("filechooser");
    await page.locator("#editorialKnowledgeImport").click();
    await (await chooser).setFiles({ name: "learning-regression.md", mimeType: "text/markdown", buffer: Buffer.from(text) });
    assert.equal((await response).status(), 200);
    await page.waitForSelector(".material-reader pre code");
    assert.match(await page.locator(".material-reader pre code").innerText(), /# preserve code\nprint\(1\)/);
    while (await page.locator(".material-load-more").count()) await page.locator(".material-load-more").click();
    assert.match(await page.locator(".material-reader").innerText(), /MARKER_105/);
    const contrast = await page.locator(".material-reader pre code").evaluate(element => {
      const luminance = value => {
        const values = value.match(/[\d.]+/g).slice(0, 3).map(Number).map(channel => channel / 255).map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
        return values[0] * .2126 + values[1] * .7152 + values[2] * .0722;
      };
      const foreground = luminance(getComputedStyle(element).color);
      const background = luminance(getComputedStyle(element.closest("pre")).backgroundColor);
      return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
    });
    assert(contrast >= 4.5, `Code contrast ${contrast}`);
    await page.screenshot({ path: path.join(output, "material-desktop.png") });
    await page.getByRole("button", { name: "生成复习卡片", exact: true }).click();
    await page.waitForSelector("#studyProposalOverlay:not([hidden])");
    await page.locator("#confirmStudyProposalButton").click();
    await page.locator('.nav-rail [data-app-view="study"]').click();
    await page.waitForSelector(".study-card");
    await page.getByRole("button", { name: "显示答案", exact: true }).click();
    assert((await page.locator(".study-answer").innerText()).length <= 360);
    await page.getByRole("button", { name: "查看原文出处", exact: true }).first().click();
    await page.waitForSelector(".source-dialog");
    await page.keyboard.press("Escape");
    const before = await page.locator("#studyViewProgressLabel").innerText();
    await page.getByRole("button", { name: "记住", exact: true }).click();
    await page.waitForFunction(value => document.querySelector("#studyViewProgressLabel").innerText !== value, before);
    await page.screenshot({ path: path.join(output, "study-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.nav-rail [data-app-view="notes"]').click();
    const geometry = await page.evaluate(() => ({ header: document.querySelector(".topbar").getBoundingClientRect().bottom, title: document.querySelector("#selectedTitle").getBoundingClientRect().top, overflow: document.documentElement.scrollWidth > innerWidth + 1 }));
    assert(!geometry.overflow && geometry.title >= geometry.header, JSON.stringify(geometry));
    await page.screenshot({ path: path.join(output, "reader-mobile.png") });
    assert.deepEqual(errors, []);
    process.stdout.write(JSON.stringify({ ok: true, contrast, geometry, errors }));
  } finally {
    await browser.close();
  }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exit(1); });
