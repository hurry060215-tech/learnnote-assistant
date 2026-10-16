// Fault injection only. No browser is launched and native key input is forbidden.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../timeline-native-zoom-acceptance.cjs"), "utf8");

async function probe({ failureAt = "newPage", reportFails = false, closeFails = false }) {
  const calls = [], diagnostics = [], primary = new Error(`PRIMARY_${failureAt}`);
  const failAt = key => { if (failureAt === key) throw primary; };
  const close = key => async () => { calls.push(`${key}.close`); if (closeFails) throw new Error(`${key}_CLOSE_FAILURE`); };
  const server = {process: () => { failAt("process"); return {pid: 12345}; }, wsEndpoint: () => "owned-fixture", close: close("server")};
  const context = {setDefaultTimeout: timeout => assert.equal(timeout, 15000), route: async () => failAt("route"), newPage: async () => { failAt("newPage"); throw new Error("Unexpected browser setup continuation"); }, close: close("context")};
  const browser = {newContext: async () => { failAt("newContext"); return context; }, close: close("browser")};
  const sandbox = {module: {exports: {}}, process: {platform: "win32"}, URL, __dirname: "/not-executed",
    console: {error: (...args) => diagnostics.push(args.map(String).join(" "))},
    require: name => {
      if (name === "playwright") return {chromium: {launchServer: async () => server, connect: async () => { failAt("connect"); return browser; }}};
      if (name === "node:fs") return {writeFileSync: () => { if (reportFails) throw new Error("REPORT_WRITE_FAILURE"); }};
      if (name === "node:child_process") return {execFileSync: () => { assert.fail("Native commands forbidden in fault-injection tests"); }};
      return require(name);
    }};
  vm.runInNewContext(source, sandbox);
  await assert.rejects(sandbox.module.exports.assertNativeTimelineZoom({base: "http://127.0.0.1:8765", taskId: "fixture", claimId: "fixture", out: "/not-written"}), error => error === primary);
  const expected = ["process", "connect"].includes(failureAt) ? ["server.close"]
    : failureAt === "newContext" ? ["browser.close", "server.close"] : ["context.close", "browser.close", "server.close"];
  assert.deepEqual(calls, expected, "Every created browser resource must be closed after failure");
  assert.equal(diagnostics.length, reportFails ? (closeFails ? 2 : 1) : 0);
}

(async () => {
  for (const failureAt of ["process", "connect", "newContext", "route", "newPage"])
    for (const reportFails of [false, true])
      for (const closeFails of [false, true]) await probe({failureAt, reportFails, closeFails});
  console.log("Native zoom failure preservation: 20 mocked cases passed; no native commands executed");
})().catch(error => { console.error(error); process.exitCode = 1; });
