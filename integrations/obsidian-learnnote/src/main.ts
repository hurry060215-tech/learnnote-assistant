import { Notice, Plugin, TFile, WorkspaceLeaf } from "obsidian";
import { LearnNoteApi } from "./api";
import { LearnNoteImporter } from "./importer";
import { LearnNoteSettingTab } from "./settings";
import type { LearnNoteSettings } from "./types";
import { LEARNNOTE_VIEW_TYPE, LearnNoteView } from "./view";

const DEFAULT_SETTINGS: LearnNoteSettings = {
  backendUrl: "http://127.0.0.1:8765",
  targetFolder: "LearnNote",
  includeTranscript: true,
  includeVisualWindows: true,
  includeQaHistory: true,
  includeManifest: false,
  openAfterImport: true
};

export default class LearnNotePlugin extends Plugin {
  settings: LearnNoteSettings = DEFAULT_SETTINGS;
  api!: LearnNoteApi;
  importer!: LearnNoteImporter;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.api = new LearnNoteApi(() => this.settings.backendUrl);
    this.importer = new LearnNoteImporter(this.app, this.api, () => this.settings);

    this.registerView(LEARNNOTE_VIEW_TYPE, leaf => new LearnNoteView(leaf, this));
    this.addSettingTab(new LearnNoteSettingTab(this));
    this.addRibbonIcon("book-open-check", "打开 LearnNote", () => void this.activateView());

    this.addCommand({
      id: "open-learnnote",
      name: "打开任务与课程问答",
      callback: () => void this.activateView()
    });
    this.addCommand({
      id: "import-latest-completed-task",
      name: "导入最近完成的笔记",
      callback: () => void this.importLatestTask()
    });
    this.addCommand({
      id: "sync-active-learnnote-note",
      name: "同步当前 LearnNote 笔记",
      checkCallback: checking => {
        const available = this.activeLearnNoteAvailable();
        if (available && !checking) void this.syncActiveNote();
        return available;
      }
    });
    this.addCommand({
      id: "ask-about-active-learnnote-note",
      name: "围绕当前 LearnNote 笔记提问",
      checkCallback: checking => {
        const available = this.activeLearnNoteAvailable();
        if (available && !checking) void this.askAboutActiveNote();
        return available;
      }
    });
  }

  onunload(): void {
    this.app.workspace.detachLeavesOfType(LEARNNOTE_VIEW_TYPE);
  }

  async updateSettings(patch: Partial<LearnNoteSettings>): Promise<void> {
    this.settings = { ...this.settings, ...patch };
    await this.saveData(this.settings);
  }

  async activateView(): Promise<LearnNoteView | null> {
    let leaf = this.app.workspace.getLeavesOfType(LEARNNOTE_VIEW_TYPE)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false) || this.app.workspace.getLeaf("tab");
      await leaf.setViewState({ type: LEARNNOTE_VIEW_TYPE, active: true });
    }
    await this.app.workspace.revealLeaf(leaf);
    return leaf.view instanceof LearnNoteView ? leaf.view : null;
  }

  private activeLearnNoteAvailable(): boolean {
    const file = this.app.workspace.getActiveFile();
    if (!(file instanceof TFile) || file.extension !== "md") return false;
    const frontmatter = this.app.metadataCache.getFileCache(file)?.frontmatter;
    return Boolean(frontmatter?.learnnote_task_id);
  }

  private async importLatestTask(): Promise<void> {
    try {
      const [latest] = await this.api.tasks();
      if (!latest) {
        new Notice("LearnNote 中还没有可导入的已完成任务");
        return;
      }
      const result = await this.importer.importTask(latest);
      new Notice(result.created ? "已导入最近完成的 LearnNote 笔记" : "已同步最近完成的 LearnNote 笔记");
    } catch (error) {
      new Notice(error instanceof Error ? error.message : "导入失败");
    }
  }

  private async syncActiveNote(): Promise<void> {
    try {
      const taskId = await this.importer.taskIdFromActiveFile();
      if (!taskId) {
        new Notice("当前文件不是 LearnNote 导入的笔记");
        return;
      }
      const task = await this.api.task(taskId);
      await this.importer.importTask(task);
      new Notice("已同步笔记，个人补充内容已保留");
    } catch (error) {
      new Notice(error instanceof Error ? error.message : "同步失败");
    }
  }

  private async askAboutActiveNote(): Promise<void> {
    const taskId = await this.importer.taskIdFromActiveFile();
    if (!taskId) {
      new Notice("当前文件不是 LearnNote 导入的笔记");
      return;
    }
    const view = await this.activateView();
    await view?.selectTask(taskId);
  }

  private async loadSettings(): Promise<void> {
    const stored = await this.loadData() as Partial<LearnNoteSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(stored || {}) };
  }
}
