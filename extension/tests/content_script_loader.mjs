import { readFile } from "node:fs/promises";
export async function contentScriptSource() {
  const files = ["content-study-evidence.js", "content.js"];
  return (await Promise.all(files.map(file => readFile(new URL("../" + file, import.meta.url), "utf8")))).join("\n");
}
