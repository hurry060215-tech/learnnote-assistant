import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
const code = (await Promise.all(["community-source.js", "background-community.js"].map(name => readFile(new URL("../" + name, import.meta.url), "utf8")))).join("\n");
const context = vm.createContext({ URL, Map, Date, AbortController, setTimeout, clearTimeout });
vm.runInContext(code, context);
const canonical = context.LearnNoteCommunitySource.canonicalPage;
assert.equal(canonical("https://bilibili.com/video/BV1234567890/?token=secret&p=2#reply"), "https://www.bilibili.com/video/BV1234567890?p=2");
for (const url of ["https://www.bilibili.com.evil.test/video/BV1234567890", "http://www.bilibili.com/video/BV1234567890", "https://user:secret@www.bilibili.com/video/BV1234567890", "https://www.bilibili.com:8443/video/BV1234567890", "https://www.bilibili.com/video/BV1234567890?p=1&p=2", "https://www.bilibili.com/video/BV1234567890?p=0", "https://www.bilibili.com/video/BV1234567890?p=1000000"]) assert.equal(canonical(url), "");
function harness() {
  const site = "https://www.bilibili.com/video/BV1234567890?p=2";
  const state = { tab: { id: 7, url: site }, granted: true, enabled: true, calls: [], scripts: [], pairing: null, injection: null, snapshot: [{ kind: "comment", text: "Synthetic perspective", timestamp_seconds: null }], sequence: 0 };
  const chrome = { runtime: { id: "fixture", getURL: name => "chrome-extension://fixture/" + name }, tabs: { get: async id => { assert.equal(id, 7); if (!state.tab) throw Error("Closed"); return { ...state.tab }; } }, permissions: { contains: async () => state.granted }, scripting: { executeScript: async options => { state.scripts.push(options); assert.deepEqual(JSON.parse(JSON.stringify(options.target)), { tabId: 7, frameIds: [0] }); if (state.injection) await state.injection(options); return options.files ? [] : [{ result: { page_url: site, items: state.snapshot, truncated: false } }]; } } };
  const transport = context.LearnNoteCommunityTransport.create({ chrome, now: Date.now, setTimeout, clearTimeout, AbortController,
    pairingHeaders: async () => { if (state.pairing) await state.pairing(); return {}; },
    fetch: async (url, options) => {
      assert(url.startsWith("http://127.0.0.1:8765/api/")); assert.equal(options.redirect, "error"); state.calls.push({ url, options });
      const value = url.endsWith("/settings") ? { enabled: state.enabled } : url.endsWith("/preview") ? { preview_id: "a".repeat(64), fingerprint: "b".repeat(64), items: [{ item_id: "c".repeat(32), text: "Sanitized reviewed text", kind: "comment", timestamp_seconds: null }] } : { stored_count: 1 };
      return { ok: true, json: async () => value };
    } });
  const sender = { id: "fixture", url: chrome.runtime.getURL("sidepanel.html") };
  const message = type => ({ type, taskId: "synthetic-task", targetTabId: 7, pageUrl: site, backendUrl: "http://127.0.0.1:8765", requestId: `request-${++state.sequence}` });
  return { state, transport, sender, message, send: (type, extra = {}) => transport.handle({ ...message(type), ...extra }, sender) };
}
let h = harness();
assert.equal(h.state.calls.length, 0); assert.equal(h.state.scripts.length, 0);
const preview = await h.send("community-preview");
assert.equal(h.state.calls.length, 2); assert.equal(h.state.scripts.length, 2);
const sentPreview = JSON.parse(h.state.calls[1].options.body);
assert.deepEqual(sentPreview, { page_url: "https://www.bilibili.com/video/BV1234567890?p=2", items: h.state.snapshot });
await h.send("community-save", { previewId: preview.preview_id, fingerprint: preview.fingerprint, selectedItemIds: ["c".repeat(32)] });
assert.deepEqual(JSON.parse(h.state.calls[2].options.body), { preview_id: preview.preview_id, fingerprint: preview.fingerprint, selected_item_ids: ["c".repeat(32)] });
await assert.rejects(h.send("community-save", { previewId: preview.preview_id, fingerprint: preview.fingerprint, selectedItemIds: ["c".repeat(32)] }), /community_preview_expired/);
assert.equal(h.state.calls.length, 3);
for (const variant of ["permission", "closed", "part", "spoof", "backend", "sender", "disabled"]) {
  h = harness(); let extra = {}, sender = h.sender;
  if (variant === "permission") h.state.granted = false;
  if (variant === "closed") h.state.tab = null;
  if (variant === "part") h.state.tab.url = h.state.tab.url.replace("p=2", "p=3");
  if (variant === "spoof") h.state.tab.url = h.state.tab.url.replace("bilibili.com", "bilibili.com.evil.test");
  if (variant === "backend") extra.backendUrl = "https://model.example.com";
  if (variant === "sender") sender = { ...sender, tab: { id: 7 } };
  if (variant === "disabled") h.state.enabled = false;
  await assert.rejects(h.transport.handle({ ...h.message("community-preview"), ...extra }, sender), /community_/);
  assert.equal(h.state.scripts.length, 0, variant);
  assert.equal(h.state.calls.length, variant === "disabled" ? 1 : 0, variant);
}
for (const variant of ["navigate", "revoke-regrant", "cancel", "oversize", "empty"]) {
  h = harness();
  if (variant === "oversize") h.state.snapshot[0].text = "x".repeat(2001);
  if (variant === "empty") h.state.snapshot = [];
  const message = h.message("community-preview");
  if (variant === "navigate") h.state.injection = async () => h.transport.invalidate(7);
  if (variant === "revoke-regrant") h.state.injection = async () => h.transport.revoke();
  if (variant === "cancel") h.state.injection = async () => h.transport.handle({ type: "community-cancel", requestId: message.requestId }, h.sender);
  await assert.rejects(h.transport.handle(message, h.sender), /community_/);
  assert.equal(h.state.calls.length, 1, `${variant}: no preview POST`);
}
for (const variant of ["navigate", "permission", "task", "backend", "cancel", "empty"]) {
  h = harness(); const p = await h.send("community-preview");
  const extra = { previewId: p.preview_id, fingerprint: p.fingerprint, selectedItemIds: ["c".repeat(32)] };
  if (variant === "navigate") h.transport.invalidate(7);
  if (variant === "permission") h.transport.revoke();
  if (variant === "task") extra.taskId = "other-task";
  if (variant === "backend") extra.backendUrl = "http://localhost:8765";
  if (variant === "cancel") await h.send("community-cancel", { previewId: p.preview_id });
  if (variant === "empty") extra.selectedItemIds = [];
  await assert.rejects(h.send("community-save", extra), /community_/);
  assert.equal(h.state.calls.length, 2, `${variant}: save not sent`);
}
h = harness();
h.state.pairing = async () => h.transport.revoke();
await assert.rejects(h.send("community-preview"), /community_/);
assert.equal(h.state.calls.length, 0, "Revocation during pairing cannot be undone by regrant");
console.log("Community transport: explicit opt-in, exact identity, local-only, bounded preview, selected save and stale/cancel/revocation fail closed");
