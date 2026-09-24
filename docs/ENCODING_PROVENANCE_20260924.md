# 编码来源与手动重选工作包验收

* 日期：2026-09-24
* 代码基线：`origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
* 对应 Issue：[#150](https://github.com/hurry060215-tech/learnnote-assistant/issues/150)
* 分期：工作包 3A（编码导入链路）；#129 claim 证据评估和 #152 笔记结构规范另列后续 PR

## 本轮改动

- 统一文本解码会优先使用 BOM，再使用 MIME 或 HTML meta 声明，然后严格 UTF-8，最后才尝试受限字符集检测/回退。用户手动选择的字符集作为显式覆盖，但仍要求严格解码并经过 mojibake 检查。
- 解码 provenance 记录选中的编码、来源类别、声明编码、替换字符数、原字节 SHA-256 / 长度和 Unicode 规范化版本。`encoding_confidence` 是来源方法的类别（high / medium / low / user_selected），不是经过校准的统计概率。
- 本地 TXT / Markdown / HTML 导入路由接受 `encoding` multipart 字段；默认工作台和 classic 导入页都提供自动识别、UTF-8、GB18030/GBK、Big5、Shift_JIS 和 UTF-16 LE/BE。PDF 不显示字符集选择，由 PDF 文本提取器处理。
- 阅读页显示文档使用的编码及来源。重新导入同一原始文件时，如果用户选的编码与已入库版本不同，界面明确告知本次选择没有覆盖原材料。
- 页面媒体扫描、文本响应和 HLS/DASH manifest 解析改用严格解码；不能无损解码时跳过/阻断对应解析并给出结构化状态，不再把坏字节静默删除或替换后继续解析。Content-Disposition 文件名解码遇到非法字节时不生成替换字符文件名。
- 原始上传字节仍保存在本机，可通过 SHA-256 和字节长度核对；没有将资料发送到远程模型。

## 验收证据

| 检查 | 输入与环境 | 结果 |
| --- | --- | --- |
| 解码与导入回归 | `backend/tests/test_encoding_provenance.py` | 8 项通过：MIME 声明、UTF-16 BOM 优先、HTML meta charset、手动 GB18030、非法 UTF-8 阻断、Content-Disposition 非法字节，以及实际资料导入/读取。 |
| 现有 Unicode、知识库和资料库回归 | `test_pipeline_speed_unicode.py`、`test_knowledge.py`、`test_library.py`、`test_source_input.py` | 共 50 项通过，包含 UTF-8/UTF-16/GB18030/Shift_JIS、原始字节 SHA、乱码修复/阻断、PDF/Markdown/HTML 导入与旧任务标题兼容。 |
| downloader 页面/manifest 回归 | `backend/tests/test_downloader_priority.py` | 58 项通过；页面响应和 HLS/DASH 解析路径使用无损解码后仍保留现有媒体候选识别。 |
| 后端全量回归 | `python -m unittest discover -s tests -v`，项目 Python 3.12 虚拟环境，`PYTHONPATH=D:\learnnote-assistant-pkg3` | 615 项通过。首次未设仓库根 `PYTHONPATH` 时，13 项桌面凭据测试报 `ModuleNotFoundError: desktop`；按仓库根配置重跑后全量通过。最终输出：`build/qa-package3-20260924/final-verification/backend-tests-final.log`。 |
| 脚本回归 | `python -m unittest discover -s scripts/tests -v` | 73 项通过，含默认/Classic 两种导入界面的字符集控件合同。最终输出：`build/qa-package3-20260924/final-verification/scripts-tests-final2.log`。 |
| 字符集和 UI 静态检查 | `scripts/audit-i18n.py`、`node --check web/desk.js`、`node --check web/app.js`、相关 Python `py_compile` | 全部通过；中英文资源 key 对齐。 |
| 实际浏览器用户路径 | Google Chrome `153.0.8010.53`，全新临时 profile、本地 FastAPI、构造的 GB18030 TXT | 从首次页面打开“新建笔记”→“本地文件”→选择 GB18030→导入→在阅读页看到完整中文并显示“手动选择”来源信息，完整通过。命令输出：`build/qa-package3-20260924/final-verification/document-import-e2e-final.log`；证据数据保存在 `build/qa-package3-encoding-20260924/data-final-check`；profile 在结束后清除。 |

可复现的关键命令：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -v
& .\.venv\Scripts\python.exe scripts/audit-i18n.py
node --check web/desk.js
node --check web/app.js
```

全量后端测试要从 `backend` 目录运行，并设置 `PYTHONPATH` 为仓库根目录，以便桌面层测试导入 `desktop.credentials`。

## 剩余边界与 Issue 建议

- 资料库对同一原始字节会去重。若材料已经导入，随后选择另一种编码，当前实现会显式提示未覆盖旧材料；库材料的安全重解码、历史 evidence anchor / 个人批注失效提示尚未接入 UI。保留旧材料避免静默覆盖，#150 继续开放。
- PDF 文本使用 pypdf 提取，扫描页 OCR 仍是独立路径；Word/PDF/Obsidian 导出一致性还需要按 #156 的混排样本验收。
- 自动检测的 medium / low 只是来源方法分类，不表示文本语义正确；混合语言短文本和不同版本 charset-normalizer 的行为仍需要固定样本集。
- 本轮未关闭 #150；#129 的 claim-level 人工 gold corpus / confusion report，以及 #152 的语义结构门禁尚未开始。不要把已有 80 条构造断言计作语义准确率。

本轮输入为构造的 GB18030 样例和本地测试夹具，没有读取私人资料、Cookie 或原有任务；没有调用模型、上传商店、提交审核或发布 Release。
