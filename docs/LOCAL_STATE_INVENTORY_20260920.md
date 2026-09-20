# LearnNote 本地状态、保留清单与分支归档候选

更新时间：2026-09-20

工作目录：`D:\learnnote-assistant`

本清单只记录本地可恢复状态，不授权删除本地分支、配置、任务数据、浏览器配置或构建产物。

## 基线与远端状态

- `main` 与 `origin/main` 均为 `48a07412823a4ac25348ae96b509b6659d11249c`，工作区在开始本批工作时干净。
- `v0.2.13` tag 指向发布提交 `e93ac3da694c2806ab17530fe463bf499bdb5773`；当前 `main` 只比该发布提交多一条台账收口提交，不修改已发布 tag。
- GitHub 当前开放 issue API 快照为 31 个非 PR issue；另有唯一开放 PR #186。GitHub 的 issues API 会把 PR 作为 issue-like 条目返回，所以总对象数是 32，台账按“31 个 issue + 1 个独立 PR”记录。
- 当前唯一开放 PR 是 [#186](https://github.com/hurry060215-tech/learnnote-assistant/pull/186)。其 head 为 `f95bc32c`，相对当前 `main` 为 behind；GitHub checks 的两个安装 job 在 2026-09-16 失败，失败原因是 `pydantic==2.13.5` 要求 `pydantic-core==2.46.5`，而 PR 锁定了 `pydantic_core==2.49.0`。CodeQL 与 dependency-review 通过。
- 本地 `.venv` 当前为 `pydantic==2.13.5` + `pydantic-core==2.46.5`，`pip check` 通过；这只能证明当前旧环境自洽，不能证明 PR #186 的新锁可安装。

## 必须保留的本地内容

以下内容本批不删除、不移出工作区；`build/`、`dist/`、`.venv/` 和 `learnnote-config.json` 均被 `.gitignore` 排除，不会进入本次 Git 提交。

| 路径 | 观测内容 | 处理决定 |
| --- | --- | --- |
| `learnnote-config.json` | 65 bytes；当前只指向 `build/calm-ui-data` | 保留；不把本地路径配置提交到仓库 |
| `.venv/` | 本地 Windows Python 环境，约 627,741,410 bytes | 保留；测试和安装解析优先复用，必要时另建隔离环境 |
| `build/calm-ui-data/` | 约 1,683,265,376 bytes；含 tasks、courses、learning-spaces、materials、personal-notes、user-editions、SQLite 数据库、模型缓存和 webview profile | 保留任务数据、课程、学习空间、资料、个人笔记、模型缓存和数据库 |
| `build/calm-ui-data/webview-profile/` | Edge WebView 浏览器 profile；包含登录/站点/缓存数据库 | 保留为浏览器验收配置；禁止复制、上传或提交，后续共享证据必须脱敏 |
| `build/export-qa-0213/` | DOCX/PDF、20 页 PDF PNG、表格导出和渲染预览 | 保留，作为 v0.2.13 导出证据；后续长文档验收以副本运行 |
| `build/release-verify-0213-small/` | extension ZIP、resolved requirements、SBOM、build source、SHA256 | 保留，作为发布验收来源；不把历史资产改写为当前发布证据 |
| `build/pr186-pip-resolution-20260920.json` | 1,056,105 bytes；兼容 lock 的 pip dry-run 解析报告 | 保留为本批依赖证据；SHA-256 `668D18F71AA8A41F29603F2F5136B2D07F59165CD3F8309D9CD4610DF1E3C118` |
| `build/extension-verify-0213-20260920.zip` | 146,622 bytes；当前分支重新打包的 v0.2.13 扩展 | 保留为本批打包证据；17 files，SHA-256 `0F8DC7FD474AB10CBF33EA6CA8246AC12854689E21C2A79C2B06085FFF50CACF` |
| `build/learnnote-local-refs-20260920-final.bundle` | 12,036,913 bytes；包含本批提交在内的本地 refs 可恢复 Git bundle | 保留为分支历史归档；SHA-256 `4FDFF58EAD5D3F7027AC01AB8019F0FAED2ADD7DC17B217C58FB38FA84B53108` |
| `build/reliability-ad-local/` | 本地可靠性报告、synthetic subtitle、media、task data | 保留，标注为旧提交/旧时长证据 |
| `build/reliability-ad-local-3600/` | 3600 秒可靠性报告、media、task data | 保留；当前提交未重跑前不得称为当前 60 分钟通过 |
| `build/scheduler-reliability-ad-local/` | scheduler 可靠性报告和独立 data | 保留；供 #130/#132 复核，不覆盖当前失败门禁 |
| `dist/LearnNote-Browser-Extension.zip` | 147,353 bytes；v0.2.13 扩展包 | 保留；重新打包后与本文件记录的版本分开核验 |
| `node_modules/` | 当前目录存在但无已登记文件 | 保留开发环境目录，不将其作为测试证据 |

### 本地数据分类

- 需要保护的用户/验收状态：`build/calm-ui-data/tasks/`、`courses/`、`learning-spaces/`、`materials/`、`personal-notes/`、`user-editions/`、各 SQLite 数据库。
- 需要保护但不得外发的浏览器状态：`build/calm-ui-data/webview-profile/`、`model-connection.json`、`config/` 下的用户配置。报告只引用路径、版本和脱敏摘要。
- 可作为历史证据的生成物：`build/export-qa-0213/`、`build/release-verify-0213-small/`、三个 reliability 目录。
- 未来可在明确批准后清理的重复/缓存候选：`build/calm-ui-data/temp/`、`pip-cache/`、`webview-profile` 中可再生缓存、旧 reliability 运行的重复 media。清理前必须先核对任务数、来源数、卡片数、报告和校验值；本批不执行。

## 本地分支台账

数字格式为 `behind/ahead`（相对当前 `main`）；`patch-equivalent` 是 `git cherry main <branch>` 可在当前主线找到的等价提交数，`unique` 是仍未找到等价补丁的提交数。分叉不等于未合并：squash 合并会导致 ancestry 仍分叉，所以候选清理必须同时看 PR 和 patch 结果。

| 本地分支 | behind/ahead | patch-equivalent / unique | 关联公开 PR | 当前决定 |
| --- | ---: | ---: | --- | --- |
| `codex/acceptance-fixes-029` | 8/13 | 0/13 | 未作为当前 PR head 返回 | 保留，需复核 update center、队列公平性、学习范围、OCR、可靠性和编码提交是否已由后续 squash 覆盖 |
| `codex/assistant-stream-video` | 13/2 | 0/2 | #169 merged | 保留至 #151/#139 证据链核对完成 |
| `codex/captions-fast-path` | 6/7 | 0/7 | #184 merged | 保留至 v0.2.10 历史证据归档完成 |
| `codex/dependency-pr-cleanup` | 5/1 | 1/0 | #185 merged | 归档候选；保留恢复引用后再删分支 |
| `codex/freeform-issues` | 10/1 | 1/0 | #173 merged | 归档候选；PR 已 squash 合并 |
| `codex/grounding-name-recovery` | 4/1 | 0/1 | 未作为当前 PR head 返回 | 保留，唯一提交需确认是否已有后续实现覆盖 |
| `codex/issue-roadmap-20260912` | 8/10 | 0/10 | 未作为当前 PR head 返回 | 保留；其中的可靠性、OCR、编码和台账内容需迁移到本文件及当前台账后再处理 |
| `codex/learnnote-workspace-redesign` | 14/15 | 0/15 | #165 merged | 保留；历史工作台、字幕、取消和本地激活差异较大，不能仅凭 squash 状态清除 |
| `codex/product-027` | 12/1 | 1/0 | #170 merged | 归档候选；PR 已 squash 合并 |
| `codex/product-completion-027` | 12/0 | 0/0 | 未作为当前 PR head 返回 | 归档候选；没有相对当前主线的独有补丁 |
| `codex/readable-ui-release` | 8/15 | 0/15 | #182 merged | 保留；含 0.2.9 UI、可靠性和验收提交，需与 #130–#153 当前证据对照 |
| `codex/release-0210-verified` | 4/0 | 0/0 | 未作为当前 PR head 返回 | 归档候选；没有相对当前主线的独有补丁 |
| `codex/release-029-verified` | 6/0 | 0/0 | 未作为当前 PR head 返回 | 归档候选；没有相对当前主线的独有补丁 |
| `codex/release-rebuild` | 7/1 | 1/0 | #183 merged | 归档候选；PR 已 squash 合并 |
| `codex/restore-issue-forms` | 9/1 | 1/0 | #174 merged | 归档候选；PR 已 squash 合并 |
| `codex/trust-and-learning-20260906` | 15/1 | 1/0 | #164 merged | 归档候选；PR 已 squash 合并 |
| `codex/local-state-and-deps-20260920` | 0/0 | 0/0 | 本批工作分支 | 保留至本批验收完成 |

### 归档规则

1. 归档候选不是删除许可。删除前必须保存分支名、tip SHA、关联 PR、`git cherry` 结果和可恢复归档。
2. 有 `unique > 0` 的分支暂不列为删除候选；先逐个对照当前 issue 批次和 squash PR 的最终 diff。
3. 已 squash 合并但没有独有补丁的分支（`dependency-pr-cleanup`、`freeform-issues`、`product-027`、`product-completion-027`、`release-0210-verified`、`release-029-verified`、`release-rebuild`、`restore-issue-forms`、`trust-and-learning-20260906`）只进入可恢复归档候选，不在本批删除。
4. 远端当前还保留 `origin/codex/closeout-ad-0212`、`origin/codex/complete-ej-browser`、`origin/dependabot/pip/backend/python-runtime-b03b90fc7e`；远端分支状态与本地分支删除必须分开处理。

## 本批依赖决策

以当前 `main` 重新解析 #186 的 9 个升级项：接受 anyio、huggingface-hub、jiter、onnxruntime、pyinstaller、pypdf、tqdm、tzdata；拒绝单独升级 `pydantic-core`，因为当前 `pydantic==2.13.5` 的元数据精确要求 `pydantic-core==2.46.5`。直接依赖和 Windows lock 同步 `pypdf==6.18.1`，其余接受的版本写入 Windows lock；不修改已发布 tag。

安装解析、`pip check`、受影响后端测试和打包检查结果：`build/pr186-pip-resolution-20260920.json` 的 dry-run 解析退出码 0；本地 `pip check` 通过；后端全量 588 tests、脚本 60 tests、桌面 45 tests 均通过；扩展 v0.2.13 打包校验通过（17 files，SHA-256 `0f8dc7fd474ab10cbf33ea6ca8246ac12854689e21c2a79c2b06085fff50cacf`）。这些是当前本地分支证据，#186 仍需同一提交的 GitHub CI 后才能关闭，不能把本地通过写成远端已恢复。
