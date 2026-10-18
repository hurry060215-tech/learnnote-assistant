// Evidence only for the exact synthetic installed-page download and destination.
// No URL, filename, path, contents, GUID or filesystem timestamp is retained.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const MAX_BYTES = 256 * 1024, MAX_COUNT = 1000;
const count = (report, key) => { if (report[key] < MAX_COUNT) report[key]++; else report.counts_capped = true; };
const size = value => Number.isSafeInteger(value) && value >= 0 ? Math.min(MAX_BYTES + 1, value) : null;

function fileObservation(expectedBytes) {
  assert(Number.isSafeInteger(expectedBytes) && expectedBytes > 0 && expectedBytes <= MAX_BYTES);
  const started = Date.now(); let previous, lastKey;
  const report = { expected_bytes: expectedBytes, outcome: 'not_checked', samples: 0,
    transitions: [], transitions_dropped: 0, last: null, unavailable: false, counts_capped: false };
  const record = item => {
    count(report, 'samples'); report.last = item;
    const key = JSON.stringify(item);
    if (key === lastKey) return;
    lastKey = key;
    if (report.transitions.length < 12) report.transitions.push({ ...item, elapsed_ms: Math.min(60000, Math.max(0, Date.now() - started)) });
    else count(report, 'transitions_dropped');
  };
  const safe = work => { try { work(); } catch { report.unavailable = true; } };
  const observation = {
    report,
    stat(stat) { safe(() => {
      const bytes = size(stat.size), regular = stat.isFile() && !stat.isSymbolicLink();
      const stamp = `${stat.size}:${stat.mtimeMs}`;
      record({ state: regular ? 'regular' : 'non_regular', bytes, bytes_capped: stat.size > MAX_BYTES + 1,
        length: bytes === null ? 'unknown' : stat.size < expectedBytes ? 'short' : stat.size === expectedBytes ? 'exact' : 'oversized',
        stable_with_previous: previous === undefined ? null : stamp === previous });
      previous = stamp;
    }); },
    error(error) { safe(() => record({ state: error?.code === 'ENOENT' ? 'missing' : error?.code === 'EBUSY' ? 'busy' : error?.code === 'EACCES' ? 'access_denied' : 'other_io_error',
      bytes: null, bytes_capped: false, length: 'unknown', stable_with_previous: null })); },
    sample(file) { try { observation.stat(fs.lstatSync(file)); } catch (error) { observation.error(error); } },
    finish(outcome) { safe(() => {
      assert(['verified', 'byte_check_failed', 'native_step_failed'].includes(outcome));
      report.outcome = outcome;
    }); },
  };
  return observation;
}

function downloadObservation(origin, clock = () => performance.now()) {
  const started = clock();
  let active, closed = false;
  const records = new Map();
  const report = { status: 'not_attached', contract: 'passive_page_download_events', setup_failure: null,
    begins: 0, progress_events: 0, ignored_events: 0, dropped_downloads: 0, invalid_events: 0,
    detach_failed: false, counts_capped: false, downloads: [],
    timeline_contract: 'parent_monotonic_receipt_order_not_native_execution_time', timeline: [], timeline_dropped: 0 };
  const stamp = (event, format = active) => {
    if (report.timeline.length >= 32) { count(report, 'timeline_dropped'); return; }
    const elapsed = Math.max(0, clock() - started);
    report.timeline.push({ format, event, elapsed_ms: Math.min(180000, Math.floor(elapsed)), time_capped: elapsed > 180000 });
  };
  const invalid = () => { count(report, 'invalid_events'); };
  return {
    report,
    active(format) { assert(['md', 'json', 'cancel'].includes(format)); active = format; },
    phase(phase) {
      if (!closed && active && ['uia-initialization', 'dialog-wait', 'dialog-capture', 'filename-host', 'filename-edit', 'save-button', 'filename-set', 'filename-focus', 'filename-select', 'filename-type', 'filename-readback', 'save-focus', 'save-invoke', 'save-completion', 'native-ready', 'action-dispatch'].includes(phase)) stamp(phase);
    },
    begin(event) {
      if (closed) return;
      count(report, 'begins');
      try {
        if (!active || typeof event.guid !== 'string' || !event.guid || event.guid.length > 128 || typeof event.url !== 'string' || event.url.length > 4096) { invalid(); return; }
        const url = new URL(event.url);
        if (url.protocol !== 'blob:' || url.origin !== origin) { count(report, 'ignored_events'); return; }
        if (records.has(event.guid)) { invalid(); return; }
        if (records.size >= 4) { count(report, 'dropped_downloads'); return; }
        const item = { format: active, expected_name_matches: active === 'cancel' ? null : event.suggestedFilename === `learnnote-diagnostics.${active}`,
          state: 'begun', received_bytes: null, total_bytes: null, bytes_capped: false };
        records.set(event.guid, item); report.downloads.push(item); stamp('download-begun');
      } catch { invalid(); }
    },
    progress(event) {
      if (closed) return;
      count(report, 'progress_events');
      try {
        const item = records.get(event.guid);
        if (!item) { count(report, 'ignored_events'); return; }
        const received = size(event.receivedBytes), total = size(event.totalBytes);
        if (!['inProgress', 'completed', 'canceled'].includes(event.state)) { invalid(); return; }
        if (received === null || total === null) invalid();
        // Chromium maps both INTERRUPTED and CANCELLED to the CDP 'canceled' value.
        if (item.state !== event.state) stamp(`download-${event.state}`, item.format);
        item.state = event.state; item.received_bytes = received; item.total_bytes = total;
        item.bytes_capped = event.receivedBytes > MAX_BYTES + 1 || event.totalBytes > MAX_BYTES + 1;
      } catch { invalid(); }
    },
    close() { closed = true; active = undefined; records.clear(); },
  };
}

async function attachDownloadObservation(page, origin, bounded) {
  const observation = downloadObservation(origin); let session, accepting = true, stage = 'attach';
  const begin = event => observation.begin(event), progress = event => observation.progress(event);
  // PageHandler emits these events after Page.enable without a download-behavior
  // override. They are deprecated, so an absent event is explicitly inconclusive.
  // https://chromium.googlesource.com/chromium/src/+/refs/heads/main/content/browser/devtools/protocol/page_handler.cc
  const detach = async target => { try { await bounded(target.detach(), 'download observer detach', 1000); }
    catch { observation.report.detach_failed = true; } };
  try {
    session = await bounded(Promise.resolve().then(() => page.context().newCDPSession(page)).then(async value => {
      if (!accepting) { await detach(value); return null; } return value;
    }), 'download observer attach', 1000);
    session.on('Page.downloadWillBegin', begin); session.on('Page.downloadProgress', progress);
    stage = 'enable'; await bounded(session.send('Page.enable'), 'download observer enable', 1000);
    observation.report.status = 'listening';
  } catch {
    observation.report.status = 'unavailable'; observation.report.setup_failure = stage;
  } finally { accepting = false; }
  return {
    ...observation,
    async close() {
      observation.close();
      if (observation.report.status === 'listening') observation.report.status = observation.report.begins ? 'events_observed' : 'no_events_observed';
      if (session) {
        try { session.off('Page.downloadWillBegin', begin); session.off('Page.downloadProgress', progress); }
        catch { observation.report.detach_failed = true; }
        await detach(session);
      }
    },
  };
}

module.exports = { fileObservation, downloadObservation, attachDownloadObservation };
