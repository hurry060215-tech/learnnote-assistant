const { chromium } = require("playwright");

async function main() {
  const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
  const output = (process.argv[3] || "D:/LearnNote/audit/visual-acceptance").replace(/\\/g, "/");
  const executablePath = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
  const browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  if (await page.locator("#onboardingOverlay:not([hidden])").count()) {
    await page.locator("#skipOnboardingButton").click();
    await page.waitForTimeout(200);
  }
  if (await page.locator("#aiAssistantDrawer").isVisible()) {
    throw new Error("AI assistant covers the create workspace by default");
  }
  const wideNavigation = await page.evaluate(() => ({
    railWidth: document.querySelector(".nav-rail")?.getBoundingClientRect().width || 0,
    visibleLabels: [...document.querySelectorAll(".nav-item span")]
      .filter(label => label.getBoundingClientRect().width > 20).length
  }));
  if (wideNavigation.railWidth < 180 || wideNavigation.visibleLabels !== 4) {
    throw new Error(`Wide navigation labels are not stable: ${JSON.stringify(wideNavigation)}`);
  }
  await page.waitForTimeout(500);
  const settledWorkflowVisible = await page.locator("#sourceWorkflow.settled").isVisible().catch(() => false);
  if (settledWorkflowVisible) {
    throw new Error("A completed historical workflow still occupies the create workspace");
  }
  await page.screenshot({ path: `${output}-create-1440.png`, omitBackground: false });

  const hasCurrentPageTask = await page.evaluate(async () => {
    const response = await fetch("/api/tasks");
    const payload = await response.json();
    return (payload.tasks || []).some(task => task.source_type === "current_page"
      && task?.selected_resource?.source !== "manual"
      && !String(task?.selected_resource?.request_type || "").startsWith("manual"));
  });
  if (hasCurrentPageTask) {
    await page.locator('#generateNoteButton').click();
    await page.waitForFunction(() => document.body.dataset.appView === "notes");
  } else {
    await page.locator('[data-app-view="notes"]').click();
  }

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForTimeout(500);
  if (!await page.locator(".queue-panel").isVisible()) {
    throw new Error("The note list is hidden when entering the note library");
  }
  const tasks = page.locator("#tasks .task");
  if (!await tasks.count()) throw new Error("No task is available for the note-list layout audit");
  if (!await tasks.first().evaluate(element => element.classList.contains("selected"))) {
    await tasks.first().evaluate(element => element.click());
  }
  await page.waitForTimeout(250);
  const layout = await page.evaluate(() => {
    const task = document.querySelector("#tasks .task");
    const title = task?.querySelector(".task-headline > strong");
    const list = document.querySelector("#tasks");
    const nav = document.querySelector(".nav-rail");
    if (!task || !title || !list || !nav) return { missing: true };
    const original = title.textContent;
    const before = task.getBoundingClientRect();
    const shortHeight = before.height;
    title.textContent = "这是一个非常长的学习视频标题，用来验证不同长度字段不会撑开左侧列表或改变整个框的宽度";
    const after = task.getBoundingClientRect();
    title.textContent = original;
    return {
      beforeWidth: before.width,
      afterWidth: after.width,
      shortHeight,
      longHeight: after.height,
      listWidth: list.getBoundingClientRect().width,
      navWidth: nav.getBoundingClientRect().width,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
    };
  });
  if (layout.missing) throw new Error("No task is available for the note-list layout audit");
  if (Math.abs(layout.beforeWidth - layout.afterWidth) > 0.5 || Math.abs(layout.shortHeight - layout.longHeight) > 0.5 || layout.horizontalOverflow) {
    throw new Error(`Long note titles changed the left-column layout: ${JSON.stringify(layout)}`);
  }
  if (Math.abs(layout.shortHeight - 84) > 0.5) {
    throw new Error(`Note rows do not keep a stable height: ${JSON.stringify(layout)}`);
  }

  await page.locator('[data-app-view="settings"]').click();
  await page.waitForTimeout(250);
  const settingsMenu = await page.evaluate(() => {
    const menu = document.querySelector('.settings-menu');
    const buttons = [...document.querySelectorAll('.settings-menu button')];
    return {
      width: menu?.getBoundingClientRect().width || 0,
      widths: buttons.map(button => button.getBoundingClientRect().width),
      heights: buttons.map(button => button.getBoundingClientRect().height)
    };
  });
  if (Math.abs(settingsMenu.width - 220) > 0.5 || settingsMenu.widths.some(width => Math.abs(width - 220) > 0.5) || settingsMenu.heights.some(height => Math.abs(height - 48) > 0.5)) {
    throw new Error(`Settings navigation changes size with label length: ${JSON.stringify(settingsMenu)}`);
  }
  await page.screenshot({ path: `${output}-settings-1024.png` });
  await page.locator('[data-app-view="notes"]').click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${output}-notes-1024.png` });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(700);
  await page.locator("#openAiAssistantButton").click();
  await page.waitForTimeout(250);
  if (!await page.locator("#aiAssistantDrawer").isVisible()) {
    throw new Error("AI assistant did not open from the note reader");
  }
  const overlap = await page.evaluate(() => {
    const result = document.querySelector(".result-panel")?.getBoundingClientRect();
    const drawer = document.querySelector("#aiAssistantDrawer")?.getBoundingClientRect();
    return result && drawer ? {
      pixels: Math.max(0, result.right - drawer.left),
      viewport: innerWidth,
      result: { left: result.left, right: result.right, width: result.width },
      drawer: { left: drawer.left, right: drawer.right, width: drawer.width },
      bodyClass: document.body.className
    } : { pixels: 0, viewport: innerWidth };
  });
  if (overlap.pixels > 1) throw new Error(`AI assistant overlaps note reader: ${JSON.stringify(overlap)}`);
  await page.screenshot({ path: `${output}-notes-ai-1440.png` });
  await browser.close();

  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  process.stdout.write(JSON.stringify({ ok: true, wideNavigation, layout, overlap, hasCurrentPageTask, screenshots: 4 }));
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
