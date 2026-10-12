// Actual Edge UI, one synthetic local material, and separately reported geometry.
// Run only against the isolated fixture backend used by .github/workflows/ui-visual.yml.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

async function main() {
  const base = process.argv[2] || "http://127.0.0.1:8765";
  assert(["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname),
    "Use an isolated loopback fixture backend, never a remote or user-data server.");
  const out = path.resolve(process.argv[3] || "build/design-ui");
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({ reducedMotion: "reduce", timezoneId: "UTC" });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [], externalRequests = [];
  page.on("pageerror", error => errors.push(error.message));
  const report = {
    schema_version: 1,
    source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
    browser: browser.version(),
    data: "One synthetic Markdown material imported through the real isolated backend; list/history reads scoped to fixture responses.",
    interaction: "Actual default app and Edge clicks; no model calls, downloads, credentials, or user files.",
    screenshots: "Viewport PNGs for human visual review; not a new aesthetic approval.",
    geometry: "Explicit overflow, centering, footer, drawer-shadow, and header line checks; independent of human pixel review.",
    reference_images_reviewed: false,
    native_webview_tested: false,
    cases: [],
  };
  let material, showFixture = false;
  try {
    const response = await context.request.post(new URL("/api/library/materials/import", base).href, {
      multipart: { file: {
        name: "design-audit-synthetic.md", mimeType: "text/markdown",
        buffer: Buffer.from("# 留下自己的理解\n\n把看过的内容转成可核对的笔记。先阅读，再返回原文确认，最后写下自己的理解。\n\n## 从一个问题开始\n\n学习率控制参数更新的步长。Reading stays left aligned, with enough room for mixed Chinese and English text.\n\n### 核对来源\n\n- 找到原文依据\n- 区分事实与推断\n- 记录还没有弄清的问题\n\n## 回到自己的语言\n\n用一两句话说明你理解了什么，再补充下一步需要验证的内容。\n"),
      } },
    });
    assert(response.ok(), `Synthetic import: ${response.status()} ${await response.text()}`);
    material = (await response.json()).material;
    assert(material?.material_id);
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (url.origin !== new URL(base).origin) {
        externalRequests.push(url.origin);
        return route.abort();
      }
      if (route.request().method() !== "GET") return route.continue();
      if (url.pathname === "/api/tasks") return route.fulfill({ json: { tasks: [] } });
      if (url.pathname === "/api/library/materials")
        return route.fulfill({ json: { materials: showFixture ? [material] : [] } });
      if (url.pathname === "/api/assistant/history") return route.fulfill({ json: { items: [] } });
      return route.continue();
    });

    async function sidebar(open) {
      const expanded = await page.locator("#menu").getAttribute("aria-expanded") === "true";
      if (expanded !== open) await page.locator(expanded ? "#collapseSidebar" : "#menu").click();
      assert.equal(await page.locator("#menu").getAttribute("aria-expanded"), String(open));
    }
    async function assistantHeading(name) {
      await page.locator("#assistantPanel > header").scrollIntoViewIfNeeded();
      const heading = await page.locator("#assistantPanel > header").evaluate(header => {
        const title = header.querySelector("strong"), tag = header.querySelector(".assistant-source-tag");
        const walker = document.createTreeWalker(title, NodeFilter.SHOW_TEXT), tops = [];
        while (walker.nextNode()) {
          if (!walker.currentNode.textContent.trim()) continue;
          const range = document.createRange(); range.selectNodeContents(walker.currentNode);
          for (const rect of range.getClientRects()) tops.push(rect.top);
        }
        return { viewport: innerWidth, titleLineTops: tops,
          titleBottom: title.getBoundingClientRect().bottom, tagTop: tag.getBoundingClientRect().top,
          controls: [...header.querySelectorAll("button")].map(button => {
            const rect = button.getBoundingClientRect();
            return { id: button.id, left: rect.left, right: rect.right };
          }) };
      });
      if (heading.viewport <= 760) {
        assert(heading.titleLineTops.length > 0);
        assert(Math.max(...heading.titleLineTops) - Math.min(...heading.titleLineTops) < 1,
          `${name}: assistant title wraps`);
        assert(heading.tagTop >= heading.titleBottom, `${name}: source tag competes with title row`);
      }
      for (const button of heading.controls)
        assert(button.left >= 0 && button.right <= heading.viewport, `${name}: clipped header control ${button.id}`);
      return heading;
    }
    async function capture(name, surface) {
      await page.evaluate(() => scrollTo(0, 0));
      const geometry = await page.locator(surface).evaluate(element => {
        const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
        const workspace = document.querySelector(".workspace").getBoundingClientRect();
        const sidebar = document.querySelector("#sidebar");
        const expanded = document.querySelector("#menu").getAttribute("aria-expanded") === "true";
        const footer = sidebar.querySelector("footer").getBoundingClientRect();
        const footerControls = expanded ? [...sidebar.querySelectorAll("footer button")]
          .filter(button => button.getClientRects().length)
          .map(button => {
            const r = button.getBoundingClientRect();
            const range = document.createRange();
            range.selectNodeContents(button);
            const text = range.getBoundingClientRect();
            return { id: button.id, left: r.left, right: r.right, top: r.top, bottom: r.bottom,
              textLeft: text.left, textRight: text.right };
          }) : [];
        return {
          viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          left: rect.left, right: rect.right, textAlign: style.textAlign,
          workspaceLeft: workspace.left, workspaceRight: workspace.right,
          leftGutter: rect.left - workspace.left, rightGutter: workspace.right - rect.right,
          sidebarOpen: expanded, sidebarShadow: getComputedStyle(sidebar).boxShadow,
          footerLeft: footer.left, footerRight: footer.right, footerControls,
        };
      });
      await page.screenshot({ path: path.join(out, `${name}.png`), animations: "disabled" });
      assert(geometry.scrollWidth <= geometry.viewport + 1, `${name}: page overflow`);
      assert(geometry.left >= -1 && geometry.right <= geometry.viewport + 1, `${name}: surface clipped`);
      if (surface === "#document") {
        assert(["start", "left"].includes(geometry.textAlign), `${name}: reader alignment`);
        assert(Math.abs(geometry.leftGutter - geometry.rightGutter) <= 1, `${name}: unequal reader gutters`);
      }
      if (geometry.viewport <= 760 && !geometry.sidebarOpen)
        assert.equal(geometry.sidebarShadow, "none", `${name}: hidden drawer casts a shadow`);
      for (const button of geometry.footerControls) {
        assert(button.left >= geometry.footerLeft - 1 && button.right <= geometry.footerRight + 1,
          `${name}: footer button ${button.id} out of bounds`);
        assert(button.textLeft >= button.left - 1 && button.textRight <= button.right + 1,
          `${name}: footer label ${button.id} spills outside its target`);
      }
      for (let a = 0; a < geometry.footerControls.length; a++) {
        for (let b = a + 1; b < geometry.footerControls.length; b++) {
          const one = geometry.footerControls[a], two = geometry.footerControls[b];
          const overlapX = Math.min(one.right, two.right) - Math.max(one.left, two.left);
          const overlapY = Math.min(one.bottom, two.bottom) - Math.max(one.top, two.top);
          assert(overlapX <= 0 || overlapY <= 0, `${name}: overlapping footer controls`);
        }
      }
      report.cases.push({ name, surface, geometry });
    }

    for (const width of [1280, 1440, 768, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      for (const theme of ["light", "dark"]) {
        const prefix = `${width}-${theme}`;
        showFixture = false;
        await page.goto(base);
        await page.waitForFunction(() => document.querySelector("#welcome").dataset.ready === "true");
        await sidebar(true);
        if (await page.locator("body").evaluate(body => body.classList.contains("dark")) !== (theme === "dark"))
          await page.locator("#theme").click();
        for (const open of [true, false]) {
          await sidebar(open);
          await capture(`${prefix}-home-sidebar-${open ? "open" : "closed"}`, "#welcome");
        }
        await sidebar(true);
        await page.locator("#newNote").click();
        await capture(`${prefix}-create-dialog`, "#createDialog");
        await page.locator("#createDialog [data-close]").click();
        assert.equal(await page.locator("#createDialog").evaluate(dialog => dialog.open), false);
        await page.locator("#settings").click();
        await page.locator('[data-settings-section="appearance"]').click();
        await capture(`${prefix}-settings-dialog`, "#settingsDialog");
        await page.locator("#settingsDialog [data-close]").click();
        assert.equal(await page.locator("#settingsDialog").evaluate(dialog => dialog.open), false);

        showFixture = true;
        await page.locator("#refresh").click();
        await page.locator(`[data-id="${material.material_id}"][data-kind="material"]`).first().click();
        await page.locator("#document").getByText("留下自己的理解", { exact: true }).waitFor();
        for (const open of [true, false]) {
          await sidebar(open);
          await capture(`${prefix}-reader-sidebar-${open ? "open" : "closed"}`, "#document");
        }
        await sidebar(true);
        await page.locator("#search").fill("no-such-synthetic-design-note");
        assert.equal(await page.locator("#notes [data-id]").count(), 0);
        await capture(`${prefix}-empty-search`, "#sidebar");
        await page.locator("#search").fill("");
        await sidebar(false);
        await page.locator("#aiAssistant").click();
        await page.locator(".assistant-empty").waitFor();
        const heading = await assistantHeading(prefix);
        await capture(`${prefix}-empty-assistant`, "#assistantPanel");
        report.cases.at(-1).heading = heading;
        await page.locator("#closeAssistant").click();
        assert.equal(await page.locator("#assistantPanel").isVisible(), false);
      }
    }
    // Effective 200% viewport reflow: 390x844 physical CSS area / 2. This is not
    // native browser-toolbar zoom or a desktop WebView test.
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width: 390, height: 844 });
      await sidebar(true);
      if (await page.locator("body").evaluate(body => body.classList.contains("dark")) !== (theme === "dark"))
        await page.locator("#theme").click();
      await sidebar(false);
      await page.setViewportSize({ width: 195, height: 422 });
      await page.locator("#aiAssistant").click();
      await page.locator(".assistant-empty").waitFor();
      const name = `390-effective-200-${theme}-assistant`;
      const heading = await assistantHeading(name);
      await capture(name, "#assistantPanel");
      report.cases.at(-1).heading = heading;
      report.cases.at(-1).effective_viewport = "195x422 CSS px; equivalent reflow only, not native zoom";
      // Verify the composer remains reachable when the available height is small.
      await page.locator("#aiQuestion").scrollIntoViewIfNeeded();
      await page.locator("#aiQuestion").fill("Synthetic reflow check; do not send.");
      await page.locator("#aiQuestion").fill("");
      await page.locator("#closeAssistant").click();
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
    report.passed = true;
    console.log(JSON.stringify({ passed: true, screenshots: report.cases.length, out }));
  } finally {
    report.errors = errors;
    report.external_requests = externalRequests;
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
