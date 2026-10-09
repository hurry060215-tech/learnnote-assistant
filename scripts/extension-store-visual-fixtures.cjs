/* Store artwork uses unmodified, real panel excerpts, with explicit demo disclosure. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {createHash} = require("node:crypto");

// The same authored English lesson is supplied in BOTH UI locales. Localization
// must not turn course content into translated product copy.
const STORE_FIXTURE = {
  id: "active-recall-demo-v1",
  title: "Active recall: a two-minute study routine",
  modelName: "Demo model (simulated)",
  duration: 120,
  instruction: "Keep the examples and link each key point to its source timestamp.",
  question: "How can I check what I remember before rereading?",
  answer: "Close the source, recall three ideas, then compare your answer with the original.",
  note: "# A small routine for active recall\n\n- 00:00 Close the source and write down three ideas from memory.\n- 00:40 Compare your answer with the original; mark the missing ideas.\n- 01:20 Try again tomorrow, focusing on what you missed.\n\n## Put it into practice\nExplain one idea in your own words before reopening the lesson.",
  cues: [
    {start: 0, end: 20, text: "After a short lesson, close the source and recall three ideas."},
    {start: 20, end: 40, text: "Write your answer before checking. Familiarity can feel like understanding."},
    {start: 40, end: 60, text: "Compare your answer with the original and mark the missing ideas."},
    {start: 60, end: 80, text: "Explain one idea in your own words and add a concrete example."},
    {start: 80, end: 100, text: "Try again tomorrow, starting with the points you could not recall."},
    {start: 100, end: 120, text: "Keep each source timestamp so you can revisit the explanation."}
  ],
  chapters: [{title: "Recall and compare", start: 0, end: 60}, {title: "Explain and revisit", start: 60, end: 120}]
};

const STORE_COPY = {
  "en-US": {
    locale: "ENGLISH INTERFACE",
    summary: {title: "Keep the ideas.\nKeep the source.", detail: "Read a structured note and revisit the explanation through its timestamps.", result: "NOTES · RENDERED PANEL EXCERPT"},
    transcript: {title: "Read the words.\nRevisit the moment.", detail: "Follow the original transcript and use timestamps to return to the video.", result: "SUBTITLES · RENDERED PANEL EXCERPT"},
    source: "CURRENT VIDEO · RENDERED PANEL EXCERPT",
    original: "Your course content stays in its original language.",
    requirement: "Works with the LearnNote desktop client. Note generation requires a configured model.",
    disclosure: "Separate panel views rendered in Edge, arranged for this image. Synthetic course and service replies; no model call or native extension installation."
  },
  "zh-CN": {
    locale: "简体中文界面",
    summary: {title: "留下要点，\n也留下出处。", detail: "阅读结构化笔记，点击时间戳，回到视频中的讲解。", result: "笔记 · 实际侧栏界面节选"},
    transcript: {title: "读到原文，\n回到那一刻。", detail: "按时间阅读原始字幕，通过时间戳回到视频。", result: "字幕 · 实际侧栏界面节选"},
    source: "当前视频 · 实际侧栏界面节选",
    original: "界面跟随浏览器语言，课程内容保留原文。",
    requirement: "配合 LearnNote 桌面客户端使用。生成笔记需要配置模型。",
    disclosure: "图中并列展示两处独立的侧栏视图，均由 Edge 渲染。课程与服务响应为合成示例；未调用模型，未进行原生扩展安装。"
  }
};

const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const escape = value => String(value).replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));
function pngSize(bytes) {
  assert(bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])), "Expected PNG bytes");
  assert.equal(bytes.toString("ascii", 12, 16), "IHDR");
  return {width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20)};
}
function fileEvidence(filename, bytes) {
  return {filename, sha256: sha256(bytes), ...pngSize(bytes)};
}
function verifyStoreCandidates(directory) {
  const root = fs.realpathSync(directory);
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "store-candidates.json"), "utf8"));
  const report = JSON.parse(fs.readFileSync(path.join(root, "report.json"), "utf8"));
  assert.equal(manifest.status, "candidate-unreviewed", "Keep the generated provenance unchanged; record review separately");
  assert.match(manifest.source_sha, /^[a-f0-9]{40}$/);
  assert.equal(report.source_sha, manifest.source_sha);
  assert.equal(report.passed, true, "The complete extension acceptance run must pass");
  assert.equal(report.cases.length, 18);
  const expectedCases = ["en-US", "zh-CN"].flatMap(locale => [390, 768, 1440].flatMap(width => [90, 100, 200].map(zoom => `${locale}/${width}/${zoom}`))).sort();
  assert.deepEqual(report.cases.map(item => `${item.locale}/${item.width}/${item.zoom}`).sort(), expectedCases);
  assert.equal(manifest.fixture_id, STORE_FIXTURE.id);
  assert.equal(manifest.fixture_sha256, sha256(JSON.stringify(STORE_FIXTURE)));
  assert.equal(manifest.synthetic_data, true);
  assert.equal(manifest.model_called, false);
  assert.equal(manifest.native_extension_installation_tested, false);
  assert.equal(manifest.original_content_identical_across_locales, true);
  assert.equal(manifest.assets.length, 4);
  const expected = Object.keys(STORE_COPY).flatMap(locale => ["summary", "transcript"].map(state => `store-${locale}-${state}-1280x800.png`)).sort();
  assert.deepEqual(manifest.assets.map(asset => asset.filename).sort(), expected);
  assert.deepEqual([...report.store_candidates].sort(), expected);
  const verify = evidence => {
    assert.equal(path.basename(evidence.filename), evidence.filename);
    const file = fs.realpathSync(path.join(root, evidence.filename));
    assert(file.startsWith(root + path.sep), "Capture must stay within its artifact directory");
    assert.deepEqual(fileEvidence(evidence.filename, fs.readFileSync(file)), evidence);
  };
  for (const asset of manifest.assets) {
    assert.equal(asset.filename, `store-${asset.locale}-${asset.state}-1280x800.png`);
    assert.equal(asset.width, 1280); assert.equal(asset.height, 800);
    assert.equal(asset.original_title, STORE_FIXTURE.title);
    assert.equal(asset.disclosure, STORE_COPY[asset.locale].disclosure);
    verify({filename: asset.filename, sha256: asset.sha256, width: asset.width, height: asset.height});
    assert.deepEqual(asset.captures.map(capture => capture.filename), [
      `store-source-${asset.locale}.png`, `store-result-${asset.locale}-${asset.state}.png`, `store-full-panel-${asset.locale}-${asset.state}.png`
    ]);
    for (const capture of asset.captures) verify(capture);
  }
  return {source_sha: manifest.source_sha, assets: 4, status: "bytes-verified; visual review still required"};
}
function artworkHtml(locale, state, sourceBytes, resultBytes) {
  const copy = STORE_COPY[locale], scene = copy[state];
  const source = pngSize(sourceBytes), result = pngSize(resultBytes);
  // Fit whole source/result excerpts at the same scale; never crop or stretch.
  const scale = Math.min(1, 596 / Math.max(source.width, result.width), 374 / source.height, 504 / result.height);
  assert(scale >= 0.9, "Store excerpts must remain legible; use shorter demo content instead of shrinking further");
  const picture = (bytes, size, label) => `<figure><figcaption>${escape(label)}</figcaption><img alt="${escape(label)}" width="${size.width * scale}" height="${size.height * scale}" src="data:image/png;base64,${bytes.toString("base64")}"></figure>`;
  return `<!doctype html><html lang="${locale}"><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;color:#26332c;background:#eef2eb;font-family:"Segoe UI","Microsoft YaHei",sans-serif}
    .artwork{width:1280px;height:800px;padding:32px;position:relative}
    .story{height:125px}.brand{font-size:23px;font-weight:700;margin-right:24px}.locale{font-size:12px;letter-spacing:1.5px;color:#4e6850;font-weight:700}
    h1{font-size:32px;line-height:1.22;letter-spacing:-.6px;margin:12px 0 6px}p{font-size:16px;line-height:1.6;margin:0}.original{margin-top:20px;font-weight:600}.requirement{font-size:13px;color:#50604d;margin-top:8px;max-width:530px}
    .screens{height:526px;display:grid;grid-template-columns:596px 596px;gap:24px;align-items:start}figure{margin:0}figcaption{font-size:11px;font-weight:700;letter-spacing:.6px;line-height:16px;margin:0 0 6px;color:#50604d}img{display:block;box-shadow:0 3px 16px #26332c12;outline:1px solid #d9e0d4}
    footer{position:absolute;bottom:20px;left:32px;right:32px;font-size:13px;line-height:19px;color:#4b5948;border-top:1px solid #c5d1c0;padding-top:10px}
    </style><body><main class="artwork"><section class="story"><span class="brand">LearnNote</span><span class="locale">${escape(copy.locale)}</span><h1>${escape(scene.title.replace(/\n/g, " "))}</h1><p>${escape(scene.detail)}</p></section><section class="screens"><div class="source-view">${picture(sourceBytes, source, copy.source)}<p class="original">${escape(copy.original)}</p><p class="requirement">${escape(copy.requirement)}</p></div>${picture(resultBytes, result, scene.result)}</section><footer>${escape(copy.disclosure)}</footer></main></body></html>`;
}

async function captureStoreCandidates({browser, origin, out, root, installFixtures, geometry, sourceSha}) {
  const manifest = {
    schema_version: 1, status: "candidate-unreviewed", source_sha: sourceSha,
    fixture_id: STORE_FIXTURE.id, fixture_sha256: sha256(JSON.stringify(STORE_FIXTURE)),
    browser: browser.version(), viewport: {width: 1280, height: 800},
    panel_viewport: {width: 576, height: 900}, device_scale_factor: 1,
    composition: "Two separate views: complete top-of-panel before sending, and complete result card after the synthetic task. Uniform scale at least 90%; unmodified product DOM/CSS. Full panel captures retained for review.",
    synthetic_data: true, model_called: false, native_extension_installation_tested: false,
    original_content_identical_across_locales: true, visual_review: null,
    workflow_run_url: process.env.GITHUB_ACTIONS === "true" ? `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}` : null,
    assets: []
  };
  for (const locale of Object.keys(STORE_COPY)) {
    const context = await browser.newContext({viewport: manifest.panel_viewport, deviceScaleFactor: 1, locale, reducedMotion: "reduce"});
    try {
      const page = await context.newPage(), errors = [];
      page.setDefaultTimeout(12000); page.on("pageerror", error => errors.push(error.message));
      const catalog = JSON.parse(fs.readFileSync(path.join(root, "extension", "_locales", locale.startsWith("en") ? "en" : "zh_CN", "messages.json"), "utf8"));
      await page.addInitScript(installFixtures, {locale, catalog, fixture: STORE_FIXTURE});
      await page.goto(`${origin}/extension/sidepanel.html`, {waitUntil: "domcontentloaded"});
      await page.locator("#sourcePreviewCard").waitFor({state: "visible"});
      await page.evaluate(() => __localeFixture.connect());
      await page.waitForFunction(() => __learnnoteSidepanel.getState().clientConnected && !document.querySelector("#sendButton").disabled);
      assert.equal(await page.locator("#videoTitle").innerText(), STORE_FIXTURE.title);
      assert.equal(await page.locator("html").getAttribute("lang"), locale.startsWith("en") ? "en" : "zh-CN");
      await page.locator(".brand-mark").evaluate(image => image.decode());
      await page.evaluate(() => window.scrollTo(0, 0));
      const sourceBox = await page.locator(".video-card").boundingBox();
      const sourceHeight = Math.ceil(sourceBox.y + sourceBox.height);
      assert(sourceHeight < manifest.panel_viewport.height, "Complete source frame must fit");
      const sourceFile = `store-source-${locale}.png`;
      const sourceBytes = await page.screenshot({path: path.join(out, sourceFile), clip: {x: 0, y: 0, width: manifest.panel_viewport.width, height: sourceHeight}});
      await page.locator("#sendButton").click();
      await page.locator("#quickSummaryPanel").getByText("A small routine for active recall", {exact: true}).waitFor();
      const plainNote = STORE_FIXTURE.note.replace(/^#{1,3} |^- /gm, "").replace(/\s+/g, " ").trim();
      assert.equal((await page.locator("#quickSummaryPanel").innerText()).replace(/\s+/g, " ").trim(), plainNote);
      assert.deepEqual(await page.locator("#quickTranscriptPanel .quick-transcript-cue span").allTextContents(), STORE_FIXTURE.cues.map(cue => cue.text));
      for (const state of ["summary", "transcript"]) {
        await page.locator(`[data-quick-tab="${state}"]`).click();
        await page.evaluate(() => {
          document.querySelectorAll(".quick-panel").forEach(panel => { panel.scrollTop = 0; });
          const result = document.querySelector("#quickResultCard");
          window.scrollTo(0, result.getBoundingClientRect().top + window.scrollY - 80);
        });
        const panelGeometry = await geometry(page);
        assert(panelGeometry.scrollWidth <= panelGeometry.width + 1);
        assert(panelGeometry.bodyScrollWidth <= panelGeometry.width + 1);
        assert.deepEqual(panelGeometry.overflow, []);
        const contentFits = await page.locator(`[data-quick-panel="${state}"]`).evaluate(panel => panel.scrollHeight <= panel.clientHeight + 1 && panel.scrollWidth <= panel.clientWidth + 1);
        assert(contentFits, `${locale}/${state}: the full authored result must fit without internal scrolling`);
        const resultBox = await page.locator("#quickResultCard").boundingBox();
        assert(resultBox.y >= 60 && resultBox.y + resultBox.height <= 900, "Complete result card must fit below sticky header");
        const resultFile = `store-result-${locale}-${state}.png`;
        const resultBytes = await page.locator("#quickResultCard").screenshot({path: path.join(out, resultFile)});
        const fullFile = `store-full-panel-${locale}-${state}.png`;
        await page.evaluate(() => window.scrollTo(0, 0));
        const fullBytes = await page.screenshot({path: path.join(out, fullFile), fullPage: true});
        const artwork = await context.newPage();
        await artwork.setViewportSize(manifest.viewport);
        await artwork.setContent(artworkHtml(locale, state, sourceBytes, resultBytes));
        await artwork.locator("img").evaluateAll(images => Promise.all(images.map(image => image.decode())));
        const layout = await artwork.evaluate(() => {
          const bottom = document.querySelector("footer").getBoundingClientRect().top;
          return [...document.querySelectorAll(".story,.source-view,figure")].every(element => {
            const box = element.getBoundingClientRect();
            return box.x >= 0 && box.right <= 1280 && box.y >= 0 && box.bottom <= bottom;
          }) && document.documentElement.scrollWidth === 1280 && document.documentElement.scrollHeight === 800;
        });
        assert(layout, `${locale}/${state}: all artwork content must be in frame`);
        const filename = `store-${locale}-${state}-1280x800.png`;
        const bytes = await artwork.screenshot({path: path.join(out, filename)});
        manifest.assets.push({...fileEvidence(filename, bytes), locale, state, original_title: STORE_FIXTURE.title,
          disclosure: STORE_COPY[locale].disclosure, panel_geometry: panelGeometry,
          captures: [fileEvidence(sourceFile, sourceBytes), fileEvidence(resultFile, resultBytes), fileEvidence(fullFile, fullBytes)]});
        await artwork.close();
      }
      assert.deepEqual(await page.evaluate(() => __localeFixture.unexpected), []);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  }
  fs.writeFileSync(path.join(out, "store-candidates.json"), JSON.stringify(manifest, null, 2) + "\n");
  return manifest.assets.map(asset => asset.filename);
}

module.exports = {STORE_FIXTURE, STORE_COPY, pngSize, fileEvidence, artworkHtml, captureStoreCandidates, verifyStoreCandidates};
if (require.main === module) {
  try {
    assert.equal(process.argv[2], "--verify", "Usage: node scripts/extension-store-visual-fixtures.cjs --verify <artifact-directory>");
    console.log(JSON.stringify(verifyStoreCandidates(process.argv[3])));
  } catch (error) { console.error(error); process.exitCode = 1; }
}
