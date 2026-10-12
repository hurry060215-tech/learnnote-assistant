// Actual Edge UI with synthetic usage responses; never calls a provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function group(requests, measured, value) {
  return { requests, measured_requests: measured, total_tokens: value,
    measured_input_requests: measured, input_tokens: value === null ? null : Math.floor(value * 0.8),
    measured_output_requests: measured, output_tokens: value === null ? null : value - Math.floor(value * 0.8) };
}
function report(totals) {
  return { schema_version: 2, totals, recent: [],
    daily: totals.requests ? [{ day: '2026-10-12', ...totals }] : [],
    models: totals.requests ? [{ model: '合成验收模型', host: 'fixture.invalid', ...totals }] : [] };
}

module.exports = async function verifyUsageCoverage(page, base, out) {
  let current = report(group(2, 1, 1500)), fail = false;
  const evidence = { synthetic: true, providerCalls: 0, views: [], scenarios: [] };
  await page.route('**/api/model/usage', route => fail
    ? route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable ledger' } })
    : route.fulfill({ json: current }));
  try {
  await page.goto(base);
  await page.locator('#welcome[data-ready="true"]').waitFor();
  const cases = [
    ['partial', group(2, 1, 1500), '已记录 1,500', 1],
    ['unknown', group(2, 0, null), '未知', 0],
    ['reported-zero', group(1, 1, 0), '0', 1],
    ['empty', group(0, 0, 0), '0', 0],
    ['total-only', { ...group(1, 1, 25), input_tokens: null, output_tokens: null,
      measured_input_requests: 0, measured_output_requests: 0 }, '25', 1],
  ];
  async function capture(name, selector) {
    const layout = await page.locator(selector).evaluate(el => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, width: innerWidth, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
    });
    assert(layout.left >= 0 && layout.right <= layout.width + 1, name);
    assert(Math.abs(layout.left - (layout.width - layout.right)) <= 2, name + ' centered');
    assert(layout.scrollWidth <= layout.clientWidth + 1, name + ' no horizontal overflow');
    await page.screenshot({ path: path.join(out, name + '.png') });
    evidence.views.push({ name, ...layout });
  }
  for (const [name, totals, expected, meters] of cases) {
    current = report(totals);
    await page.locator('#profile').click();
    await page.locator('.profile-stats section').nth(1).locator('strong').getByText(expected, { exact: true }).waitFor();
    assert.equal(await page.locator('.usage-day meter').count(), meters);
    if (totals.requests) {
      await page.getByText('按模型查看', { exact: true }).click();
      assert.equal(await page.locator('#profileBody details').first().locator('strong').innerText(), expected + ' Token');
      if (meters) assert.match(await page.locator('.usage-day meter').getAttribute('aria-label'), /次有记录/);
    }
    if (name === 'total-only') assert.match(await page.locator('#profileBody').innerText(), /输入 未知.*输出 未知/);
    for (const width of [1440, 390]) {
      if (!['partial', 'unknown'].includes(name)) break;
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await capture(`usage-${name}-${width}-light`, '#profileDialog');
    }
    await page.getByRole('button', { name: '关闭个人主页' }).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.locator('#settings').click();
    await page.locator('[data-settings-section="usage"]').click();
    await page.locator('#refreshTokenUsage').click();
    await page.locator('#tokenUsageReport h3').getByText('Token 用量：' + expected, { exact: true }).waitFor();
    await page.locator('#tokenUsageReport p').filter({ hasText: totals.requests ? `总量 ${totals.measured_requests} / ${totals.requests} 次有记录` : '总量 尚无请求记录' }).waitFor();
    if (name === 'total-only') assert.match(await page.locator('#tokenUsageReport').innerText(), /输入 未知.*输出 未知/);
    if (name === 'unknown') await capture('usage-settings-unknown-1440-light', '#settingsDialog');
    await page.locator('#settingsDialog [data-close]').click();
    evidence.scenarios.push({ name, expected, meters });
  }
  current = report(group(2, 1, 1500));
  await page.locator('#theme').click();
  await page.waitForFunction(() => document.body.classList.contains('dark'));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (await page.locator('#menu').getAttribute('aria-expanded') !== 'true' && width === 390) await page.locator('#menu').click();
    await page.locator('#profile').click();
    await page.locator('.profile-stats section').nth(1).locator('strong').getByText('已记录 1,500', { exact: true }).waitFor();
    await capture(`usage-partial-${width}-dark`, '#profileDialog');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#profileDialog').evaluate(el => el.open), false);
  }
  // A failed fetch must not become zero, and explicit refresh must recover.
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  fail = true;
  await page.locator('#profile').click();
  await page.getByText('用量暂时无法读取，请刷新重试。', { exact: true }).waitFor();
  fail = false;
  await page.locator('#profileRefresh').click();
  await page.locator('.profile-stats section').nth(1).locator('strong').getByText('已记录 1,500', { exact: true }).waitFor();
  await page.keyboard.press('Escape');
  fail = true;
  await page.locator('#settings').click();
  await page.locator('[data-settings-section="usage"]').click();
  await page.locator('#refreshTokenUsage').click();
  await page.getByText('用量暂时无法读取，请点击刷新重试。', { exact: true }).waitFor();
  fail = false;
  await page.locator('#refreshTokenUsage').click();
  await page.locator('#tokenUsageReport h3').getByText('Token 用量：已记录 1,500', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await capture('usage-settings-partial-390-dark', '#settingsDialog');
  await page.locator('#settingsDialog [data-close]').click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.locator('#theme').click();
  await page.waitForFunction(() => !document.body.classList.contains('dark'));
  evidence.scenarios.push({ name: 'failure-refresh-close-reopen', passed: true });
  evidence.passed = true;
  } catch (error) { evidence.passed = false; evidence.failure = error.message; throw error; }
  finally { fs.writeFileSync(path.join(out, 'usage-coverage-report.json'), JSON.stringify(evidence, null, 2)); }
};
