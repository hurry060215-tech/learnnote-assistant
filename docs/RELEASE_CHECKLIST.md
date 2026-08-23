# v0.1.55 发布收口清单

当前代码与门禁已准备好；下面两步必须由有仓库 Code Owner 权限的账号完成，不能由 CI 代替。

## 合并前

- [ ] 在 [PR #49](https://github.com/hurry060215-tech/learnnote-assistant/pull/49) 完成 Code Owner review。
- [ ] 确认 required checks、CodeQL、Dependency Review、Obsidian verify 全部通过。
- [ ] 检查 `APP_VERSION`、扩展 manifest、安装器、Docker 默认 tag、Release Notes 和官网下载链接均为 `0.1.55`。
- [ ] 确认没有把本地 Cookie、模型 Key、`data/` 任务产物或签名 URL 提交到仓库。

## 合并后

```powershell
git checkout main
git pull --ff-only origin main
git tag -a v0.1.55 -m "LearnNote v0.1.55"
git push origin v0.1.55
```

Tag 会触发 Desktop Release workflow，生成：

- `LearnNote-Windows-x64.zip`
- `LearnNote-Setup-x64.exe`
- `LearnNote-Browser-Extension-v0.1.55.zip`
- `SHA256SUMS.txt`

## 签名与商店

- 有 Authenticode secrets 时验证安装器和可执行文件签名；没有时保留 SHA-256 与 SmartScreen 说明。
- 使用 `docs/BROWSER_STORE_SUBMISSION.md` 提交 Chrome Web Store 和 Edge Add-ons；商店包必须与 Release 扩展 ZIP 相同。
- 发布后重新运行真实 Edge smoke、安装/升级 smoke 和公开站点下载链接检查。
