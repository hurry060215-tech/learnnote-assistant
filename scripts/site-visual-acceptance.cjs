const { chromium } = require("playwright");

async function auditPage(page, viewport, outputPath) {
  await page.setViewportSize(viewport);
  await page.goto(process.argv[2] || "http://127.0.0.1:8793", { waitUntil: "networkidle" });
  await page.waitForTimeout(350);

  const audit = await page.evaluate(() => {
    const hero = document.querySelector(".hero");
    const workflow = document.querySelector("#workflow");
    const h1 = document.querySelector("h1");
    const heroHeading = document.querySelector(".hero h2");
    const images = [...document.querySelectorAll("main img")];
    const revealElements = [...document.querySelectorAll(".reveal")];
    const primaryDownload = document.querySelector("[data-release-link]");
    return {
      h1: h1?.textContent?.trim(),
      h1Size: Number.parseFloat(getComputedStyle(h1).fontSize),
      heroHeadingSize: Number.parseFloat(getComputedStyle(heroHeading).fontSize),
      heroBottom: hero?.getBoundingClientRect().bottom || 0,
      workflowTop: workflow?.getBoundingClientRect().top || 0,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      imagesReady: images.length === 2 && images.every(image => image.complete && image.naturalWidth > 900),
      contentVisible: revealElements.length > 0 && revealElements.every(element => Number.parseFloat(getComputedStyle(element).opacity) === 1),
      downloadHref: primaryDownload?.href || "",
      releaseText: document.querySelector("[data-release-version]")?.textContent?.trim() || ""
    };
  });

  if (audit.h1 !== "LearnNote") throw new Error(`Unexpected H1: ${audit.h1}`);
  if (audit.overflow > 1) throw new Error(`Horizontal overflow at ${viewport.width}px: ${audit.overflow}`);
  if (!audit.imagesReady) throw new Error(`Product screenshots did not load at ${viewport.width}px`);
  if (!audit.contentVisible) throw new Error(`Offscreen site content is hidden at ${viewport.width}px`);
  if (!/LearnNote-Setup-x64\.exe$/.test(audit.downloadHref)) throw new Error(`Installer link is not a release asset: ${audit.downloadHref}`);
  if (!/^v\d+\.\d+\.\d+$/.test(audit.releaseText)) throw new Error(`Invalid release label: ${audit.releaseText}`);
  if (viewport.width >= 1000 && audit.workflowTop > viewport.height + 72) {
    throw new Error(`The next section is not hinted in the desktop first viewport: ${audit.workflowTop}`);
  }
  if (audit.h1Size < (viewport.width >= 1000 ? 60 : 44)) throw new Error(`H1 is too small: ${audit.h1Size}`);
  if (audit.heroHeadingSize < (viewport.width >= 1000 ? 34 : 26)) throw new Error(`Hero heading is too small: ${audit.heroHeadingSize}`);

  await page.screenshot({ path: outputPath, fullPage: true });
  return audit;
}

async function main() {
  const output = (process.argv[3] || "D:/LearnNote/audit/site-v0130").replace(/\\/g, "/");
  const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  const desktop = await auditPage(page, { width: 1440, height: 900 }, `${output}-desktop.png`);
  const mobile = await auditPage(page, { width: 390, height: 844 }, `${output}-mobile.png`);

  const menu = page.locator(".menu-button");
  if (await menu.count() !== 1) throw new Error("Mobile menu button is missing or duplicated");
  await menu.click();
  if (!await page.locator("#siteNavigation").isVisible()) throw new Error("Mobile navigation did not open");
  if (await menu.getAttribute("aria-expanded") !== "true") throw new Error("Mobile navigation state is not exposed");

  await browser.close();
  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  process.stdout.write(JSON.stringify({ ok: true, desktop, mobile, screenshots: 2 }));
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
