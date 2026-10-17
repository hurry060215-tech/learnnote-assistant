// Failure evidence for the synthetic, loopback-only streaming acceptance fixture.
const fs = require('node:fs');
const path = require('node:path');
function safePath(value) {
  try {
    const url = new URL(value);
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return '[non-loopback]';
    return url.pathname.length <= 256 && /^\/(?:web\/[a-zA-Z0-9_.-]+)?$/.test(url.pathname) ? url.pathname : '[other-local-path]';
  } catch { return '[invalid-url]'; }
}
function safeError(error) {
  return String(error?.message || error).replace(/https?:\/\/[^\s"'<>]+/g, safePath).slice(0, 1500);
}
function observe(page) {
  const evidence = { page_errors: [], requests: [], failed_requests: [], bad_responses: [], dropped: { page_errors: 0, requests: 0, failed_requests: 0, bad_responses: 0 } };
  const append = (key, value) => { if (evidence[key].length < 80) evidence[key].push(value); else evidence.dropped[key]++; };
  const request = req => ({ method: req.method().slice(0, 12), path: safePath(req.url()), type: req.resourceType().slice(0, 24) });
  page.on('pageerror', error => append('page_errors', safeError(error)));
  page.on('request', req => { if (['document', 'script'].includes(req.resourceType())) append('requests', request(req)); });
  page.on('requestfailed', req => append('failed_requests', { ...request(req), error: safeError(req.failure()?.errorText || 'unknown') }));
  page.on('response', res => { if (res.status() >= 400) append('bad_responses', { ...request(res.request()), status: res.status() }); });
  return evidence;
}
async function bounded(operation, ms = 2000) {
  let timer;
  try { return await Promise.race([Promise.resolve().then(operation), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('diagnostic timeout')), ms); })]); }
  finally { clearTimeout(timer); }
}
async function captureFailure(page, evidence, error, out, write = fs.writeFileSync) {
  const report = { passed: false, failure: safeError(error), ...evidence, diagnostic_errors: [] };
  if (!page) {
    report.page_state = "not-created";
    write(path.join(out, "failure.json"), JSON.stringify(report, null, 2), "utf8");
    return report;
  }
  try {
    report.page_path = safePath(page.url());
    report.dom = await bounded(() => page.evaluate(() => ({
      ready_state: document.readyState,
      assistant_count: document.querySelectorAll('#aiAssistant').length,
      toolbar_count: document.querySelectorAll('.toolbar').length,
      module_scripts: Array.from(document.querySelectorAll('script[type="module"]')).slice(0, 20).map(el => {
        const url = new URL(el.src, location.href);
        return url.origin === location.origin && url.pathname.length <= 256 && /^\/web\/[a-zA-Z0-9_.-]+$/.test(url.pathname) ? url.pathname : '[other-script]';
      }),
    })));
  } catch (captureError) { report.diagnostic_errors.push(safeError(captureError)); }
  try { await page.screenshot({ path: path.join(out, 'failure.png'), timeout: 5000, animations: 'disabled' }); }
  catch (captureError) { report.diagnostic_errors.push(safeError(captureError)); }
  write(path.join(out, 'failure.json'), JSON.stringify(report, null, 2), 'utf8');
  return report;
}
async function runWithEvidence(action, failure, cleanups) {
  let primary;
  try { return await action(); }
  catch (error) {
    primary = error;
    try { await failure(error); } catch (diagnosticError) { console.error('Streaming diagnostic write failed:', safeError(diagnosticError)); }
    throw error;
  } finally {
    let cleanupFailure;
    for (const cleanup of cleanups) {
      try { await cleanup(); } catch (error) { cleanupFailure ||= error; console.error('Streaming fixture cleanup failed:', safeError(error)); }
    }
    if (!primary && cleanupFailure) throw cleanupFailure;
  }
}
module.exports = { safePath, observe, captureFailure, runWithEvidence };
