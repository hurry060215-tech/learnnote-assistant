import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
const setup = fs.readFileSync(path.join(root, "web", "model-setup.js"), "utf8");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "experience.css"), "utf8");
const backend = fs.readFileSync(path.join(root, "backend", "app", "routers", "system.py"), "utf8");
const desktop = fs.readFileSync(path.join(root, "desktop", "main.py"), "utf8");

test("guided model setup loads after the main app and before editorial actions", () => {
  const appIndex = html.indexOf("/web/app.js");
  const setupIndex = html.indexOf("/web/model-setup.js");
  const editorialIndex = html.indexOf("/web/editorial.js");
  assert.ok(appIndex >= 0 && setupIndex > appIndex && editorialIndex > setupIndex);
  for (const id of ["modelSetupGuide", "modelProviderQuickChoices", "openModelProviderButton", "discoverModelsButton", "testModelConnectionButton", "finishModelSetupButton"]) {
    assert.ok(html.includes(`id="${id}"`), `missing model setup control ${id}`);
  }
});

test("one-click entry reveals advanced model settings and remembers where to return", () => {
  assert.match(setup, /appSettings\.advancedSettings\s*=\s*true/);
  assert.match(setup, /showAppView\("settings"\)/);
  assert.match(setup, /showSettingsPane\("model"\)/);
  assert.match(setup, /returnContext\s*=\s*\{/);
  assert.match(setup, /setAssistantOpen\(true/);
  assert.match(setup, /#onboardingModelButton/);
  assert.match(setup, /data-open-model-setup/);
});

test("provider console links are fixed official allowlists rather than user-controlled URLs", () => {
  for (const host of ["platform.openai.com", "console.groq.com", "aistudio.google.com", "bailian.console.aliyun.com", "platform.deepseek.com", "platform.kimi.com"]) {
    assert.ok(setup.includes(host), `web provider allowlist is missing ${host}`);
    assert.ok(desktop.includes(host), `desktop provider allowlist is missing ${host}`);
  }
  assert.match(desktop, /MODEL_PROVIDER_KEY_URLS\.get\(normalized, ""\)/);
  assert.match(desktop, /raise ValueError\("Unsupported model provider"\)/);
});

test("connection check uses a real short chat and never returns or persists the key", () => {
  assert.match(setup, /\/api\/model\/setup\/check/);
  assert.match(backend, /Reply with OK only\./);
  assert.match(backend, /max_retries=0/);
  assert.match(backend, /TRUSTED_MODEL_API_HOSTS/);
  assert.match(backend, /api_key=payload\.api_key\.strip\(\)/);
  assert.doesNotMatch(setup, /localStorage[\s\S]{0,120}(?:api[_ -]?key|llmApiKey)/i);
  assert.doesNotMatch(app.match(/function currentModelSettings\(\)[\s\S]*?\n\}/)?.[0] || "", /api[_ -]?key/i);
});

test("assistant missing-key state exposes a direct setup action", () => {
  assert.match(setup, /latest\?\.warning === "missing_api_key"/);
  assert.match(setup, /一键配置模型/);
  assert.match(setup, /assistant-model-cta/);
  assert.match(css, /\.assistant-model-cta/);
});

test("guided setup remains usable on mobile", () => {
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.model-setup-steps\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(css, /\.model-setup-steps small\s*\{\s*display:\s*none/);
  assert.match(css, /\.model-setup-actions #finishModelSetupButton[\s\S]*grid-column:\s*1 \/ -1/);
});
