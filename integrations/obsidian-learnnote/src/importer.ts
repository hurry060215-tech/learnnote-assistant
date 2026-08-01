import { App, normalizePath, TFile, TFolder } from "obsidian";
import { strFromU8, unzipSync } from "fflate";
import {
  formatTimestamp,
  importedTaskId,
  mergeGeneratedNote,
  noteFrontmatter,
  safeArchivePath,
  taskFolderPath
} from "./core.mjs";
import type { LearnNoteApi } from "./api";
import type { ImportResult, LearnNoteSettings, LearnNoteTask } from "./types";

const MAX_ARCHIVE_FILES = 240;
const MAX_ARCHIVE_COMPRESSED_BYTES = 60 * 1024 * 1024;
const MAX_ARCHIVE_BYTES = 120 * 1024 * 1024;
const MAX_SINGLE_FILE_BYTES = 30 * 1024 * 1024;

function decoded(files: Record<string, Uint8Array>, name: string): string {
  const value = files[name];
  return value ? strFromU8(value) : "";
}

function stripFrontmatter(markdown: string): string {
  return String(markdown || "").replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, "").trim();
}

function transcriptMarkdown(raw: string): string {
  if (!raw.trim()) return "";
  try {
    const payload = JSON.parse(raw) as { source?: string; language?: string; segments?: Array<{ start?: number; end?: number; text?: string }> };
    const lines = [
      "# 字幕",
      "",
      `- 来源：${payload.source || "unknown"}`,
      `- 语言：${payload.language || "unknown"}`,
      ""
    ];
    for (const segment of payload.segments || []) {
      const text = String(segment.text || "").trim();
      if (!text) continue;
      lines.push(`- **${formatTimestamp(segment.start)} – ${formatTimestamp(segment.end)}** ${text}`);
    }
    return lines.join("\n");
  } catch {
    return "# 字幕\n\n字幕 JSON 无法解析，请查看 `transcript.json`。";
  }
}

function allowedArchiveEntry(path: string, settings: LearnNoteSettings): boolean {
  if (path === "note.md") return true;
  if (settings.includeManifest && ["manifest.json", "audit.md"].includes(path)) return true;
  if (settings.includeTranscript && (path === "transcript.json" || path.startsWith("subtitles/"))) return true;
  if (settings.includeVisualWindows && (path === "visual_windows.md" || path === "visual_index.json" || path.startsWith("grids/"))) return true;
  if (settings.includeQaHistory && (path === "qa.md" || path === "qa_history.json")) return true;
  return false;
}

export class LearnNoteImporter {
  constructor(
    private readonly app: App,
    private readonly api: LearnNoteApi,
    private readonly settings: () => LearnNoteSettings
  ) {}

  private async ensureFolder(path: string): Promise<void> {
    const normalized = normalizePath(path);
    const parts = normalized.split("/").filter(Boolean);
    let current = "";
    for (const part of parts) {
      current = current ? `${current}/${part}` : part;
      const existing = this.app.vault.getAbstractFileByPath(current);
      if (existing instanceof TFolder) continue;
      if (existing) throw new Error(`Vault 中已有同名文件：${current}`);
      await this.app.vault.createFolder(current);
    }
  }

  private async writeText(path: string, content: string): Promise<TFile> {
    const normalized = normalizePath(path);
    const parent = normalized.split("/").slice(0, -1).join("/");
    if (parent) await this.ensureFolder(parent);
    const existing = this.app.vault.getAbstractFileByPath(normalized);
    if (existing instanceof TFile) {
      await this.app.vault.modify(existing, content);
      return existing;
    }
    if (existing) throw new Error(`Vault 路径不是文件：${normalized}`);
    return this.app.vault.create(normalized, content);
  }

  private async writeBinary(path: string, content: Uint8Array): Promise<TFile> {
    const normalized = normalizePath(path);
    const parent = normalized.split("/").slice(0, -1).join("/");
    if (parent) await this.ensureFolder(parent);
    const bytes = Uint8Array.from(content).buffer;
    const existing = this.app.vault.getAbstractFileByPath(normalized);
    if (existing instanceof TFile) {
      await this.app.vault.modifyBinary(existing, bytes);
      return existing;
    }
    if (existing) throw new Error(`Vault 路径不是文件：${normalized}`);
    return this.app.vault.createBinary(normalized, bytes);
  }

  importedNote(task: LearnNoteTask): TFile | null {
    const path = normalizePath(`${taskFolderPath(this.settings().targetFolder, task.title, task.id)}/LearnNote.md`);
    const file = this.app.vault.getAbstractFileByPath(path);
    return file instanceof TFile ? file : null;
  }

  async taskIdFromActiveFile(): Promise<string> {
    const file = this.app.workspace.getActiveFile();
    if (!file) return "";
    return importedTaskId(await this.app.vault.read(file));
  }

  async importTask(task: LearnNoteTask): Promise<ImportResult> {
    const settings = this.settings();
    const folderPath = normalizePath(taskFolderPath(settings.targetFolder, task.title, task.id));
    const notePath = normalizePath(`${folderPath}/LearnNote.md`);
    const bundle = new Uint8Array(await this.api.bundle(task.id));
    if (bundle.byteLength > MAX_ARCHIVE_COMPRESSED_BYTES) {
      throw new Error("LearnNote 资料包过大，已停止导入");
    }
    const files = unzipSync(bundle);
    const entries = Object.entries(files);
    if (entries.length > MAX_ARCHIVE_FILES) throw new Error("LearnNote 资料包文件数量异常，已停止导入");
    const totalBytes = entries.reduce((total, [, value]) => total + value.byteLength, 0);
    if (totalBytes > MAX_ARCHIVE_BYTES || entries.some(([, value]) => value.byteLength > MAX_SINGLE_FILE_BYTES)) {
      throw new Error("LearnNote 资料包超出 Obsidian 导入限制");
    }

    const note = decoded(files, "note.md");
    if (!note.trim()) throw new Error("资料包中没有可导入的笔记");
    await this.ensureFolder(folderPath);

    let extractedFiles = 0;
    for (const [rawPath, content] of entries) {
      const safePath = safeArchivePath(rawPath);
      if (!safePath || !allowedArchiveEntry(safePath, settings) || safePath === "note.md") continue;
      const destination = normalizePath(`${folderPath}/${safePath}`);
      if (/\.(?:md|json|srt|vtt|ass|ssa)$/i.test(safePath)) {
        await this.writeText(destination, strFromU8(content));
      } else {
        await this.writeBinary(destination, content);
      }
      extractedFiles += 1;
    }

    const related: string[] = [];
    if (settings.includeTranscript && files["transcript.json"]) {
      await this.writeText(`${folderPath}/Transcript.md`, transcriptMarkdown(decoded(files, "transcript.json")));
      related.push("[[Transcript|带时间戳字幕]]");
    }
    if (settings.includeVisualWindows && files["visual_windows.md"]) related.push("[[visual_windows|画面与时间轴]]");
    if (settings.includeQaHistory && files["qa.md"]) related.push("[[qa|课程问答记录]]");
    if (settings.includeManifest && files["manifest.json"]) related.push("[[manifest.json|资料清单]]");

    const generated = [
      stripFrontmatter(note),
      "",
      "## LearnNote 资料",
      "",
      related.length ? related.map(item => `- ${item}`).join("\n") : "- 当前仅导入主笔记",
      "",
      `> LearnNote 任务：\`${task.id}\` · 最近同步：${new Date().toLocaleString()}`
    ].join("\n");
    const existingFile = this.app.vault.getAbstractFileByPath(notePath);
    const existing = existingFile instanceof TFile ? await this.app.vault.read(existingFile) : "";
    const created = !(existingFile instanceof TFile);
    const syncedAt = new Date().toISOString();
    const merged = mergeGeneratedNote(existing, noteFrontmatter(task, syncedAt), generated);
    const noteFile = await this.writeText(notePath, merged);
    await this.writeText(`${folderPath}/_learnnote.json`, JSON.stringify({
      schema_version: 1,
      task_id: task.id,
      source_title: task.title,
      synced_at: syncedAt,
      generated_note: "LearnNote.md",
      extracted_files: extractedFiles
    }, null, 2));

    if (settings.openAfterImport) await this.app.workspace.getLeaf(false).openFile(noteFile);
    return { notePath, folderPath, created, extractedFiles };
  }
}
