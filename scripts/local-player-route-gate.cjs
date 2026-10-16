// Delays real Playwright requests with one owner and bounded, observed teardown.
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
async function bounded(promise, label, timeout = 20000) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), timeout);
    })]);
  } finally { clearTimeout(timer); }
}
async function installRouteGate(page, pattern, {
  label, prepare = async () => undefined, settle = route => route.continue(),
  allowCanceled = false, onError = () => {}, onCanceled = () => {},
}) {
  const release = deferred(), reached = deferred(), failed = deferred();
  const active = new Set(), seen = new WeakSet(), failures = [];
  let finishing;
  const recordError = error => { failures.push(error); failed.resolve(error); onError(error); };
  const handler = async route => {
    if (seen.has(route)) { recordError(new Error(`${label}: duplicate route ownership`)); return; }
    seen.add(route);
    const done = deferred(); active.add(done.promise);
    try {
      const prepared = await prepare(route);
      reached.resolve();
      await release.promise;
      // This is the only call that may settle this request. Never retry it.
      await settle(route, prepared);
    } catch (error) {
      const cancellation = route.request().failure?.();
      if (allowCanceled && cancellation?.errorText === "net::ERR_ABORTED") onCanceled(cancellation.errorText);
      else recordError(error);
    } finally { active.delete(done.promise); done.resolve(); }
  };
  await page.route(pattern, handler);
  const drain = async () => { while (active.size) await Promise.all([...active]); };
  return {
    waitReached: () => bounded(Promise.race([reached.promise, failed.promise.then(error => { throw error; })]), `${label} request`),
    release: release.resolve,
    finish() {
      if (!finishing) finishing = (async () => {
        release.resolve();
        // Removing a handler while its continue/fulfill is pending can race
        // Playwright's own route fallback. Settle first, unregister second.
        await bounded(drain(), `${label} settlement`);
        await page.unroute(pattern, handler);
        await bounded(drain(), `${label} removal`);
        if (failures.length) throw failures[0];
      })();
      return finishing;
    },
  };
}
module.exports = { installRouteGate };
