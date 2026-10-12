import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
const source = fs.readFileSync(new URL("../usage-coverage.js", import.meta.url), "utf8");
const { usageCoverage } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("empty history, unknown provider usage and true zero are distinct", () => {
  assert.deepEqual(usageCoverage({ requests: 0, measured_requests: 0, total_tokens: 0 }),
    { status: "empty", value: 0, text: "0", detail: "尚无请求记录" });
  for (const total_tokens of [null, 0]) {
    const result = usageCoverage({ requests: 2, measured_requests: 0, total_tokens });
    assert.equal(result.text, "未知"); assert.equal(result.value, null);
    assert.equal(result.detail, "0/2 次有记录");
  }
  assert.equal(usageCoverage({ requests: 1, measured_requests: 1, total_tokens: 0 }).text, "0");
});

test("mixed sums, including reported zero, visibly qualify their coverage", () => {
  for (const value of [0, 25]) {
    const result = usageCoverage({ requests: 2, measured_requests: 1, total_tokens: value });
    assert.equal(result.text, `已记录 ${value}`);
    assert.equal(result.detail, "1/2 次有记录");
    assert.equal(result.status, "partial");
  }
});

test("input and output do not borrow total coverage or invent missing counts", () => {
  const group = { requests: 1, measured_requests: 1, total_tokens: 25, input_tokens: null, output_tokens: null,
    measured_input_requests: 0, measured_output_requests: 0 };
  assert.equal(usageCoverage(group).text, "25");
  assert.equal(usageCoverage(group, "input_tokens").text, "未知");
  assert.equal(usageCoverage(group, "output_tokens").text, "未知");
  assert.equal(usageCoverage({ ...group, input_tokens: 25, measured_input_requests: undefined }, "input_tokens").text, "未知");
});

test("invalid and legacy incomplete fields stay unknown without coercion", () => {
  for (const group of [undefined, {}, { total_tokens: 0 }, { requests: 1, measured_requests: 2, total_tokens: 5 },
    { requests: 1, measured_requests: 1, total_tokens: null }, { requests: 1, measured_requests: 1, total_tokens: -1 },
    { requests: 1, measured_requests: true, total_tokens: 5 }, { requests: 1, measured_requests: 1, total_tokens: "5" }]) {
    assert.equal(usageCoverage(group).text, "未知");
  }
});
