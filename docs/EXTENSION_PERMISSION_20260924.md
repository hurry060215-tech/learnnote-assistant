# 扩展权限与配对工作包验收

* 日期：2026-09-24
* 代码基线：`origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
* 对应 Issue：[#135](https://github.com/hurry060215-tech/learnnote-assistant/issues/135)、[#55](https://github.com/hurry060215-tech/learnnote-assistant/issues/55)
* 正式版本基准：扩展和本机后端 `0.2.14`；扩展协议 `1`

## 用户问题与改动

用户打开侧栏时，页面线索可能触发本机预检；站点授权被撤销后，已经排队的字幕注入或媒体捕获也可能把旧结果带回来。

- 未获得当前站点权限前，侧栏不向本机预检发送页面候选。用户点击发送后才请求该站点权限；拒绝时不创建任务。
- 后台在页面读取前、Cookie 读取后和向本机后端发送前重新检查站点权限。撤权会清理页面/媒体缓存、捕获状态和诊断日志，并通知仍打开的侧栏清除页面线索；已经交给本机的任务保留，并明确显示仍可查看或取消。
- 授权匹配按协议和主机名判断，不受非默认端口影响；来自已撤销捕获的迟到消息和字幕结果不会恢复旧页面线索。
- 站点权限面板使用中英文数据流文案，区分发往本机服务的 Cookie 与可能发给模型的字幕/画面。仅字幕模式不读取 Cookie。
- 发现本机 LearnNote 健康检查可达但协议版本不匹配时，侧栏明确显示两端协议号和更新提示；不会把它误报为“客户端未启动”。
- 扩展 smoke 将浏览器 profile 和日志放在 `LEARNNOTE_DATA_DIR` 下，关闭浏览器后删除本轮新建的临时 profile。配对验收现在会比较后端与扩展协议版本，不匹配即失败。

Manifest 版本和既有可选权限未扩大；旧任务仍可在本机工作台查看或取消。当前验收未迁移或读取旧用户数据。

## 可复现证据

| 检查 | 输入与环境 | 结果 |
| --- | --- | --- |
| 扩展回归 | `extension/tests/*.test.mjs`，Node.js 24.16.0 | 58 项通过，含拒绝授权、显式授权、撤权清理、迟到字幕竞态、端口匹配和协议不兼容提示。输出：`build/qa-package2-20260924/final-verification-3/extension-tests.log`。 |
| 脚本回归 | `python -m unittest discover -s scripts/tests -v`，项目 Python 3.12 虚拟环境 | 74 项通过。输出：`build/qa-package2-20260924/final-verification-2/scripts-tests.log`。 |
| 后端协议/任务回归 | `backend/tests/test_task_management.py`、`backend/tests/test_api_pipeline.py` | 77 项通过；含心跳版本兼容和旧任务恢复等合同。输出：`build/qa-package2-20260924/final-verification-2/backend-protocol-tests.log`。 |
| Edge 浏览器 smoke | Microsoft Edge `153.0.4234.48`；临时 profile、本机媒体样例、本机后端 | 心跳显示扩展 `0.2.14` / 协议 `1`；MP4、HLS、播放器 POST API、通用播放器 API、Blob iframe 和学习通 mock 通过；侧栏创建本机任务成功。输出：`build/qa-package2-20260924/final-verification-3/edge-e2e.log`。 |
| Chrome 浏览器 smoke | Google Chrome for Testing `154.0.8037.57`；临时 profile、本机媒体样例、本机后端 | 与 Edge 同一条媒体和任务矩阵通过；扩展 `0.2.14` / 协议 `1`。测试浏览器下载/解压于工作区隔离目录，没有安装到系统。输出：`build/qa-package2-20260924/final-verification-3/chrome-cft-e2e.log`。 |
| Chrome Stable 启动限制 | 本机 Google Chrome `153.0.8010.53` | 官方品牌版忽略 `--disable-extensions-except`，因此未加载扩展。证据日志保存在 `build/qa-package2-20260924/chrome-stable-diagnostic/test-runs/e2e-logs/chrome-extension-browser.log`。Chrome 说明自 M137 移除 `--load-extension`、自 M139 移除 `--disable-extensions-except`；应使用 Chrome for Testing 进行此类扩展自动化。该次启动失败不记作产品路径失败或通过。 |
| 候选包 | `extension/manifest.json` 声明版本 `0.2.14` | Store ZIP 校验通过，17 个包文件；SHA-256：`4e62db10a84f261cd184c5192ae81bb0bddd2cbbde9a8248abfe57c3f8851883`。 |

扩展回归可从仓库根目录复现：

```powershell
Get-ChildItem extension/tests/*.test.mjs | ForEach-Object { node $_.FullName }
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -v
```

Chrome for Testing smoke：

```powershell
$env:LEARNNOTE_E2E_BROWSER = '<Chrome for Testing 解压目录>\chrome-win64\chrome.exe'
$env:LEARNNOTE_DATA_DIR = '<独立临时数据目录>'
& .\.venv\Scripts\python.exe scripts/e2e-extension-smoke.py --browser chrome --backend-port 0 --samples-port 0 --debug-port 0
```

真实浏览器输入是本地构造的媒体与播放器样例，未使用真实课程、私人 Cookie、登录态或远程模型。学习通 mock 只设置本地模拟 Cookie。Chrome for Testing/Edge 开发态扩展加载只证明浏览器自动化和本机配对链路，不代表 Chrome Web Store 安装。

## 权限矩阵与剩余边界

自动回归已覆盖站点授权被拒绝时不预检、不创建任务；模拟明确授权后允许用户发起任务；撤权事件清除活动侧栏线索；后台在捕获异步边界重验权限并丢弃旧字幕。真实 Chrome 和 Edge smoke 验证了可选权限之外的本机来源、扩展心跳、协议兼容和任务交接。

本轮没有实际点击 Chrome 原生站点权限弹窗的“允许/拒绝/撤销/重新授权”完整矩阵；运行在 localhost 样例上，而 localhost 本来就属于扩展的本机后端 host permission。也未从 Chrome Web Store 安装扩展或验证真实用户升级。因此 #135 保持开放，建议完成普通 Chrome 用户配置下的权限弹窗/站点设置矩阵后再关闭；#55 继续保持开放，商店安装、审核与发布状态另行验收。

候选包位于 `build/qa-candidates/LearnNote-Browser-Extension-v0.2.14-pkg2-final3-20260924.zip`。本轮未上传商店、提交审核或发布 Release。
