# LearnNote Assistant for Obsidian

把 LearnNote 已完成的视频笔记导入 Obsidian，并保留字幕、关键画面、问答记录和任务来源。

## 能做什么

- 浏览本机 LearnNote 中已完成的任务。
- 一键导入或同步结构化 Markdown 笔记。
- 可选同步带时间戳字幕、视觉窗口、关键帧网格和问答记录。
- 在 Obsidian 侧栏围绕课程继续提问，回答仍由本机 LearnNote 后端生成。
- 重复同步只更新 LearnNote 生成区，不覆盖 `我的补充` 下的个人内容。

## 使用条件

1. 安装并启动 LearnNote Windows 客户端。
2. 本机服务可访问 `http://127.0.0.1:8765/api/health`。
3. 使用 Obsidian 桌面版。移动端无法连接电脑的本机 LearnNote 服务。

## 手动安装

运行插件目录中的 `npm install && npm run build`，然后把以下文件复制到 Vault：

```text
<Vault>/.obsidian/plugins/learnnote-assistant/
  manifest.json
  main.js
  styles.css
```

在 Obsidian 的 `设置 -> 第三方插件` 中启用 **LearnNote Assistant**。

## 使用

1. 点击左侧功能区的 LearnNote 图标。
2. 从已完成任务中选择 `导入`。
3. 在生成的 `LearnNote.md` 下继续补充个人笔记。
4. 视频笔记更新后点击 `同步`；个人补充不会被覆盖。
5. 选中任务后，可在侧栏直接围绕字幕与画面证据提问。

默认导入到：

```text
LearnNote/<视频标题>--<任务 ID>/
```

目标目录和同步内容可在 Obsidian 的 LearnNote 设置页修改。

## 本地边界

插件只允许连接 `localhost`、`127.0.0.1` 或 `::1`。它不会读取浏览器 Cookie，也不自行下载视频；视频处理和模型调用均由 LearnNote 客户端负责。

## 开发

```powershell
cd D:\Projects\learnnote-assistant\integrations\obsidian-learnnote
$env:npm_config_cache = 'D:\LearnNoteBuildCache\npm-cache'
npm install
npm run verify
```

当前插件以源码随 LearnNote 仓库发布，尚未进入 Obsidian 官方社区插件目录。
