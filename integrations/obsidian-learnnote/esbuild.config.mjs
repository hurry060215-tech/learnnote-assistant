import esbuild from "esbuild";
import process from "process";
import { builtinModules } from "node:module";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export function buildOptions(production = false) {
  return {
    banner: {
      js: "/* Generated LearnNote Obsidian plugin bundle. Source: integrations/obsidian-learnnote/src */"
    },
    entryPoints: ["src/main.ts"],
    bundle: true,
    external: [
      "obsidian",
      "electron",
      "@codemirror/autocomplete",
      "@codemirror/collab",
      "@codemirror/commands",
      "@codemirror/language",
      "@codemirror/lint",
      "@codemirror/search",
      "@codemirror/state",
      "@codemirror/view",
      "@lezer/common",
      "@lezer/highlight",
      "@lezer/lr",
      ...builtinModules
    ],
    format: "cjs",
    target: "es2021",
    logLevel: "info",
    sourcemap: production ? false : "inline",
    treeShaking: true,
    outfile: "main.js",
    minify: production
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const production = process.argv[2] === "production";
  const context = await esbuild.context(buildOptions(production));
  if (production) {
    await context.rebuild();
    await context.dispose();
  } else {
    await context.watch();
  }
}
