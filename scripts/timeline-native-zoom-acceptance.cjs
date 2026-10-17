/* A fresh, no-extension Edge process; genuine browser zoom keys, never emulation. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { execFileSync } = require("node:child_process");
const { runNativeZoomMatrix, waitForNativePreset } = require("./timeline-native-zoom-matrix.cjs");
const { captureNativeViews } = require("./timeline-native-capture.cjs");

async function assertNativeTimelineZoom({ base, taskId, claimId, out }) {
  assert.equal(process.platform, "win32", "Native Edge zoom acceptance requires the hosted Windows runner");
  const { chromium } = require("playwright");
  const origin = new URL(base).origin;
  const server = await chromium.launchServer({ channel: "msedge", headless: false, args: ["--window-size=1440,1000"] });
  let ownedPid, browser, context, page, preparation, translationOffer, before, after, zoomCommand, report, failure;
  const unexpected = [], errors = [], captures = [], zoomCases = [];
  const nativeKey = (zoom, capturePath) => JSON.parse(execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-File", path.join(__dirname, "timeline-native-zoom.ps1"), "-OwnedBrowserPid", String(ownedPid), "-Zoom", zoom, ...(capturePath ? ["-CapturePath", capturePath] : [])], { encoding: "utf8", timeout: 15000 }));
  const metrics = () => page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
    cssZoom: getComputedStyle(document.body).zoom, documentZoom: getComputedStyle(document.documentElement).zoom,
    visualScale: visualViewport.scale, overflow: document.documentElement.scrollWidth - innerWidth }));
  const writeReport = () => fs.writeFileSync(path.join(out,"native-zoom-report.json"),JSON.stringify(report,null,2));
  const writeFailureReport = () => {
    try { writeReport(); }
    catch (error) { console.error("Native zoom diagnostic report could not be written:", error); }
  };
  try {
    ownedPid = server.process().pid;
    browser = await chromium.connect(server.wsEndpoint());
    context = await browser.newContext({ viewport: null });
    context.setDefaultTimeout(15000);
    await context.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.origin === origin || ["data:", "blob:"].includes(url.protocol)) return route.continue();
      unexpected.push(url.href); return route.abort();
    });
    page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(base); await page.locator(`[data-id="${taskId}"][data-kind="task"]`).first().click();
    const marker = page.locator(`.note-claim-marker[data-claim-id="${claimId}"]`);
    await marker.click(); await page.waitForFunction(() => document.querySelector("#player").readyState >= 1);
    await page.bringToFront(); preparation = nativeKey("prepare");
    translationOffer = nativeKey("dismiss-translation");
    nativeKey("reset"); before = await metrics();
    assert.equal(before.dpr, 1, "Owned-window capture currently requires the hosted display at 100% OS scale");
    await runNativeZoomMatrix({ page, marker, nativeKey, metrics, baseline: before, out, cases: zoomCases });
    await marker.click(); await page.waitForFunction(() => document.querySelector("#player").readyState >= 1);
    await marker.focus();
    zoomCommand = nativeKey("200");
    await page.waitForFunction(initial => Math.abs(devicePixelRatio / initial.dpr - 2) < .05 && Math.abs(innerWidth / initial.width - .5) < .03, before);
    after = await metrics();
    assert(["1", "normal"].includes(after.cssZoom)); assert(["1", "normal"].includes(after.documentZoom));
    assert.equal(after.visualScale, 1, "Native page zoom is not pinch/page-scale emulation");
    assert(after.overflow <= 2, "Native 200% zoom must reflow without horizontal overflow");
    assert.equal(await marker.evaluate(node => node === document.activeElement), true, "Native zoom keeps the source marker focused");
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => Math.abs(document.querySelector("#player").currentTime - 10) < .1);
    const cue = page.locator('#sourceContent .cue[aria-current="time"]');
    await cue.focus(); await page.keyboard.press("End");
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.match(await page.evaluate(() => document.activeElement.getAttribute("aria-label")), /^203\/203/);
    await page.keyboard.press("Home");
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.match(await page.evaluate(() => document.activeElement.getAttribute("aria-label")), /^1\/203/);
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector("#player").currentTime < .1 && !document.querySelector("#player").seeking);
    assert.equal(await page.locator("#player").evaluate(node => node.paused), true);
    assert.equal(await page.evaluate(() => document.activeElement?.dataset.cueIndex), "0");
    await captureNativeViews(page, { out, zoomed: after, nativeCapture: filename => nativeKey("capture", filename), reports: captures });
    assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
    report = {passed:true,browser:browser.version(),method:"Owned Edge window Ctrl+0 then five Ctrl+Add keys",fresh_profile:true,extensions_loaded:false,viewport_emulation:false,preparation,translation_offer:translationOffer,before,after,additional_native_zoom_cases:zoomCases,zoom_command:zoomCommand,keyboard_marker_seek:true,keyboard_virtual_cues:true,captures,visual_review_required:true,unexpected_requests:unexpected,page_errors:errors};
    writeReport();
    return report;
  } catch (error) {
    failure = error;
    await page?.screenshot({path:path.join(out,"native-zoom-failure.png")}).catch(()=>{});
    report = {passed:false,preparation,translation_offer:translationOffer,before,after,additional_native_zoom_cases:zoomCases,zoom_command:zoomCommand,captures,error:String(error),unexpected_requests:unexpected,page_errors:errors};
    writeFailureReport();
    throw error;
  } finally {
    const cleanupErrors = [];
    try { if (page && !page.isClosed()) { await page.bringToFront(); nativeKey("reset"); if (before) { const restored = await waitForNativePreset(page, metrics, before, 100); report.baseline_restored = restored; writeReport(); } } }
    catch (error) { cleanupErrors.push(`Zoom reset: ${error}`); }
    finally {
      try { await context?.close(); } catch (error) { cleanupErrors.push(`Context close: ${error}`); }
      finally {
        try { await browser?.close(); } catch (error) { cleanupErrors.push(`Browser close: ${error}`); }
        finally { await server.close().catch(error => cleanupErrors.push(`Owned server close: ${error}`)); }
      }
    }
    if (cleanupErrors.length) {
      report = {...report, passed:false, cleanup_errors:cleanupErrors};
      writeFailureReport();
      if (!failure) throw new Error(cleanupErrors.join("; "));
    }
  }
}
module.exports = { assertNativeTimelineZoom };
