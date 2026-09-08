const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18781";
  const out = process.argv[3] || "build/redesign-site";
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({
    ...(process.platform === "win32" ? { channel: "msedge" } : {}),
    headless: true,
  });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({
        viewport: { width, height: 960 },
        reducedMotion: "reduce",
      });
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(base);
      assert((await page.title()).includes("LearnNote"));
      await page.evaluate(() => document.fonts.ready);
      assert(
        await page.evaluate(() =>
          [...document.fonts].some(
            (font) =>
              font.family === "LearnNote Site Sans" && font.status === "loaded",
          ),
        ),
      );
      assert(await page.locator("h1").isVisible());
      assert.equal(
        await page.locator("a.button").first().getAttribute("href"),
        "https://github.com/hurry060215-tech/learnnote-assistant/releases/latest",
      );
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      );
      for (const id of ["workspace", "workflow", "privacy"]) {
        assert.equal(await page.locator(`#${id}`).count(), 1);
      }
      await page.locator("#demo-source-tab").click();
      assert(await page.locator("#demo-source").isVisible());
      assert(!(await page.locator("#demo-note").isVisible()));
      await page.locator("#demo-source-tab").press("ArrowRight");
      assert(await page.locator("#demo-outline").isVisible());
      await page.locator('[data-open-heading="points"]').click();
      assert(await page.locator("#demo-note").isVisible());
      await page.locator("#demo-note [data-open-source]").click();
      assert(await page.locator("#demo-source").isVisible());
      await page.locator("#demo-source-tab").press("Home");
      assert(await page.locator("#demo-note").isVisible());
      await page.locator("#transcription-tab").click();
      assert(await page.locator("#transcription-route").isVisible());
      await page.locator("#transcription-tab").press("ArrowLeft");
      assert(await page.locator("#caption-route").isVisible());
      await page.locator('.hero a[href="#extension"]').click();
      assert.equal(new URL(page.url()).hash, "#extension");
      assert(await page.locator("#extension").isVisible());
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: path.join(out, `site-${width}.png`),
        fullPage: true,
      });
      await page.locator('a[href="privacy.html"]').first().click();
      assert((await page.title()).includes("隐私"));
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log(
      "Site layout, typography, example tabs, keyboard navigation, processing routes, install links and privacy navigation passed",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
