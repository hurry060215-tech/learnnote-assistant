import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
const { createMaterialListing } = await import("data:text/javascript;base64," + Buffer.from(readFileSync(new URL("../material-listing.js", import.meta.url))).toString("base64"));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const result = (ids, next_cursor = "") => ({ materials: ids.map(material_id => ({ material_id })), next_cursor, has_more: Boolean(next_cursor), total: 105 });

test("unchanged polling reuses one material page and explicit pagination accumulates unique rows", async () => {
  const calls = []; let clock = 100;
  const listing = createMaterialListing({ now: () => clock, api: async path => { calls.push(path); return calls.length === 1 ? result(["a", "b"], "next") : result(["b", "c"]); } });
  const first = await listing.refresh();
  for (let i = 0; i < 6; i++) assert.equal(await listing.refresh(), first);
  assert.equal(calls.length, 1);
  const second = await listing.more();
  assert.deepEqual(second.materials.map(row => row.material_id), ["a", "b", "c"]);
  assert.match(calls[1], /cursor=next/);
  listing.invalidate(); await listing.refresh(); assert.equal(calls.length, 3);
});

test("overlapping requests share one promise and stale search replies cannot publish", async () => {
  const waiting = [];
  const listing = createMaterialListing({ api: path => { const wait = deferred(); waiting.push({ path, ...wait }); return wait.promise; } });
  const first = listing.refresh(), joined = listing.refresh(); assert.equal(first, joined);
  listing.setQuery("older title"); const next = listing.refresh();
  waiting[1].resolve(result(["old-found"])); await next;
  waiting[0].resolve(result(["wrong"])); assert.equal(await first, null);
  assert.equal(listing.value.materials[0].material_id, "old-found"); assert.match(waiting[1].path, /q=older%20title/);
});

test("failed page preserves accumulated rows and allows explicit retry", async () => {
  let fail = false;
  const listing = createMaterialListing({ api: async () => { if (fail) throw new Error("offline"); return result(["kept"], "next"); } });
  await listing.refresh(); fail = true; await assert.rejects(listing.more(), /offline/);
  assert.equal(listing.value.materials[0].material_id, "kept"); fail = false; await listing.more();
  assert.equal(listing.value.materials.length, 1);
});

test("refresh rereads every opened page after an import without hiding old rows or caching forever", async () => {
  let clock = 100, version = 1; const calls = [];
  const listing = createMaterialListing({ now: () => clock, api: async path => {
    calls.push(path);
    return path.includes("cursor=") ? result(["old"]) : result(version === 1 ? ["first"] : ["new", "first"], "next");
  } });
  await listing.refresh(); await listing.more(); assert.equal(calls.length, 2);
  version = 2; listing.invalidate();
  assert.deepEqual((await listing.refresh()).materials.map(item => item.material_id), ["new", "first", "old"]);
  assert.equal(calls.length, 4);
  clock += 31000; await listing.refresh(); assert.equal(calls.length, 6);
});

test("search length is normalized to the server contract before requests and comparisons", async () => {
  const calls = [], listing = createMaterialListing({ api: async path => { calls.push(path); return result([]); } });
  assert(listing.setQuery("a".repeat(250))); await listing.refresh();
  assert.equal(new URL(calls[0], "http://localhost").searchParams.get("q").length, 200);
  assert.equal(listing.setQuery("a".repeat(201)), false);
});

test("a next-page click during refresh waits for its fresh cursor and duplicate clicks load only one page", async () => {
  let clock = 100; const waiting = [], calls = [];
  const listing = createMaterialListing({ now: () => clock, api: path => {
    calls.push(path); if (calls.length === 1) return Promise.resolve(result(["first"], "old-cursor"));
    const wait = deferred(); waiting.push(wait); return wait.promise;
  } });
  await listing.refresh(); clock += 31000;
  const refresh = listing.refresh(), more = listing.more();
  assert.notEqual(more, refresh); assert.equal(listing.more(), more);
  waiting[0].resolve(result(["fresh-first"], "fresh-cursor")); await refresh;
  assert.equal(calls.length, 3); assert.match(calls[2], /cursor=fresh-cursor/);
  assert.equal(listing.more(), more, "Clicks during the queued page still coalesce");
  waiting[1].resolve(result(["next-page"], "third-page"));
  assert.deepEqual((await more).materials.map(row => row.material_id), ["fresh-first", "next-page"]);
  assert.equal(calls.length, 3);
});

test("query changes and invalidation cancel an old queued next page without hiding a new request", async () => {
  for (const change of ["query", "invalidate"]) {
    const waiting = [], calls = []; let clock = 100;
    const listing = createMaterialListing({ now: () => clock, api: path => {
      calls.push(path); if (calls.length === 1) return Promise.resolve(result(["initial"], "old-cursor"));
      const wait = deferred(); waiting.push(wait); return wait.promise;
    } });
    await listing.refresh(); clock += 31000;
    const oldRefresh = listing.refresh(), more = listing.more();
    if (change === "query") listing.setQuery("new query"); else listing.invalidate();
    const fresh = listing.refresh(); waiting[0].resolve(result(["obsolete"], "obsolete-cursor"));
    assert.equal(await oldRefresh, null); assert.equal(await more, null);
    assert.equal(calls.length, 3, "No old cursor request is emitted");
    waiting[1].resolve(result(["current"])); await fresh;
    assert.equal(listing.value.materials[0].material_id, "current");
  }
});

test("a failed refresh rejects its queued page and a completed final page does not request another cursor", async () => {
  for (const fail of [false, true]) {
    let clock = 100, calls = 0; const pending = deferred();
    const listing = createMaterialListing({ now: () => clock, api: async () => {
      if (++calls === 1) return result(["kept"], "old-cursor"); return pending.promise;
    } });
    await listing.refresh(); clock += 31000;
    const refresh = listing.refresh(), more = listing.more();
    if (fail) {
      const rejected = [assert.rejects(refresh, /offline/), assert.rejects(more, /offline/)];
      pending.reject(new Error("offline")); await Promise.all(rejected);
      assert.equal(listing.value.materials[0].material_id, "kept");
    } else {
      pending.resolve(result(["last"])); await refresh;
      assert.equal((await more).materials[0].material_id, "last");
    }
    assert.equal(calls, 2);
  }
});

test("the load-more button publishes its accumulated rows after an older whole-library refresh finishes", async () => {
  const source = readFileSync(new URL("../desk.js", import.meta.url), "utf8"), waiting = deferred();
  let fresh = 0, rendered = 100;
  const state = { materialBrowser: { more: async () => {} } }, moreMaterials = {};
  state.refreshPromise = waiting.promise.finally(() => { rendered = 100; state.refreshPromise = null; });
  const context = vm.createContext({ state, moreMaterials, failure: error => { throw error; }, refresh: () => {
    if (state.refreshPromise) return state.refreshPromise;
    fresh++; rendered = 106; return Promise.resolve();
  } });
  vm.runInContext(source.slice(source.indexOf("moreMaterials.onclick ="), source.indexOf("const claimContainer =")), context);
  const clicked = moreMaterials.onclick(); await Promise.resolve();
  assert.equal(moreMaterials.disabled, true); assert.equal(fresh, 0);
  waiting.resolve(); await clicked;
  assert.equal(fresh, 1); assert.equal(rendered, 106); assert.equal(moreMaterials.disabled, false);
});
