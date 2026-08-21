const { chromium } = require("playwright");
const fs = require("node:fs");

async function revealWholePage(page, viewport) {
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  const step = Math.max(500, Math.round(viewport.height * .72));
  for (let y = 0; y < height; y += step) {
    await page.evaluate(value => window.scrollTo(0, value), y);
    await page.waitForTimeout(90);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(250);
}

async function auditPage(page, viewport, outputPath) {
  await page.setViewportSize(viewport);
  await page.goto(process.argv[2] || "http://127.0.0.1:8793", { waitUntil: "networkidle" });
  await page.waitForTimeout(2200);
  await revealWholePage(page, viewport);

  const audit = await page.evaluate(() => {
    const h1 = document.querySelector("h1");
    const proofs = [...document.querySelectorAll(".proof")];
    const images = [...document.querySelectorAll("main img")];
    const sectionIds = ["workflow", "product", "features", "case", "privacy", "faq", "download"];
    const revealElements = [...document.querySelectorAll(".reveal")];
    const photo = document.querySelector(".hero-photo");
    return {
      h1: h1?.textContent?.replace(/\s+/g, "").trim() || "",
      h1Size: Number.parseFloat(getComputedStyle(h1).fontSize),
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      pageHeight: document.documentElement.scrollHeight,
      navCount: document.querySelectorAll("#site-nav a").length,
      proofCount: proofs.length,
      sectionsReady: sectionIds.every(id => Boolean(document.getElementById(id))),
      imagesReady: images.length === 3 && images.every(image => image.complete && image.naturalWidth > 900),
      revealsVisible: revealElements.length >= 10 && revealElements.every(element => Number.parseFloat(getComputedStyle(element).opacity) === 1),
      downloadHref: document.querySelector("[data-release-link]")?.href || "",
      releaseText: document.querySelector("[data-release-version]")?.textContent?.trim() || "",
      noUnsafeMedia: document.querySelectorAll("video, iframe, form, canvas").length === 0,
      backgroundReady: getComputedStyle(photo).backgroundImage.includes("learnnote-fiber-wave-v2.png")
        && performance.getEntriesByType("resource").some(entry => entry.name.includes("learnnote-fiber-wave-v2.png")),
      privacyLinks: Boolean(document.querySelector('a[href="./privacy.html"]') && document.querySelector('a[href="./security.html"]')),
      copy: document.body.innerText
    };
  });

  if (audit.h1 !== "听懂每一段内容写出有依据的笔记") throw new Error(`Unexpected H1: ${audit.h1}`);
  if (audit.bodyBackground !== "rgb(0, 0, 0)") throw new Error(`Body is not pure black: ${audit.bodyBackground}`);
  if (audit.overflowX > 1) throw new Error(`Horizontal overflow at ${viewport.width}px: ${audit.overflowX}`);
  if (audit.pageHeight < viewport.height * 4.5) throw new Error(`Long-form page is too short at ${viewport.width}px: ${audit.pageHeight}`);
  if (audit.navCount !== 4 || audit.proofCount !== 3) throw new Error(`Navigation or hero proof rail is incomplete at ${viewport.width}px`);
  if (!audit.sectionsReady) throw new Error(`One or more long-form sections are missing at ${viewport.width}px`);
  if (!audit.imagesReady) throw new Error(`Product screenshots are incomplete at ${viewport.width}px`);
  if (!audit.revealsVisible) throw new Error(`Scroll-revealed content remains hidden at ${viewport.width}px`);
  if (!audit.noUnsafeMedia || !audit.backgroundReady) throw new Error(`Unsafe media or missing local background at ${viewport.width}px`);
  if (!audit.privacyLinks) throw new Error(`Privacy or security link is missing at ${viewport.width}px`);
  if (!/LearnNote-Setup-x64\.exe$/.test(audit.downloadHref)) throw new Error(`Installer link is invalid: ${audit.downloadHref}`);
  if (!/^v\d+\.\d+\.\d+$/.test(audit.releaseText)) throw new Error(`Release label is invalid: ${audit.releaseText}`);
  for (const text of ["当前页面 / 视频链接 / 本地视频", "字幕、画面和笔记", "可信度保护", "不会绕过 DRM", "常见问题"]) {
    if (!audit.copy.includes(text)) throw new Error(`Required LearnNote copy is missing: ${text}`);
  }
  if (audit.h1Size < (viewport.width >= 1000 ? 52 : 40)) throw new Error(`H1 is too small: ${audit.h1Size}`);

  await page.screenshot({ path: outputPath, fullPage: true });
  return audit;
}

async function main() {
  const output = (process.argv[3] || "D:/LearnNote/audit/site-long-form").replace(/\\/g, "/");
  const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
  const browser = await chromium.launch({ ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });

  const desktop = await auditPage(page, { width: 1440, height: 900 }, `${output}-desktop.png`);
  const mobile = await auditPage(page, { width: 390, height: 844 }, `${output}-mobile.png`);

  for (const [path, heading] of [["privacy.html", "隐私说明"], ["security.html", "安全说明"]]) {
    await page.goto(new URL(path, process.argv[2] || "http://127.0.0.1:8793").toString(), { waitUntil: "networkidle" });
    if (await page.locator("h1").textContent() !== heading) throw new Error(`${path} has an invalid heading`);
    if (await page.locator(".legal-document").count() !== 1 || !await page.locator(".legal-document").isVisible()) throw new Error(`${path} legal content is unavailable`);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(process.argv[2] || "http://127.0.0.1:8793", { waitUntil: "networkidle" });
  const menu = page.locator(".burger");
  await menu.click();
  await page.waitForTimeout(350);
  const menuState = await page.evaluate(() => {
    const nav = document.querySelector("#site-nav");
    const rect = nav?.getBoundingClientRect();
    return { expanded: document.querySelector(".burger")?.getAttribute("aria-expanded"), visible: nav && getComputedStyle(nav).visibility === "visible", fullViewport: Boolean(rect && rect.width >= innerWidth - 2 && rect.height >= innerHeight - 2) };
  });
  if (menuState.expanded !== "true" || !menuState.visible || !menuState.fullViewport) throw new Error(`Mobile menu did not open: ${JSON.stringify(menuState)}`);
  await page.keyboard.press("Escape");
  if (await menu.getAttribute("aria-expanded") !== "false") throw new Error("Escape did not close the mobile menu");

  await browser.close();
  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  process.stdout.write(JSON.stringify({ ok: true, desktop, mobile, screenshots: 2 }));
}

main().catch(error => { process.stderr.write(`${error.stack || error}\n`); process.exit(1); });
