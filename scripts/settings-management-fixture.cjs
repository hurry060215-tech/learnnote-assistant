// Hosted fixture navigation only. Storage also contains migration-record details.
const assert = require("node:assert/strict");

async function openDataManagement(page) {
  const management = page.locator('#settingsDialog [data-settings-page="storage"] details')
    .filter({ has: page.locator("#studyTools") });
  assert.equal(await management.count(), 1, "Exactly one storage disclosure must own the study tools");
  const summary = management.locator(":scope > summary");
  assert.equal(await summary.count(), 1);
  assert.equal((await summary.innerText()).trim(), "数据与学习管理");
  if (!await management.evaluate(node => node.open)) await summary.click();
  assert.equal(await management.evaluate(node => node.open), true);
  for (const selector of ["#studyTools", "#storageTools"]) {
    assert.equal(await management.locator(selector).count(), 1);
    assert.equal(await management.locator(selector).isVisible(), true,
      `The opened management disclosure must show ${selector}`);
  }
}

module.exports = { openDataManagement };
