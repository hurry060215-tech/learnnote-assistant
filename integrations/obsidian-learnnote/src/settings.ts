import { Notice, PluginSettingTab, Setting } from "obsidian";
import type LearnNotePlugin from "./main";

export class LearnNoteSettingTab extends PluginSettingTab {
  constructor(private readonly plugin: LearnNotePlugin) {
    super(plugin.app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "LearnNote Assistant" });
    containerEl.createEl("p", {
      text: "连接本机 LearnNote，将完成的视频笔记、字幕和视觉窗口同步到当前 Vault。",
      cls: "learnnote-settings-intro"
    });

    new Setting(containerEl)
      .setName("本地服务地址")
      .setDesc("LearnNote 桌面客户端默认使用 http://127.0.0.1:8765")
      .addText(text => text
        .setPlaceholder("http://127.0.0.1:8765")
        .setValue(this.plugin.settings.backendUrl)
        .onChange(async value => this.plugin.updateSettings({ backendUrl: value.trim() }))
      )
      .addButton(button => button
        .setButtonText("测试连接")
        .onClick(async () => {
          try {
            const health = await this.plugin.api.health();
            new Notice(`已连接 LearnNote v${health.app_version || "unknown"}`);
          } catch (error) {
            new Notice(error instanceof Error ? error.message : "无法连接 LearnNote");
          }
        })
      );

    new Setting(containerEl)
      .setName("笔记目录")
      .setDesc("每个 LearnNote 任务会在该目录下创建独立文件夹")
      .addText(text => text
        .setPlaceholder("LearnNote")
        .setValue(this.plugin.settings.targetFolder)
        .onChange(async value => this.plugin.updateSettings({ targetFolder: value.trim() || "LearnNote" }))
      );

    new Setting(containerEl)
      .setName("导入带时间戳字幕")
      .setDesc("生成可读的 Transcript.md，并保留原始字幕文件")
      .addToggle(toggle => toggle
        .setValue(this.plugin.settings.includeTranscript)
        .onChange(async value => this.plugin.updateSettings({ includeTranscript: value }))
      );

    new Setting(containerEl)
      .setName("导入画面与时间轴")
      .setDesc("保存关键帧网格、视觉索引和 visual_windows.md")
      .addToggle(toggle => toggle
        .setValue(this.plugin.settings.includeVisualWindows)
        .onChange(async value => this.plugin.updateSettings({ includeVisualWindows: value }))
      );

    new Setting(containerEl)
      .setName("导入课程问答记录")
      .setDesc("同步 LearnNote 中已有的问答历史")
      .addToggle(toggle => toggle
        .setValue(this.plugin.settings.includeQaHistory)
        .onChange(async value => this.plugin.updateSettings({ includeQaHistory: value }))
      );

    new Setting(containerEl)
      .setName("导入资料清单")
      .setDesc("保留 manifest.json 和任务审计信息")
      .addToggle(toggle => toggle
        .setValue(this.plugin.settings.includeManifest)
        .onChange(async value => this.plugin.updateSettings({ includeManifest: value }))
      );

    new Setting(containerEl)
      .setName("导入后打开笔记")
      .setDesc("同步完成后自动打开 LearnNote.md")
      .addToggle(toggle => toggle
        .setValue(this.plugin.settings.openAfterImport)
        .onChange(async value => this.plugin.updateSettings({ openAfterImport: value }))
      );
  }
}
