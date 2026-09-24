# Claim 证据状态公开样本评估

* 日期：2026-09-24
* 代码基线：`origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
* 本次验收代码 commit：`fc7357b66382cd4d3535ea900c9ae17f472e1b4d`
* 对应 Issue：[#129](https://github.com/hurry060215-tech/learnnote-assistant/issues/129)
* 数据文件：`backend/tests/fixtures/claim_evidence_public_gold_20260924.json`
* 评估入口：`scripts/claim-evidence-benchmark.py`

## 数据与标注

样本来自 12 个公开的一手技术文档章节：Python 3.12 官方教程/标准库、Unicode UAX #15 和 IETF RFC 9110。语料中的 evidence 句子是人工概括，不复制整段原文；每条记录保留具体来源 URL、章节定位、语言、风险类别和人工 gold 状态。输入由字幕式和文档式证据片段构成，全部可离线重跑，不会访问这些网址。

每个来源包含 5 种独立手写 claim：直接支持、可定位的实质矛盾、明确推断、无关待核对内容，以及一个语义可支持但没有逐字对应的 paraphrase。共 60 条（英文 30、中文 30），覆盖术语实体、数值、否定、因果/顺序、条件、字符串规范化和 HTTP 状态语义。

## 结果

`python scripts/claim-evidence-benchmark.py --output <report.json>` 输出完整 JSON；CI 默认打印摘要。当前验证代码产生的混淆矩阵如下：

| 人工 gold \ 系统状态 | 直接支持 | 仅定位 | 推断 | 待核对 |
| --- | ---: | ---: | ---: | ---: |
| 直接支持 | 12 | 10 | 2 | 0 |
| 仅定位 | 0 | 12 | 0 | 0 |
| 推断 | 0 | 0 | 12 | 0 |
| 待核对 | 0 | 0 | 0 | 12 |

在这个固定集合上，直接支持 precision 为 1.00、recall 为 0.50；review gate 的 precision 为 0.75、recall 为 1.00；待核对类 precision/recall 均为 1.00。当前保守规则没有把不一致样本标成直接支持，同时有 12 条人工作为直接支持的释义被降级为“仅定位”或“推断”，需要人工核对。报告中的 0.80 状态分类一致率仅描述这 60 条固定样本，**不代表真实课程或自然语言语义准确率**。

原有 [EVIDENCE_CORPUS_20260920.md](EVIDENCE_CORPUS_20260920.md) 的 20 条构造 source、80 次投影断言仍是回归夹具；它与本公开来源 gold 集分开报告，不能把 80 次断言称为 80 个独立真实样本。

## 代码变化与边界

- Claim map schema 升至 v5，新增文档证据输入，并按直接匹配、候选定位、推断、待核对区分状态。v4 的字幕/画面映射保留现有 evidence ID 与状态，仅做兼容投影；更旧的字符串/时间戳映射继续降级为待复核。
- 阅读状态卡片直接显示四类 verification 状态和字幕/画面/文档来源类型；文档证据能打开本地资料，并尝试定位到页码或来源片段。
- 直接逐字证据只表示“来源文本直接支持该表述”，不证明来源文档或课程本身的事实为真。
- 该评估使用公共技术文档和人工概括，不是带登录态课程或真实课堂字幕。生产任务的 claim evidence 生成仍主要接在视频转录和视觉窗口；文档 claim map 的完整生产流、真实课堂样本、批注/导出联动都未验收。因此 #129 保持开放。

运行命令：

```powershell
$env:PYTHONPATH='D:\learnnote-assistant-pkg3b\backend;D:\learnnote-assistant-pkg3b'
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' scripts/claim-evidence-benchmark.py --output build\claim-evidence-public-report.json
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' -m unittest discover -s backend\tests -v
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' -m unittest discover -s scripts\tests -v
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' scripts\check-architecture.py
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' scripts\audit-i18n.py
node --check web\desk.js
```

在 Python 3.12.10 / Windows 的当前 PR 候选代码上，后端完整套件为 611 项通过（93.8 秒），脚本套件 72 项通过；架构检查和中英文资源审计通过，JS 语法检查通过。首次全量尝试缺少 `backend` 根目录的 `PYTHONPATH`，造成 5 个导入错误和 2 个子进程测试失败；设置正确路径后完整重跑通过。CI PR 检查仍需远端完成。工作台 UI 只做状态文案/导航契约检查；因产品任务尚未生成文档 claim map，本轮没有声称真实文档任务的浏览器端到端验收。

主要公开来源：

- [Python 3.12 Data Structures](https://docs.python.org/3.12/tutorial/datastructures.html)
- [Python 3.12 Built-in Functions](https://docs.python.org/3.12/library/functions.html)
- [Python 3.12 Built-in Types](https://docs.python.org/3.12/library/stdtypes.html)
- [Unicode UAX #15, version 58](https://www.unicode.org/reports/tr15/tr15-58.html)
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
