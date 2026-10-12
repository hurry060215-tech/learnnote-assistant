/* Run only against the caller's isolated CI service and synthetic fixture IDs. */
const assert = require("node:assert/strict");
module.exports = async function ({page, api, openStudio, evidence, cards, capture}) {
  const quote = "Learning rate controls the parameter update step and influences convergence speed.";
  const card = (await api("/api/study/cards", {method: "POST", data: {cards: [{front: "What controls the update step?", back: quote, source_evidence_ids: [evidence.evidence_id]}]}})).cards[0];
  const base = `/api/study/cards/${card.card_id}`;
  const attempts = async () => (await api("/api/study/export")).quiz_attempts.filter(item => item.card_id === card.card_id);
  const close = async () => { if (await page.locator("#reviewDialog").evaluate(el => el.open)) await page.locator("#reviewDialog [data-close]").click(); };
  const open = async () => { await openStudio(); await page.locator('[data-action="start-review"]').click(); };
  const input = page.locator("#reviewQuiz input"), submit = page.locator("#reviewQuiz .quiz-answer-form button");
  const status = page.locator('#reviewQuiz [role="status"]');
  const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
  let delayedGet, delayedAnswer;
  try {
    // The surrounding acceptance fixture owns these cards. Keep this run scoped
    // to its synthetic course and restore all statuses in finally.
    for (const item of cards) await api(`/api/study/cards/${item.card_id}`, {method: "PATCH", data: {status: "suspended"}});
    await open(); await input.waitFor();
    assert.equal((await attempts()).length, 0);
    assert.equal(await page.locator("#reviewContent h3").isVisible(), false, "Cloze term must not be leaked through the recall heading");
    await input.fill("Wrong term");
    const answered = page.waitForResponse(response => response.url().endsWith(base + "/answer"));
    await page.locator("#reviewQuiz form").evaluate(form => { form.dispatchEvent(new Event("submit", {cancelable: true})); form.dispatchEvent(new Event("submit", {cancelable: true})); });
    assert.equal((await answered).status(), 200);
    await status.filter({hasText: /填空未匹配原文/}).waitFor();
    assert.equal((await attempts()).length, 1);
    await capture("objective-cloze-result", "#reviewDialog");
    await page.locator("#reviewQuiz").getByText("回原文核对", {exact: true}).click();
    await page.locator(`#sourceContent [data-evidence-id="${evidence.evidence_id}"]`).waitFor({state: "visible"});
    await page.locator("#closeSource").click();

    // A received-but-lost response must retry the same saved attempt.
    let drop = true;
    const loseResponse = async route => { const response = await route.fetch(); if (drop) { drop = false; await route.abort("failed"); } else await route.fulfill({response}); };
    await page.route("**" + base + "/answer", loseResponse);
    await open(); await input.fill("  LEARNING  rate  "); await submit.click();
    await submit.filter({hasText: "重试此次作答"}).waitFor();
    assert.equal((await attempts()).length, 2);
    await submit.click(); await status.filter({hasText: /填空正确/}).waitFor();
    assert.equal((await attempts()).length, 2);
    await page.unroute("**" + base + "/answer", loseResponse);
    await close();

    // An older GET released after close/reopen cannot replace the newer input.
    delayedGet = deferred(); const getStarted = deferred(); let holdGet = true;
    const delayQuestion = async route => { const response = await route.fetch(); if (holdGet) { holdGet = false; getStarted.resolve(); await delayedGet.promise; } await route.fulfill({response}); };
    await page.route("**" + base + "/quiz", delayQuestion);
    await open(); await getStarted.promise; await close(); await open();
    await input.fill("new draft");
    const oldGetResponse = page.waitForResponse(response => response.url().endsWith(base + "/quiz"));
    delayedGet.resolve(); await oldGetResponse;
    assert.equal(await input.inputValue(), "new draft");
    await page.unroute("**" + base + "/quiz", delayQuestion);

    // The submitted action persists if the user closes while its reply is pending;
    // that reply must not change the newly opened review session.
    delayedAnswer = deferred(); const answerSaved = deferred();
    const delayAnswer = async route => { const response = await route.fetch(); answerSaved.resolve(); await delayedAnswer.promise; await route.fulfill({response}); };
    await page.route("**" + base + "/answer", delayAnswer);
    await submit.click(); await answerSaved.promise; await close(); await open(); await input.fill("keep new session");
    const oldAnswerResponse = page.waitForResponse(response => response.url().endsWith(base + "/answer"));
    delayedAnswer.resolve(); await oldAnswerResponse;
    assert.equal(await input.inputValue(), "keep new session");
    assert.equal((await attempts()).length, 3);
    await page.unroute("**" + base + "/answer", delayAnswer);

    await page.locator("#skipReflection").click();
    assert.equal(await input.isDisabled(), true);
    const rated = page.waitForResponse(response => response.url().endsWith(base + "/review"));
    await page.locator('[data-rating="4"]').click(); assert.equal((await rated).status(), 200);
    const stored = (await api("/api/study/cards?limit=500")).cards.find(item => item.card_id === card.card_id);
    assert.equal(stored.reps, 1);
    assert.equal((await attempts()).filter(item => item.correct).length, 1);
    assert.equal((await attempts()).length, 3, "Self-rating and reveal do not invent objective attempts");
    await close(); await openStudio(); await page.locator(".study-measures").filter({hasText: /客观填空/}).waitFor();
    return {passed: true, objective_attempts: 3, exact_matches: 1, self_ratings: 1, source_jump: true, repeat_submit: true, lost_response_retry: true, close_reopen_get: true, close_reopen_post: true};
  } finally {
    delayedGet?.resolve(); delayedAnswer?.resolve();
    await page.unroute("**" + base + "/quiz"); await page.unroute("**" + base + "/answer");
    await close();
    await api(base + "?confirm=delete_card", {method: "DELETE"});
    for (const item of cards) await api(`/api/study/cards/${item.card_id}`, {method: "PATCH", data: {status: item.status}});
  }
};
