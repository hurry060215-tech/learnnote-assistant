# 学习数据副本迁移恢复验收

可重复执行命令：

```
.venv/Scripts/python.exe scripts/audit-learning-copy.py --source-data build/calm-ui-data --output-dir build/learning-copy-NEW
```

输出目录必须不存在且与源数据目录互不包含。脚本通过 SQLite 在线备份和指定子目录副本执行验收，原始数据库以只读方式打开，不复制模型配置、浏览器 profile 或媒体文件；副本包含用户资料，只留在本机。

2026-09-20 已完成两种本地运行：

| 场景 | 结果 |
| --- | --- |
| 当前资料的完整引用副本 | 2 张卡、4 条评分历史、3 个空间；重复恢复后来源数、卡片数、FSRS 状态与评分历史一致 |
| 构造的旧版布局副本（创建副本时不复制 learning-spaces） | 首次迁移 1 个课程，再次迁移 0 个；恢复后 2 个空间；原有卡片/评分历史不变 |
| 原始文件保护 | 两次运行均核对输入文件 SHA-256 未变化 |

报告保存在 build/learning-copy-20260920/report.json 和 build/learning-copy-legacy-20260920/report.json。第二种场景明确是用真实资料副本构造的旧版目录，不是独立采集的旧版本安装环境。

范围限制：只有当前 2 张卡与 4 条评分历史；缺失来源、更多版本、跨平台迁移和完整备份恢复仍需更广样本，不据此关闭全部学习空间/迁移 issue。
