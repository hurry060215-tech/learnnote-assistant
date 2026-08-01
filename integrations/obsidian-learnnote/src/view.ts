import { ItemView, Notice, WorkspaceLeaf, setIcon } from "obsidian";
import type LearnNotePlugin from "./main";
import type { LearnNoteTask, QuestionHistoryItem, QuestionResult } from "./types";

export const LEARNNOTE_VIEW_TYPE = "learnnote-tasks-view";

export class LearnNoteView extends ItemView {
  private tasks: LearnNoteTask[] = [];
  private selectedTaskId = "";
  private filter = "";
  private loading = false;
  private history: QuestionHistoryItem[] = [];

  constructor(leaf: WorkspaceLeaf, private readonly plugin: LearnNotePlugin) {
    super(leaf);
  }

  getViewType(): string {
    return LEARNNOTE_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "LearnNote";
  }

  getIcon(): string {
    return "book-open-check";
  }

  async onOpen(): Promise<void> {
    await this.refresh();
  }

  async selectTask(taskId: string): Promise<void> {
    this.selectedTaskId = taskId;
    await this.loadHistory();
    this.render();
  }

  private async refresh(): Promise<void> {
    if (this.loading) return;
    this.loading = true;
    this.render();
    try {
      this.tasks = await this.plugin.api.tasks();
      if (this.selectedTaskId && !this.tasks.some(task => task.id === this.selectedTaskId)) this.selectedTaskId = "";
      if (!this.selectedTaskId && this.tasks.length) this.selectedTaskId = this.tasks[0].id;
      await this.loadHistory();
    } catch (error) {
      this.tasks = [];
      new Notice(error instanceof Error ? error.message : "无法读取 LearnNote 任务");
    } finally {
      this.loading = false;
      this.render();
    }
  }

  private async loadHistory(): Promise<void> {
    if (!this.selectedTaskId) {
      this.history = [];
      return;
    }
    try {
      this.history = await this.plugin.api.questionHistory(this.selectedTaskId);
    } catch {
      this.history = [];
    }
  }

  private async importTask(task: LearnNoteTask): Promise<void> {
    try {
      const result = await this.plugin.importer.importTask(task);
      new Notice(result.created ? "已导入 LearnNote 笔记" : "已同步 LearnNote 笔记，个人补充已保留");
      this.render();
    } catch (error) {
      new Notice(error instanceof Error ? error.message : "导入失败");
    }
  }

  private taskCard(container: HTMLElement, task: LearnNoteTask): void {
    const card = container.createDiv({ cls: `learnnote-task-card${task.id === this.selectedTaskId ? " is-selected" : ""}` });
    card.createEl("button", { text: task.title || "未命名任务", cls: "learnnote-task-title" })
      .addEventListener("click", () => void this.selectTask(task.id));
    const meta = card.createDiv({ cls: "learnnote-task-meta" });
    meta.createSpan({ text: task.source_type === "local" ? "本地视频" : "网页视频" });
    if (task.updated_at) meta.createSpan({ text: new Date(task.updated_at).toLocaleDateString() });
    if (this.plugin.importer.importedNote(task)) meta.createSpan({ text: "已导入", cls: "is-imported" });
    const actions = card.createDiv({ cls: "learnnote-task-actions" });
    const importButton = actions.createEl("button", {
      text: this.plugin.importer.importedNote(task) ? "同步" : "导入",
      cls: "mod-cta"
    });
    importButton.addEventListener("click", () => void this.importTask(task));
    const askButton = actions.createEl("button", { text: "提问" });
    askButton.addEventListener("click", () => void this.selectTask(task.id));
  }

  private citationText(result: QuestionResult): string {
    const citations = result.citations || [];
    if (!citations.length) return "";
    return citations.slice(0, 4).map(item => {
      const range = item.start !== undefined ? `${Math.floor(item.start)}s${item.end !== undefined ? `–${Math.floor(item.end)}s` : ""}` : "";
      return [item.label || item.source || "证据", range].filter(Boolean).join(" · ");
    }).join("；");
  }

  private questionPane(container: HTMLElement): void {
    const task = this.tasks.find(item => item.id === this.selectedTaskId);
    const pane = container.createDiv({ cls: "learnnote-question-pane" });
    pane.createEl("h3", { text: "问这节课" });
    pane.createEl("p", { text: task ? task.title : "先选择一篇已完成的 LearnNote 笔记", cls: "learnnote-question-context" });
    const conversation = pane.createDiv({ cls: "learnnote-conversation" });
    for (const item of this.history.slice(-8)) {
      if (item.question) conversation.createDiv({ text: item.question, cls: "learnnote-message is-user" });
      if (item.answer) conversation.createDiv({ text: item.answer, cls: "learnnote-message is-assistant" });
    }
    const input = pane.createEl("textarea", { attr: { placeholder: "根据字幕和画面证据提问…", rows: "3" } });
    const send = pane.createEl("button", { text: "发送", cls: "mod-cta learnnote-send" });
    send.disabled = !task;
    send.addEventListener("click", async () => {
      const question = input.value.trim();
      if (!task || !question) return;
      input.disabled = true;
      send.disabled = true;
      send.setText("正在回答…");
      try {
        const result = await this.plugin.api.question(task.id, question);
        this.history.push({ question, answer: result.answer, source: result.source, citations: result.citations });
        input.value = "";
        const citation = this.citationText(result);
        if (citation) new Notice(`回答依据：${citation}`);
      } catch (error) {
        new Notice(error instanceof Error ? error.message : "课程问答失败");
      } finally {
        input.disabled = false;
        send.disabled = false;
        send.setText("发送");
        this.render();
      }
    });
  }

  private renderTaskList(list: HTMLElement): void {
    list.empty();
    const needle = this.filter.trim().toLowerCase();
    const filtered = this.tasks.filter(task => task.title.toLowerCase().includes(needle));
    if (!filtered.length) {
      const empty = list.createDiv({ cls: "learnnote-empty" });
      empty.createEl("strong", { text: this.loading ? "正在读取任务" : "没有可导入的笔记" });
      empty.createEl("span", { text: "请先启动 LearnNote，并完成一个视频笔记任务。" });
      return;
    }
    for (const task of filtered) this.taskCard(list, task);
  }

  private render(): void {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("learnnote-view");
    const header = root.createDiv({ cls: "learnnote-view-header" });
    const heading = header.createDiv();
    heading.createEl("h2", { text: "LearnNote" });
    heading.createEl("small", { text: this.loading ? "正在连接本地客户端…" : `${this.tasks.length} 篇可导入笔记` });
    const refresh = header.createEl("button", { attr: { "aria-label": "刷新 LearnNote 任务" } });
    setIcon(refresh, "refresh-cw");
    refresh.addEventListener("click", () => void this.refresh());

    const search = root.createEl("input", {
      cls: "learnnote-search",
      attr: { type: "search", placeholder: "搜索 LearnNote 任务" },
      value: this.filter
    });
    const list = root.createDiv({ cls: "learnnote-task-list" });
    search.addEventListener("input", () => {
      this.filter = search.value;
      this.renderTaskList(list);
    });
    this.renderTaskList(list);
    this.questionPane(root);
  }
}
