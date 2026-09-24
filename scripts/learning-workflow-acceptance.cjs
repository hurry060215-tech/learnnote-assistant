const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const base = process.argv[2] || "http://127.0.0.1:8765/";
  const output = path.resolve(process.argv[3] || "build/learning-ui");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, timezoneId: "Asia/Tokyo" });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(base, { waitUntil: "networkidle" });
    if (await page.locator("#skipOnboardingButton").isVisible()) await page.locator("#skipOnboardingButton").click();
    if (await page.locator("#confirmReleaseNotesButton").isVisible()) await page.locator("#confirmReleaseNotesButton").click();
    await page.locator("#settingsNav").click();
    await page.locator('[data-settings-tab="connection"]').click();
    await page.waitForFunction(() => Boolean(document.querySelector("#studyPlanTimezone")?.value));
    const initialSuggestedTimezone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
    assert.equal(initialSuggestedTimezone, "Asia/Tokyo");
    assert.equal(await page.locator("#studyPlanTimezone").inputValue(), initialSuggestedTimezone);
    await page.locator("#studyPlanTarget").fill("10");
    await page.locator("#studyPlanPaused").uncheck();
    await page.locator("#studyPlanTimezone").fill("Asia/Shanghai");
    await page.locator("#studyPlanSaveButton").focus();
    await page.keyboard.press("Enter");
    await page.getByText("学习计划已保存。", { exact: true }).waitFor();
    const savedPlan = await (await page.request.get(new URL("/api/study/plan", base).href)).json();
    assert.equal(savedPlan.plan.timezone, "Asia/Shanghai");
    assert.equal(savedPlan.plan.paused, false);
    await page.locator("#workspaceNav").click();
    const text = "# 回归讲义\n\n学习率决定每一步参数更新的步长，并影响收敛速度。\n\n```python\n# preserve code\nprint(1)\n```\n\n" + Array.from({ length: 105 }, (_, index) => `第${index+1}段：资料必须可以完整阅读，不能静默截断。MARKER_${index+1}`).join("\n\n");
    const response = page.waitForResponse(result => result.url().endsWith("/api/library/materials/import") && result.request().method() === "POST");
    const chooser = page.waitForEvent("filechooser");
    await page.locator("#editorialKnowledgeImport").click();
    await (await chooser).setFiles({ name: "learning-regression.md", mimeType: "text/markdown", buffer: Buffer.from(text) });
    const importResponse = await response;
    assert.equal(importResponse.status(), 200);
    const imported = await importResponse.json();
    assert(imported.material?.material_id, "The local Markdown import did not return a material id");
    const courseResponse = await page.request.post(new URL("/api/courses", base).href, {
      data: { title: "回归课程", sources: [{ kind: "material", id: imported.material.material_id }] },
    });
    assert.equal(courseResponse.status(), 200);
    const course = (await courseResponse.json()).course;
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
    const courseSelect = page.locator("#studyCourseSelect");
    await page.waitForFunction(id => Array.from(document.querySelector("#studyCourseSelect").options).some(option => option.value === id), course.id);
    await courseSelect.focus();
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.waitForFunction(id => document.querySelector("#studyCourseSelect").value === id, course.id);
    assert.match(await page.locator(".study-card").innerText(), /学习率决定什么/);
    await courseSelect.focus();
    await page.keyboard.press("Home");
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector("#studyCourseSelect").value === "");
    const reflection = page.getByRole("textbox", { name: "自我解释", exact: true });
    await reflection.focus();
    await page.keyboard.type("学习率改变每一步参数更新的幅度。");
    assert.equal(await reflection.inputValue(), "学习率改变每一步参数更新的幅度。");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), "记录解释并显示出处答案");
    await page.keyboard.press("Enter");
    await page.getByText("已记录自我解释动作；解释文本未保存。", { exact: true }).waitFor();
    const studyDashboard = await (await page.request.get(new URL("/api/study/dashboard", base).href)).json();
    assert((studyDashboard.progress.activity || []).some(day => day.self_assessment_count > 0), "Self-assessment was not recorded locally");
    assert((await page.locator(".study-answer").innerText()).length <= 360);
    const sourceButton = page.getByRole("button", { name: "查看原文出处", exact: true }).first();
    await sourceButton.focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector(".source-dialog");
    await page.keyboard.press("Escape");
    const before = await page.locator("#studyViewProgressLabel").innerText();
    const remembered = page.getByRole("button", { name: "记住", exact: true });
    await remembered.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(value => document.querySelector("#studyViewProgressLabel").innerText !== value, before);
    await page.screenshot({ path: path.join(output, "study-desktop.png") });

    const studyGeometry = {};
    for (const [name, width, height] of [["mobile", 390, 844], ["tablet", 768, 1024], ["desktop", 1440, 900]]) {
      await page.setViewportSize({ width, height });
      studyGeometry[name] = await page.evaluate(() => {
        const view = document.querySelector("#studyView").getBoundingClientRect();
        const card = document.querySelector(".study-card")?.getBoundingClientRect();
        return { viewportWidth: innerWidth, scrollWidth: document.documentElement.scrollWidth, viewWidth: Math.round(view.width), cardWidth: Math.round(card?.width || 0) };
      });
      assert(studyGeometry[name].scrollWidth <= width + 1, `${name} review overflows: ${JSON.stringify(studyGeometry[name])}`);
      assert(studyGeometry[name].cardWidth >= (name === "tablet" ? 500 : 280), `${name} review card is too narrow: ${JSON.stringify(studyGeometry[name])}`);
      await page.screenshot({ path: path.join(output, `study-${name}.png`) });
    }
    await page.locator('.nav-rail [data-app-view="notes"]').click();
    const geometry = {};
    for (const [name, width, height] of [["mobile", 390, 844], ["tablet", 768, 1024], ["desktop", 1440, 900]]) {
      await page.setViewportSize({ width, height });
      geometry[name] = await page.evaluate(() => {
        const box = selector => {
          const element = document.querySelector(selector);
          if (!element) return null;
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height), display: style.display, position: style.position, gridColumn: style.gridColumn, gridColumns: style.gridTemplateColumns };
        };
        return {
          viewportWidth: innerWidth,
          bodyClass: document.body.className,
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
          appShellChildren: Array.from(document.querySelector(".app-shell").children).map(element => {
            const rect = element.getBoundingClientRect(); const style = getComputedStyle(element);
            return { id: element.id, className: String(element.className), x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height), display: style.display, position: style.position, gridColumn: style.gridColumn, gridRow: style.gridRow };
          }),
          header: document.querySelector(".topbar").getBoundingClientRect().bottom,
          titleTop: document.querySelector("#selectedTitle").getBoundingClientRect().top,
          shell: box(".app-shell"), taskSidebar: box("#taskSidebar"), navigation: box(".nav-rail"), resultPanel: box("#resultPanel"),
          materialReader: box(".material-reader"), selectedTitle: box("#selectedTitle"),
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
        };
      });
      assert(!geometry[name].overflow && geometry[name].titleTop >= geometry[name].header, `${name}: ${JSON.stringify(geometry[name])}`);
      assert(geometry[name].materialReader.width >= (name === "tablet" ? 500 : 250), `${name} reader is too narrow: ${JSON.stringify(geometry[name])}`);
      await page.screenshot({ path: path.join(output, `reader-${name}.png`) });
    }

    await page.locator("#settingsNav").focus();
    await page.keyboard.press("Enter");
    await page.locator('[data-settings-tab="connection"]').focus();
    await page.keyboard.press("Enter");
    await page.locator("#studyExportButton").focus();
    const downloadEvent = page.waitForEvent("download");
    await page.keyboard.press("Enter");
    const download = await downloadEvent;
    const backupPath = path.join(output, "learning-backup.json");
    await download.saveAs(backupPath);
    assert.match(download.suggestedFilename(), /^learnnote-learning-backup-.*\.json$/);

    const clearResponse = await page.request.delete(new URL("/api/study/data?confirm=delete_all_study_data", base).href);
    assert.equal(clearResponse.status(), 200);
    assert.equal((await (await page.request.get(new URL("/api/study/cards", base).href)).json()).cards.length, 0);
    const fileChooserEvent = page.waitForEvent("filechooser");
    await page.locator("#studyRestoreButton").focus();
    await page.keyboard.press("Enter");
    const fileChooser = await fileChooserEvent;
    page.once("dialog", dialog => dialog.accept());
    await fileChooser.setFiles(backupPath);
    await page.waitForFunction(() => document.querySelector("#studyDueList")?.textContent.includes("已合并"));
    const restoredCards = (await (await page.request.get(new URL("/api/study/cards", base).href)).json()).cards;
    const restoredReviews = (await (await page.request.get(new URL("/api/study/reviews", base).href)).json()).reviews;
    assert(restoredCards.length > 0 && restoredReviews.length > 0, "Browser backup restore lost study cards or rating history");
    assert.equal((await (await page.request.get(new URL("/api/study/plan", base).href)).json()).plan.timezone, "Asia/Shanghai");
    const crossTimezonePage = await browser.newPage({ viewport: { width: 1440, height: 900 }, timezoneId: "America/New_York" });
    crossTimezonePage.on("pageerror", error => errors.push(error.message));
    await crossTimezonePage.goto(base, { waitUntil: "networkidle" });
    if (await crossTimezonePage.locator("#skipOnboardingButton").isVisible()) await crossTimezonePage.locator("#skipOnboardingButton").click();
    if (await crossTimezonePage.locator("#confirmReleaseNotesButton").isVisible()) await crossTimezonePage.locator("#confirmReleaseNotesButton").click();
    await crossTimezonePage.locator("#settingsNav").click();
    await crossTimezonePage.locator('[data-settings-tab="connection"]').click();
    await crossTimezonePage.waitForFunction(() => Boolean(document.querySelector("#studyPlanTimezone")?.value));
    const changedBrowserTimezone = await crossTimezonePage.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
    assert.equal(changedBrowserTimezone, "America/New_York");
    assert.equal(await crossTimezonePage.locator("#studyPlanTimezone").inputValue(), "Asia/Shanghai");
    process.stdout.write(JSON.stringify({ ok: true, contrast, studyGeometry, geometry, initialSuggestedTimezone, changedBrowserTimezone, preservedPlanTimezone: "Asia/Shanghai", restoredCards: restoredCards.length, restoredReviews: restoredReviews.length, errors }));
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exit(1); });
