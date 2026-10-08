import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import esbuild from "esbuild";
import { buildOptions } from "../esbuild.config.mjs";

const require = createRequire(import.meta.url);

test("Obsidian's development dependency resolves patched Moment", () => {
  const obsidianRequire = createRequire(require.resolve("obsidian/package.json"));
  const moment = obsidianRequire("moment/package.json");
  const [major, minor] = moment.version.split(".").map(Number);
  assert.ok(major > 2 || (major === 2 && minor >= 31),
    `Moment ${moment.version} is affected by GHSA-4p3w-j4w9-5jqw`);
  const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url)));
  const moments = Object.entries(lock.packages).filter(([path]) => path.endsWith("node_modules/moment"));
  assert.ok(moments.length > 0);
  for (const [path, entry] of moments) {
    assert.equal(entry.dev, true, `${path} must remain development-only`);
    assert.equal(entry.version, moment.version, `${path} must match the resolved patched version`);
  }
});

test("production bundle excludes Moment and keeps Obsidian host-provided", async () => {
  const result = await esbuild.build({
    ...buildOptions(true),
    write: false,
    metafile: true
  });
  for (const path of Object.keys(result.metafile.inputs)) {
    assert.doesNotMatch(path.replaceAll("\\", "/"), /(?:^|\/)node_modules\/(?:moment|obsidian)\//);
  }
  const imports = Object.values(result.metafile.outputs).flatMap(output => output.imports);
  assert.ok(imports.some(entry => entry.path === "obsidian" && entry.external));
  assert.ok(!imports.some(entry => /^moment(?:\/|$)/.test(entry.path)),
    "Moment must not become a runtime dependency, even as an external import");
});
