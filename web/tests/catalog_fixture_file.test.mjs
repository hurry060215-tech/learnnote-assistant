import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("Edge fixture reads checked file descriptors and closes them after read failure", () => {
  const script = fileURLToPath(new URL("../../scripts/material-catalog-recovery-acceptance.cjs", import.meta.url));
  const result = execFileSync(process.execPath, [script, "--self-test"], { encoding: "utf8" });
  assert.match(result, /fixture loaded/);
});
