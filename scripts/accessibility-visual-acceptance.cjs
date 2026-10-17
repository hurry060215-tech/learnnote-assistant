const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

function settingsGeometry() {
  const rect = node => {
    const r = node.getBoundingClientRect(), css = getComputedStyle(node);
    return { left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height,
      clientWidth:node.clientWidth, scrollWidth:node.scrollWidth, overflowX:css.overflowX,
      overflowY:css.overflowY, display:css.display, position:css.position, widthCss:css.width,
      marginLeft:css.marginLeft, marginRight:css.marginRight, gridColumn:css.gridColumn };
  };
  const selectors = ['.app-shell', '#mainNavigation', '#settingsView', '.settings-header',
    '.settings-layout', '.settings-menu', '.settings-content', '#settingsCloseButton',
    '#saveSettingsButton', '#resetSettingsButton', '#settingLocale', '[data-setting="uiScale"]',
    '.settings-pane:not([hidden]) input[type="checkbox"]'];
  return { method:'fixed Playwright viewport and application uiScale setting; not native browser zoom',
    viewport:{width:innerWidth,height:innerHeight}, dpr:devicePixelRatio,
    cssZoom:getComputedStyle(document.body).zoom, documentZoom:getComputedStyle(document.documentElement).zoom,
    visualScale:visualViewport?.scale, uiDensity:document.body.dataset.uiDensity,
    elements:selectors.flatMap(selector => [...document.querySelectorAll(selector)].map((node,index) => {
      const geometry=rect(node), clippingAncestors=[];
      for(let parent=node.parentElement;parent;parent=parent.parentElement) {
        const value=rect(parent);
        if(['hidden','clip','auto','scroll'].includes(value.overflowX)||['hidden','clip','auto','scroll'].includes(value.overflowY))
          clippingAncestors.push({tag:parent.tagName,id:parent.id,...value});
      }
      const textRects = [];
      if (['settingsCloseButton', 'resetSettingsButton', 'saveSettingsButton'].includes(node.id)) {
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          if (!walker.currentNode.textContent.trim()) continue;
          const range = document.createRange();
          range.selectNodeContents(walker.currentNode);
          for (const r of range.getClientRects()) textRects.push({left:r.left,right:r.right,top:r.top,bottom:r.bottom});
        }
      }
      return {selector,index,...geometry, textRects, clientHeight:node.clientHeight, scrollHeight:node.scrollHeight, outsideViewportX:geometry.left < -1 || geometry.right > innerWidth+1,
        clippingAncestors};
    })) };
}

function assertSettingsContainment(geometry) {
  const required = ['#settingsCloseButton', '#saveSettingsButton', '#settingLocale', '[data-setting="uiScale"]'];
  for (const selector of required) {
    if (!geometry.elements.some(element => element.selector === selector && element.width > 0 && element.height > 0)) {
      throw new Error(`Missing visible settings control: ${selector}`);
    }
  }
  const controls = geometry.elements.filter(element =>
    (required.includes(element.selector) || element.selector.includes('input[type="checkbox"]')) &&
    element.width > 0 && element.height > 0);
  for (const element of controls) {
    const clipped = element.clippingAncestors.some(parent =>
      ['hidden', 'clip', 'auto', 'scroll'].includes(parent.overflowX) &&
      (element.left < parent.left - 1 || element.right > parent.right + 1));
    if (element.outsideViewportX || clipped) {
      throw new Error(`Settings control horizontally clipped: ${element.selector} at app scale ${geometry.uiDensity}: ${JSON.stringify(element)}`);
    }
  }
}

function assertSettingsButtonLabels(geometry) {
  for (const selector of ['#settingsCloseButton', '#resetSettingsButton', '#saveSettingsButton']) {
    const button = geometry.elements.find(element => element.selector === selector);
    if (!button || button.width <= 0 || button.height < 44 || !button.textRects?.length)
      throw new Error(`Missing readable settings button: ${selector}`);
    for (const text of button.textRects) {
      if (text.left < button.left - 1 || text.right > button.right + 1 ||
          text.top < button.top - 1 || text.bottom > button.bottom + 1)
        throw new Error(`Settings button text escapes its box: ${selector}: ${JSON.stringify(button)}`);
    }
  }
}

async function captureMobileSettings(page, output, scale) {
  const keyboard = [];
  for (const [view, selector] of [['header', '#settingsCloseButton'], ['footer', '#resetSettingsButton']]) {
    await page.locator(selector).evaluate(element => element.scrollIntoView({block: 'center'}));
    await page.locator(selector).focus();
    await page.keyboard.press('Tab');
    const next = await page.evaluate(() => document.activeElement?.id || document.activeElement?.getAttribute('data-settings-tab'));
    if (view === 'footer' && next !== 'saveSettingsButton') throw new Error('Reset must reach Save with Tab');
    await page.keyboard.press('Shift+Tab');
    if (!await page.locator(selector).evaluate(element => element === document.activeElement))
      throw new Error(`Settings keyboard focus did not return: ${selector}`);
    const geometry = await page.evaluate(settingsGeometry);
    fs.writeFileSync(path.join(output, `settings-390x844-${scale}-${view}-geometry.json`), JSON.stringify(geometry,null,2));
    assertSettingsButtonLabels(geometry);
    const targetVisible = await page.locator(selector).evaluate(element => {
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
      return rect.top >= 0 && rect.bottom <= innerHeight && (hit === element || element.contains(hit));
    });
    if (!targetVisible) throw new Error(`Settings focused control is obscured: ${selector}`);
    await page.screenshot({path:path.join(output, `settings-390x844-${scale}-${view}.png`), fullPage:false});
    keyboard.push({view,next,returned:selector});
  }
  return keyboard;
}

async function auditViewport(page, width, height, output, scale = 200) {
  await page.setViewportSize({ width, height });
  await page.waitForTimeout(250);
  const geometry = await page.evaluate(settingsGeometry);
  fs.writeFileSync(path.join(output, `settings-${width}x${height}-${scale}-geometry.json`), JSON.stringify(geometry, null, 2));
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
  assertSettingsContainment(geometry);
  if (width === 390) assertSettingsButtonLabels(geometry);
  await page.screenshot({ path: path.join(output, `settings-${width}x${height}-${scale}.png`), fullPage: true });
  if (width === 390) result.buttonKeyboard = await captureMobileSettings(page, output, scale);
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
  await page.waitForLoadState("load");
  const stylesheets = await page.evaluate(() => [...document.styleSheets]
    .filter(sheet => sheet.href)
    .map(sheet => ({ path: new URL(sheet.href).pathname, ruleCount: sheet.cssRules.length })));
  const expectedStyles = ["styles.css", "classic-workbench-overrides.css", "classic-workbench.css", "classic-interactions.css", "classic-study.css", "workspace.css", "product.css", "mature.css", "editorial.css", "experience.css"];
  if (JSON.stringify(stylesheets.map(sheet => sheet.path)) !== JSON.stringify(expectedStyles.map(name => `/web/${name}`)) || stylesheets.some(sheet => !sheet.ruleCount)) {
    throw new Error(`Classic stylesheets failed to load in cascade order: ${JSON.stringify(stylesheets)}`);
  }
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
      close: document.querySelector("#settingsCloseButton")?.textContent || "",
      workspaceTitle: document.querySelector("#editorialHomeTitle")?.textContent || ""
    };
  });
  await page.waitForTimeout(200);
  if (english.lang !== "en-US" || english.title !== "Settings" || english.nav !== "Settings" || !english.close.includes("Back") || english.workspaceTitle !== "Start with one source") {
    throw new Error(`English locale contract failed: ${JSON.stringify(english)}`);
  }

  await page.locator('[data-setting="uiScale"] button[data-value="100"]').click();
  const baseline = [];
  for (const [width,height] of [[1440,900],[768,1024],[390,844]])
    baseline.push(await auditViewport(page,width,height,output,100));
  await page.locator('[data-setting="uiScale"] button[data-value="200"]').click();
  await page.waitForTimeout(200);
  const wide = await auditViewport(page, 1440, 900, output);
  const tablet = await auditViewport(page, 768, 1024, output);
  const mobile = await auditViewport(page, 390, 844, output);

  const tabletBoundaries = [];
  for (const scale of [100, 200]) {
    await page.locator(`[data-setting="uiScale"] button[data-value="${scale}"]`).click();
    for (const width of [681, 900]) tabletBoundaries.push(await auditViewport(page, width, 1024, output, scale));
  }
  await page.setViewportSize({ width: 390, height: 844 });

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
      nav: document.querySelector("#settingsNav span")?.textContent || "",
      workspaceTitle: document.querySelector("#editorialHomeTitle")?.textContent || ""
    };
  });
  if (chinese.lang !== "zh-CN" || chinese.title !== "设置" || chinese.nav !== "设置" || chinese.workspaceTitle !== "从一段内容开始") {
    throw new Error(`Chinese locale fallback failed: ${JSON.stringify(chinese)}`);
  }
  await browser.close();
  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  process.stdout.write(JSON.stringify({ ok: true, stylesheets, english, chinese, baseline, wide, tablet, mobile, tabletBoundaries, keyboard }));
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
