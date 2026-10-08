import { readFileSync } from "node:fs";
import vm from "node:vm";

const extensionRoot = new URL("../../", import.meta.url);

// Test-only implementation of synchronous local importScripts semantics.
export function installExtensionScriptLoader(context) {
  const loading = new Set();
  const loaded = [];
  context.importScripts = (...names) => {
    for (const name of names) {
      const url = new URL(name, extensionRoot);
      if (url.protocol !== "file:" || !url.href.startsWith(extensionRoot.href)) {
        throw new Error("Unexpected extension import: " + name);
      }
      if (loading.has(url.href)) throw new Error("Cyclic extension import: " + name);
      loading.add(url.href);
      try {
        vm.runInContext(readFileSync(url, "utf8"), context, { filename: url.pathname });
        loaded.push(name);
      } finally {
        loading.delete(url.href);
      }
    }
  };
  return loaded;
}
