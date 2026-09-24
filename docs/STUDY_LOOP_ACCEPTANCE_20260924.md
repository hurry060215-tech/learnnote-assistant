# 学习闭环验收

- 日期：2026-09-24
- 基线：`origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
- 本次验收代码 commit：待提交后填入
- 关联 Issue：[#136](https://github.com/hurry060215-tech/learnnote-assistant/issues/136)、[#140](https://github.com/hurry060215-tech/learnnote-assistant/issues/140)、[#141](https://github.com/hurry060215-tech/learnnote-assistant/issues/141)、[#159](https://github.com/hurry060215-tech/learnnote-assistant/issues/159)

## 改动

- 默认工作台的批注区会显示失效锚点，允许编辑、重新选择当前正文、修复引用或删除。只编辑批注文字会保留旧 anchor revision，不会静默把旧引用标成新出处。
- 默认工作台和复习视图在显示卡片答案前提供可跳过的自我解释步骤。选择记录后只保存一次本地 `self_assessment` 活动，不保存回答文本，也不发送给模型。
- 学习计划页显示近 14 天阅读、作答、自我解释、复习计数和本地卡片掌握分布；待复习卡片仍逐张显示对应证据出处。
- 新增 `/api/study/backup` 和 `/api/study/backup/restore`，备份包含卡片、评分历史、原始活动事件、计划 IANA timezone、个人批注和用户编辑版本。restore 会校验 FSRS/备份版本、记录数量和内容 hash，再做幂等合并；已有评分、同 ID 批注和同来源编辑不会被覆盖。最大备份大小为 100 MB。
- 两个工作台都提供学习备份的导出与导入入口，恢复需要用户选文件并确认。

学习备份不包含源 PDF/视频/字幕、资料库 SQLite 索引、课程学习空间与其自定义练习、社区观点或模型连接凭据；这些数据仍需通过各自已有的导出和本地数据恢复路径还原。原始来源需先回到本机，个人批注才能重新显示并回源。

## 连续验收

新增隔离 TestClient 集成测试使用临时数据目录，在 FastAPI HTTP 层执行：

1. 导入并阅读 Markdown 资料，选择含正文的 evidence anchor。
2. 生成并确认 evidence-backed 卡片，确认 quiz queue 不返回答案正文。
3. 打开出处，记录作答、自我解释活动和“重来”评分。
4. 修改个人版资料、添加引用原文的个人批注，重导入相同资料后检查批注仍挂在相同内容哈希上。
5. 导出学习备份；切换到空学习数据目录；恢复后检查 Asia/Shanghai、编辑稿、批注、错题和评分历史均保留。
6. 重复导入同一备份，确认没有重复评分/活动/批注，且之后修改的本地批注与编辑不会被旧备份覆盖。
7. 将 FSRS 算法篡改为未知版本，确认恢复返回 422 且已恢复数据保持不变。

这条连续路径真实调用本地 HTTP API；输入是构造的 Markdown，无登录资料、远程模型或云服务。它不是浏览器指针自动化，也没有使用远程模型。

## 验证

- Python 3.12.10 / Windows：完整后端套件 610 项通过（98.7 秒）。
- `scripts/tests`：71 项通过。
- `web/tests/*.test.mjs` 全部通过；`web/desk.js`、`web/desk-tools.js`、`web/learning.js`、`web/personal-notes.js` Node 语法检查通过。
- 架构检查、i18n 审计和 `git diff --check` 通过。

详细日志存于忽略目录 `build/package5`，没有复制或读取用户原有资料。

## 剩余边界

- #136：时区/DST/恢复自动回归通过；浏览器首次时区建议和实际跨时区交互仍需指针验收。
- #140：批注/编辑稿的本地备份恢复已验证；Obsidian 双向同步、含原媒体的完整恢复和大量孤立 anchor 修复仍未验收。
- #141：卡片由本地来源片段生成，当前没有自由文本答案评分，也不持久化自我解释文本；真实课程人工标注题库仍需独立验收。
- #159：今日目标、复习、错题、掌握、证据回源、学习备份入口均已接通；390/768/1440、键盘和浏览器完整操作验收仍待完成。

因此四个 Issue 继续开放。此包证明了本地学习闭环的数据和 API 可连续工作，但不替代浏览器视觉验收、Obsidian 同步或真实课程题目质量评估。
