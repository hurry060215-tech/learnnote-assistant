import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const product = readFileSync(new URL("../desk-product.js", import.meta.url), "utf8");
const settings = readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../desk.js", import.meta.url), "utf8");

assert.match(product, /event\.key !== "Enter" \|\| event\.shiftKey/);
assert.match(product, /event\.isComposing \|\| event\.keyCode === 229/);
assert.match(product, /if \(!pending\) \$\("aiForm"\)\.requestSubmit\(\)/);
assert.match(product, /citationPreviews\.className = "assistant-citation-previews"/);
assert.match(product, /data-citation-preview/);
assert.match(product, /aria-expanded/);
assert.match(product, /openSource\(citation\.start, messageSource\)/);
assert.doesNotMatch(product, /b\.after\(p\)/);
assert.match(product, /globalItems\.map\(\(item\) => \(\{ item, source: null \}\)\)/);
assert.match(product, /sourceItems\.map\(\(item\) => \(\{ item, source: s \}\)\)/);
assert.match(workspace, /async function openSource\(seconds, sourceOverride = null\)/);
assert.match(settings, /id='updateClientVersion'/);
assert.match(settings, /id='updateExtensionVersion'/);
assert.match(settings, /start_update_download/);
assert.match(settings, /apply_update/);
assert.match(settings, /start_extension_update_download/);
assert.match(settings, /apply_extension_update/);
assert.match(settings, /startupCheck/);
console.log("Assistant and update-center contracts are present");
