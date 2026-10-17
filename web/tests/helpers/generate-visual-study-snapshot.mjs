// Explicit opt-in regeneration from the committed pre-extraction implementation.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import vm from "node:vm";
import { baseline, functionNames, providerFiles, functionSource, createAdapters, project, cases } from "./visual-study-contract.mjs";

if (process.argv[2] !== "--write") throw Error("Pass --write to regenerate the fixed-baseline snapshot");
const root = new URL("../../../", import.meta.url);
const sources = new Map();
const readSource = name => {
  if (!sources.has(name)) sources.set(name, execFileSync("git", ["show", `${baseline}:web/${name}`], { cwd: root, encoding: "utf8" }));
  return sources.get(name);
};
const app = readSource("app.js");
const bodies = functionNames.map(name => functionSource(app, name));
const sha256 = source => createHash("sha256").update(source).digest("hex");
const snapshot = {
  baseline,
  app_sha256: sha256(app),
  function_sha256: Object.fromEntries(functionNames.map((name, index) => [name, sha256(bodies[index])])),
  cases: cases().map(row => {
    const context = vm.createContext({ URL });
    for (const file of providerFiles) vm.runInContext(readSource(file), context);
    for (const namespace of ["LearnNoteTaskFormat", "LearnNoteTaskList", "LearnNoteVisualWindowEvidence"]) Object.assign(context, context[namespace]);
    Object.assign(context, createAdapters(app, readSource, row.runtime).ports);
    vm.runInContext(bodies.join("\n"), context);
    return { ...row, expected: project(context, context.LearnNoteTaskList, row) };
  })
};
writeFileSync(new URL("../fixtures/visual-study-d2b4ef0.json", import.meta.url), JSON.stringify(snapshot, null, 2) + "\n");
console.log(`Froze ${snapshot.cases.length} original visual-study cases from ${baseline}`);
