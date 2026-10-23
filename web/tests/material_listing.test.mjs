import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const { createMaterialListing } = await import("data:text/javascript;base64," + Buffer.from(readFileSync(new URL("../material-listing.js", import.meta.url))).toString("base64"));
const deferred = () => { let resolve; const promise = new Promise(yes => resolve = yes); return { promise, resolve }; };
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
