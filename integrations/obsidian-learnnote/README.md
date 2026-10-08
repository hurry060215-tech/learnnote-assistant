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

### Moment 开发依赖修复

Obsidian API 类型包 1.13.1 固定依赖 Moment 2.29.4，受
[GHSA-4p3w-j4w9-5jqw](https://github.com/moment/moment/security/advisories/GHSA-4p3w-j4w9-5jqw)
影响：在 Node.js 中把攻击者控制的非字符串值传给 `moment.locale()` 时可能加载非预期路径。
最低修复版本是 2.31.0。

截至 2026-10-08，本次检查的 npm 注册表仍只发布到 Obsidian 1.13.1；
[上游 API 源码](https://github.com/obsidianmd/obsidian-api/blob/master/package.json)
已经采用 Moment 2.31.0，但相应新版尚不能从注册表安装。因此这里保留已验证的
Obsidian 1.13.1，只对该版本的 Moment 子依赖做 2.31.0 覆盖，不升级插件 API 或 CodeMirror。
上游发布可安装的修复版本后，应优先更新 Obsidian 类型包并移除该覆盖，再运行 `npm run verify`。

这是开发依赖修复。插件源码不调用 Moment，生产打包保留宿主提供的 `obsidian`，
不会打包 Moment，也不会外部引入它。测试会检查实际依赖解析及生产构建的输入/导入清单。
此修复不更新用户已安装的 Obsidian 应用或其内部 Moment，也不代表宿主已通过安全审计。
