import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const editorial = fs.readFileSync(path.join(root, "web", "editorial.js"), "utf8");
const experience = fs.readFileSync(path.join(root, "web", "experience.css"), "utf8");
const allCss = ["styles.css", "workspace.css", "product.css", "mature.css", "editorial.css", "experience.css"]
  .map(name => fs.readFileSync(path.join(root, "web", name), "utf8"))
  .join("\n");

const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);

function parseAttributes(tagSource) {
  const firstSpace = tagSource.search(/\s/);
  const source = firstSpace < 0 ? "" : tagSource.slice(firstSpace).replace(/\/?\s*>$/, "");
  const attributes = {};
  const pattern = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
  let match;
  while ((match = pattern.exec(source))) {
    attributes[match[1].toLowerCase()] = match[2] ?? match[3] ?? match[4] ?? "";
  }
  return attributes;
}

function parseHtml(source) {
  const rootNode = { tag: "#root", attrs: {}, parent: null, children: [], textParts: [] };
  const stack = [rootNode];
  const tokens = String(source).match(/<!--[\s\S]*?-->|<![^>]*>|<\/?[A-Za-z][^>]*>|[^<]+/g) || [];
  for (const token of tokens) {
    if (token.startsWith("<!--") || token.startsWith("<!")) continue;
    if (token.startsWith("</")) {
      const tag = token.slice(2).match(/^\s*([^\s>]+)/)?.[1]?.toLowerCase();
      while (stack.length > 1) {
        const node = stack.pop();
        if (node.tag === tag) break;
      }
      continue;
    }
    if (token.startsWith("<")) {
      const tag = token.slice(1).match(/^\s*([^\s/>]+)/)?.[1]?.toLowerCase();
      if (!tag) continue;
      const parent = stack.at(-1);
      const node = { tag, attrs: parseAttributes(token), parent, children: [], textParts: [] };
      parent.children.push(node);
      if (!VOID_TAGS.has(tag) && !/\/\s*>$/.test(token)) stack.push(node);
      continue;
    }
    stack.at(-1).textParts.push(token);
  }
  return rootNode;
}

const documentTree = parseHtml(html);

function walk(node, predicate, results = []) {
  if (predicate(node)) results.push(node);
  for (const child of node.children || []) walk(child, predicate, results);
  return results;
}

function byId(id) {
  return walk(documentTree, node => node.attrs?.id === id)[0] || null;
}

function descendants(node, predicate) {
  return (node?.children || []).flatMap(child => [
    ...(predicate(child) ? [child] : []),
    ...descendants(child, predicate)
  ]);
}

function visibleInMarkup(node) {
  for (let current = node; current; current = current.parent) {
    if (Object.hasOwn(current.attrs || {}, "hidden")) return false;
    if (current.attrs?.["aria-hidden"] === "true") return false;
  }
  return true;
}

function nodeText(node) {
  return `${(node?.textParts || []).join(" ")} ${(node?.children || []).map(nodeText).join(" ")}`
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function functionBlock(source, name) {
  const escapedName = escapeRegExp(name);
  const declaration = new RegExp(`function\\s+${escapedName}\\s*\\([^)]*\\)\\s*\\{`, "m").exec(source)
    || new RegExp(`(?:const|let)\\s+${escapedName}\\s*=\\s*(?:\\([^)]*\\)|[^=;]+)\\s*=>\\s*\\{`, "m").exec(source);
  if (!declaration) return "";
  const opening = source.indexOf("{", declaration.index);
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = opening; index < source.length; index += 1) {
    const character = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
      continue;
    }
    if (character === "'" || character === '"' || character === "`") {
      quote = character;
      continue;
    }
    if (character === "{") depth += 1;
    else if (character === "}" && --depth === 0) return source.slice(opening + 1, index);
  }
  return "";
}

function cssRules(source) {
  return [...String(source).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(match => ({
    selector: match[1].trim(),
    body: match[2],
    index: match.index
  }));
}

test("primary navigation contains only Start, Library, Review, and Settings", () => {
  const navigation = byId("mainNavigation");
  assert.ok(navigation, "main navigation is required");
  const destinations = descendants(navigation, node => node.attrs?.["data-app-view"] && visibleInMarkup(node));
  assert.deepEqual(destinations.map(nodeText), ["开始", "资料库", "复习", "设置"]);
  assert.deepEqual(destinations.map(node => node.attrs["data-app-view"]), ["workspace", "notes", "study", "settings"]);
});

test("the initial Start screen exposes the URL field and generate action without another reveal step", () => {
  const home = byId("editorialHome");
  assert.ok(home, "Start screen is required");
  const visibleUrlInputs = descendants(home, node => node.tag === "input"
    && visibleInMarkup(node)
    && (node.attrs.id === "editorialUrlInput" || node.attrs.inputmode === "url" || node.attrs.type === "url"));
  const visibleGenerateButtons = descendants(home, node => node.tag === "button"
    && visibleInMarkup(node)
    && /(?:生成笔记|开始生成|开始分析)/.test(nodeText(node)));
  assert.ok(visibleUrlInputs.length >= 1, "the URL input must be visible in the initial Start state");
  assert.ok(visibleGenerateButtons.length >= 1, "a visible generate-note action must sit on the initial Start state");
});

test("ordinary URL submissions use an explicit decision function to bypass confirmation", () => {
  const source = `${editorial}\n${app}`;
  const declaredNames = [
    ...source.matchAll(/function\s+([A-Za-z_$][\w$]*)\s*\(/g),
    ...source.matchAll(/(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:\([^)]*\)|[^=;]+)\s*=>/g)
  ].map(match => match[1]);
  const candidates = [...new Set(declaredNames)].filter(name => /^(?:should|can|needs?|requires?|skip|bypass|decide)/i.test(name)
    && /confirm|confirmation/i.test(name));
  const decision = candidates.find(name => {
    const body = functionBlock(source, name);
    const uses = source.match(new RegExp(`\\b${escapeRegExp(name)}\\b`, "g"))?.length || 0;
    return uses >= 2 && /\burl\b/i.test(body) && /return\b/.test(body);
  });
  assert.ok(decision, "define and call a URL-aware confirmation bypass decision function");
});

test("at most one collapsible trust or evidence summary precedes the completed note body", () => {
  const noteStart = app.indexOf('if (selectedTab === "note")');
  const nextBranch = app.indexOf('if (selectedTab === "slices"', noteStart);
  assert.ok(noteStart >= 0 && nextBranch > noteStart, "note render branch is required");
  const branch = app.slice(noteStart, nextBranch);
  const articleIndex = branch.indexOf('<article class="markdown-note"');
  assert.ok(articleIndex >= 0, "completed note body is required");
  const beforeBody = branch.slice(0, articleIndex);
  const surfaceNames = [...beforeBody.matchAll(/\$\{\s*([A-Za-z_$][\w$]*(?:Trust|Evidence|Provenance|Readiness|Document)[\w$]*)\s*\(/gi)]
    .map(match => match[1]);
  const uniqueSurfaces = [...new Set(surfaceNames)];
  assert.ok(uniqueSurfaces.length <= 1, `found ${uniqueSurfaces.length} pre-body trust/evidence surfaces: ${uniqueSurfaces.join(", ")}`);
  if (uniqueSurfaces.length === 1) {
    const body = functionBlock(app, uniqueSurfaces[0]);
    assert.match(body, /<details\b/i, "the single trust/evidence summary must be collapsible");
    assert.match(body, /<summary\b/i, "the collapsible trust/evidence surface needs a summary label");
  }
});

test("task deletion is not a persistent peer action on every task card", () => {
  const renderBody = functionBlock(app, "renderTasks");
  assert.ok(renderBody, "renderTasks implementation is required");
  const controls = /<div class="task-controls"[^>]*>([\s\S]*?)<\/div>/.exec(renderBody)?.[1] || "";
  const deleteIndex = controls.indexOf('data-task-action="delete"');
  if (deleteIndex < 0) return;
  const detailsOpen = controls.lastIndexOf("<details", deleteIndex);
  const detailsClose = controls.indexOf("</details>", deleteIndex);
  assert.ok(detailsOpen >= 0 && detailsClose > deleteIndex, "delete must live behind a secondary details/menu disclosure");
});

test("layout-debug controls are absent or hidden by default", () => {
  const group = descendants(documentTree, node => String(node.attrs?.class || "").split(/\s+/).includes("layout-toggle-group"))[0];
  if (!group || !visibleInMarkup(group)) return;
  const hiddenRule = cssRules(allCss).some(rule => /display\s*:\s*none\b/i.test(rule.body)
    && rule.selector.split(",").some(selector => {
      const value = selector.trim();
      return value === ".layout-toggle-group"
        || (/layout-toggle-group/.test(value) && /:not\([^)]*(?:debug|developer)[^)]*\)/i.test(value));
    }));
  assert.ok(hiddenRule, "layout-debug controls must not be visible in the default product shell");
});

test("dark mode explicitly overrides the Start surface and every glass overlay", () => {
  const rules = cssRules(experience);
  const surfaces = [
    "#workspace.workspace-panel",
    ".ai-assistant-drawer",
    ".result-more-panel",
    ".onboarding-dialog",
    ".note-version-dialog",
    ".release-notes-dialog",
    ".study-proposal-dialog"
  ];
  for (const surface of surfaces) {
    const matching = rules.filter(rule => /theme-dark/.test(rule.selector)
      && rule.selector.includes(surface)
      && /background(?:-color)?\s*:/.test(rule.body));
    assert.ok(matching.length, `missing explicit dark-mode background for ${surface}`);
    const finalBody = matching.at(-1).body;
    assert.doesNotMatch(finalBody, /background(?:-color)?\s*:\s*(?:#fff(?:fff)?\b|rgba?\(\s*255\s*,\s*255\s*,\s*255)/i);
  }

  const lightWorkspace = rules.filter(rule => /workspace-mode/.test(rule.selector)
    && !/theme-dark/.test(rule.selector)
    && rule.selector.includes("#workspace.workspace-panel")
    && /background(?:-color)?\s*:/.test(rule.body)).at(-1);
  const darkWorkspace = rules.filter(rule => /theme-dark/.test(rule.selector)
    && rule.selector.includes("#workspace.workspace-panel")
    && /background(?:-color)?\s*:/.test(rule.body)).at(-1);
  assert.ok(darkWorkspace.index > lightWorkspace.index, "the dark Start-surface override must follow the light workspace rule in the final experience layer");
});
