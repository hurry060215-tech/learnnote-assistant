// Static public website only. No accounts, user content, downloads, or model calls.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

(async () => {
  const base = new URL(process.argv[2] || "http://127.0.0.1:18781");
  assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname),
    "Run against a loopback static fixture, not a remote or user-data service.");
  const out = path.resolve(process.argv[3] || "build/redesign-site");
  fs.mkdirSync(out, { recursive: true });
  const report = {
    source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
    scope: "Static website, synthetic educational examples, and existing outbound link destinations. External links are inspected, never opened.",
    visual_review: "Real browser PNGs for human review; geometry checks do not establish aesthetic approval.",
    reflow: "320 CSS-pixel width; equivalent to 200% scaling of a 640px layout, not native browser zoom.",
    cases: [],
  };
  const browser = await chromium.launch({
    ...(process.platform === "win32" ? { channel: "msedge" } : {}),
    headless: true,
  });
  report.browser = browser.version();
  const errors = [], externalRequests = [];
  const primaryWidths = [1440, 390];
  const legalPages = ["privacy.html", "security.html"];
  try {
    for (const width of [...primaryWidths, 1280, 768, 320]) {
      const context = await browser.newContext({
        viewport: { width, height: width < 700 ? 844 : 960 },
        reducedMotion: "reduce",
      });
      await context.route("**/*", route => {
        const request = new URL(route.request().url());
        if (request.origin !== base.origin) {
          externalRequests.push(request.origin);
          return route.abort();
        }
        return route.continue();
      });
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      page.on("pageerror", error => errors.push(error.message));
      const cdp = await context.newCDPSession(page);
      await cdp.send("DOM.enable");
      await cdp.send("CSS.enable");

      async function fonts(selectors) {
        const { root } = await cdp.send("DOM.getDocument");
        const results = [];
        for (const selector of selectors) {
          const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector });
          assert(nodeId, `Missing font sample ${selector}`);
          const actual = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
          assert(actual.fonts.some(font => font.glyphCount > 0), `No rendered glyph evidence for ${selector}`);
          results.push({ selector, computed: await page.locator(selector).first().evaluate(el => {
            const css = getComputedStyle(el);
            return { family: css.fontFamily, size: css.fontSize, weight: css.fontWeight, lineHeight: css.lineHeight };
          }), actual: actual.fonts });
        }
        return results;
      }
      async function capture(name, selector, fontSelectors = []) {
        const geometry = await page.locator(selector).evaluate(el => {
          const rect = el.getBoundingClientRect(), css = getComputedStyle(el);
          const controls = [...el.querySelectorAll("a, button")]
            .filter(node => node.getClientRects().length)
            .map(node => {
              const r = node.getBoundingClientRect();
              return { text: node.textContent.trim(), left: r.left, right: r.right, height: r.height };
            });
          return { viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
            left: rect.left, right: rect.right, textAlign: css.textAlign, controls };
        });
        await page.screenshot({ path: path.join(out, `${name}.png`), animations: "disabled" });
        assert(geometry.scrollWidth <= geometry.viewport + 1, `${name}: page overflow`);
        assert(geometry.left >= -1 && geometry.right <= geometry.viewport + 1, `${name}: clipped surface`);
        assert(Math.abs(geometry.left - (geometry.viewport - geometry.right)) <= 1,
          `${name}: unequal page gutters`);
        for (const control of geometry.controls)
          assert(control.left >= -1 && control.right <= geometry.viewport + 1,
            `${name}: clipped control ${control.text}`);
        if ([".legal-document", ".hero"].includes(selector))
          assert(["start", "left"].includes(geometry.textAlign), `${name}: prose alignment`);
        report.cases.push({ name, geometry, fonts: await fonts(fontSelectors) });
      }
      async function ready() {
        await page.waitForLoadState("load", { timeout: 15000 });
        await page.locator("h1").waitFor({ state: "visible", timeout: 15000 });
        // Legal pages have no font preload. Wait for the destination stylesheet,
        // then force its first layout before observing FontFaceSet readiness.
        // An earlier document.fonts.ready may resolve before a font is requested.
        const headingFamily = await page.locator("h1").evaluate(heading => {
          heading.getBoundingClientRect();
          return getComputedStyle(heading).fontFamily;
        });
        assert(headingFamily.startsWith('"LearnNote Site Sans"'),
          `Expected the shared website font on ${page.url()}: ${headingFamily}`);
        try {
          await page.waitForFunction(() => [...document.fonts].some(
            font => font.family === "LearnNote Site Sans" && font.status === "loaded"),
          null, { timeout: 15000 });
        } catch (error) {
          const state = await page.evaluate(() => [...document.fonts].map(font => ({
            family: font.family, status: font.status,
          })));
          throw new Error(`Self-hosted subset failed to load on ${page.url()}: ${JSON.stringify(state)}`, { cause: error });
        }
        await page.evaluate(() => document.fonts.ready);
        assert(await page.evaluate(() => [...document.fonts].some(
          font => font.family === "LearnNote Site Sans" && font.status === "loaded")), "Self-hosted subset failed to load");
        assert.equal(await page.locator("h1").count(), 1);
        assert.equal(await page.locator("html").getAttribute("lang"), "zh-CN");
        assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior), "auto");
        assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), "rgb(255, 255, 255)");
        assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()), "#303832");
      }
      async function assertTab(selector, panel) {
        assert.equal(await page.locator(selector).getAttribute("aria-selected"), "true");
        assert.equal(await page.locator(selector).getAttribute("tabindex"), "0");
        assert(await page.locator(panel).isVisible());
        const group = page.locator(selector).locator("..");
        assert.equal(await group.locator('[aria-selected="true"]').count(), 1);
        assert.equal(await group.locator('[role="tab"][tabindex="0"]').count(), 1);
      }
      await page.goto(base.href);
      assert((await page.title()).includes("LearnNote"));
      await ready();
      await capture(`site-${width}-home`, ".hero", ["#hero-title", ".hero-copy", "#demo-note h2", "#demo-note p:not(.sample-meta)"]);
      for (const id of ["workspace", "workflow", "download", "extension", "privacy"])
        assert.equal(await page.locator(`#${id}`).count(), 1);
      for (const control of await page.locator(".hero-actions a, .site-header nav a, .preview-tabs button, .route-tabs button").all()) {
        if (await control.isVisible()) assert((await control.boundingBox()).height >= 44, "Primary touch target smaller than 44px");
      }
      const localTargets = await page.locator('a[href^="#"]').evaluateAll(links => links.map(link => link.getAttribute("href")));
      for (const target of localTargets) assert.equal(await page.locator(target).count(), 1, `Broken anchor ${target}`);
      const repo = "https://github.com/hurry060215-tech/learnnote-assistant";
      assert.equal(await page.locator("#download a.button").getAttribute("href"), repo);
      assert.equal(await page.locator(".hero a.button").getAttribute("href"), repo);
      assert.equal(await page.locator("#download .all-releases").getAttribute("href"), `${repo}/releases`);
      assert.equal(await page.locator('#extension a[href*="EXTENSION_CONNECTION"]').getAttribute("href"), `${repo}/blob/main/docs/EXTENSION_CONNECTION.md`);
      assert.equal(new URL(await page.locator('#extension a[href*="chromewebstore"]').getAttribute("href")).hostname, "chromewebstore.google.com");

      // Actual keyboard focus, tab wraparound, repeated selection and source return.
      await page.keyboard.press("Tab");
      assert(await page.locator(".skip-link").evaluate(el => el === document.activeElement));
      if (primaryWidths.includes(width))
        await page.screenshot({ path: path.join(out, `site-${width}-keyboard-focus.png`) });
      await page.keyboard.press("Enter");
      assert(await page.locator("#main").evaluate(el => el === document.activeElement));
      await page.locator("#demo-source-tab").click();
      await assertTab("#demo-source-tab", "#demo-source");
      assert(!(await page.locator("#demo-note").isVisible()));
      if (primaryWidths.includes(width)) {
        await page.locator("#workspace").scrollIntoViewIfNeeded();
        await capture(`site-${width}-source`, "#workspace", ["#demo-source h2", ".sample-cue.highlighted p"]);
      }
      await page.locator("#demo-source-tab").press("ArrowRight");
      await assertTab("#demo-outline-tab", "#demo-outline");
      await page.locator('[data-open-heading="points"]').click();
      await assertTab("#demo-note-tab", "#demo-note");
      assert(await page.locator("#demo-points").evaluate(el => el === document.activeElement));
      await page.locator("#demo-note [data-open-source]").click();
      await assertTab("#demo-source-tab", "#demo-source");
      await page.locator("#demo-source-tab").press("Home");
      await assertTab("#demo-note-tab", "#demo-note");
      await page.locator("#demo-note-tab").press("ArrowLeft");
      await assertTab("#demo-outline-tab", "#demo-outline");
      await page.locator('[data-open-heading="summary"]').click();
      assert(await page.locator("#demo-summary").evaluate(el => el === document.activeElement));
      await page.locator("#demo-note-tab").click();
      await page.locator("#demo-note-tab").click();
      await assertTab("#demo-note-tab", "#demo-note");
      await page.locator("#transcription-tab").click();
      await assertTab("#transcription-tab", "#transcription-route");
      if (primaryWidths.includes(width)) {
        await page.locator("#workflow").scrollIntoViewIfNeeded();
        await capture(`site-${width}-transcription`, "#workflow");
      }
      await page.locator("#transcription-tab").press("ArrowLeft");
      await assertTab("#captions-tab", "#caption-route");
      await page.locator('.site-header a[href="#download"]').click();
      assert.equal(new URL(page.url()).hash, "#download");
      if (primaryWidths.includes(width)) await capture(`site-${width}-download`, "#download");
      await page.goBack();
      assert.notEqual(new URL(page.url()).hash, "#download");
      await page.goForward();
      assert.equal(new URL(page.url()).hash, "#download");
      await page.locator('.hero a[href="#extension"]').click();
      assert.equal(new URL(page.url()).hash, "#extension");
      await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
      if (primaryWidths.includes(width))
        await page.screenshot({ path: path.join(out, `site-${width}.png`), fullPage: true, animations: "disabled" });

      for (const filename of legalPages) {
        const legal = filename.replace(".html", "");
        const destination = new URL(filename, page.url()).href;
        await Promise.all([
          page.waitForURL(destination, { waitUntil: "load", timeout: 15000 }),
          page.locator(`a[href="${filename}"]`).first().click(),
        ]);
        await ready();
        assert((await page.title()).includes(legal === "privacy" ? "隐私" : "安全"));
        assert.equal(await page.locator(`.legal-header a[href="${legal}.html"]`).getAttribute("aria-current"), "page");
        await capture(`site-${width}-${legal}`, ".legal-document", ["h1", ".legal-lead", ".legal-document h2"]);
        if (primaryWidths.includes(width))
          await page.screenshot({ path: path.join(out, `site-${width}-${legal}-full.png`), fullPage: true });
      }
      const home = new URL("./", page.url()).href;
      await Promise.all([
        page.waitForURL(home, { waitUntil: "load", timeout: 15000 }),
        page.locator('.legal-header nav a[href="./"]').click(),
      ]);
      await ready();
      assert.equal(await page.locator("#hero-title").count(), 1);
      await context.close();
    }

    // Appearance fallbacks must retain readable content and functional downloads.
    for (const mode of ["forced-colors", "font-unavailable", "no-javascript", "normal-motion"]) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 },
        reducedMotion: mode === "normal-motion" ? "no-preference" : "reduce",
        forcedColors: mode === "forced-colors" ? "active" : "none",
        javaScriptEnabled: mode !== "no-javascript" });
      if (mode === "font-unavailable") await context.route("**/*.woff2", route => route.abort());
      const page = await context.newPage();
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(base.href);
      await page.evaluate(() => document.fonts.ready);
      assert(await page.locator("#hero-title").isVisible());
      assert.equal(await page.locator("#download a.button").getAttribute("href"), "https://github.com/hurry060215-tech/learnnote-assistant");
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${mode}: overflow`);
      if (mode === "normal-motion") {
        assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior), "smooth");
        const transition = await page.locator(".hero .button").evaluate(el => getComputedStyle(el).transitionDuration);
        assert(transition.split(",").every(value => parseFloat(value) <= 0.16), "Hover motion should remain subtle");
      }
      await page.screenshot({ path: path.join(out, `site-390-${mode}.png`), animations: "disabled" });
      report.cases.push({ name: `site-390-${mode}`, verified: "Primary heading and download destination, no horizontal overflow" });
      await context.close();
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
    report.result = "passed";
    console.log("Website home, download, extension, privacy/security, keyboard navigation, responsive/reduced-motion/fallback checks and rendered font evidence passed");
  } catch (error) {
    report.result = "failed";
    report.failure = String(error);
    throw error;
  } finally {
    fs.writeFileSync(path.join(out, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
