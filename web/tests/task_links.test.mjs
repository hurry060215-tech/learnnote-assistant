import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = fs.readFileSync(path.join(root, "web", "task-links.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");

test("task link helpers stay isolated from the main application bundle", () => {
  assert.match(html, /src="\/web\/task-links\.js/);
  assert.match(app, /LearnNoteTaskLinks/);
  assert.match(source, /global\.LearnNoteTaskLinks/);
});

test("task link helpers encode task and window identifiers", () => {
  const context = { globalThis: {} };
  vm.runInNewContext(source, context);
  const links = context.globalThis.LearnNoteTaskLinks;
  const apiUrl = value => `http://localhost${value}`;
  const task = { id: "task/with spaces" };

  assert.equal(links.exportUrl(apiUrl, task, "note"), "http://localhost/api/tasks/task%2Fwith%20spaces/exports/note");
  assert.equal(links.clipExportUrl(apiUrl, task, "window 1"), "http://localhost/api/tasks/task%2Fwith%20spaces/exports/clips/window%201");
  assert.equal(links.rerunUrl(apiUrl, task.id), "http://localhost/api/tasks/task%2Fwith%20spaces/rerun-from-media");
  assert.equal(links.resumeUrl(apiUrl, task.id), "http://localhost/api/tasks/task%2Fwith%20spaces/resume");
  assert.equal(links.qaUrl(apiUrl, task.id), "http://localhost/api/tasks/task%2Fwith%20spaces/qa");
});
