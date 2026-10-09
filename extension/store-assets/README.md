# Bilingual store image archive

Status: **accepted as repository localization assets and archived**. Codex
performed an AI assistant visual review on 2026-10-09 at 14:12:58 UTC, inspecting
all four artwork images and all four full-panel captures individually at original
resolution. This is an assistant review of repository assets, not store approval.

- English: [notes](a400df83e450004253d6386847a1bfc5a473e00e/store-en-US-summary-1280x800.png)
  and [transcript](a400df83e450004253d6386847a1bfc5a473e00e/store-en-US-transcript-1280x800.png)
- 简体中文：[笔记](a400df83e450004253d6386847a1bfc5a473e00e/store-zh-CN-summary-1280x800.png)
  和[字幕](a400df83e450004253d6386847a1bfc5a473e00e/store-zh-CN-transcript-1280x800.png)
- [Actual review and source/artifact provenance](a400df83e450004253d6386847a1bfc5a473e00e/review.json)
- [Unchanged capture manifest](a400df83e450004253d6386847a1bfc5a473e00e/store-candidates.json)
  and [passing 18-condition report](a400df83e450004253d6386847a1bfc5a473e00e/report.json)

[Windows Edge run 37941628048](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37941628048)
passed at source `a400df83e450004253d6386847a1bfc5a473e00e`. Its synthetic merge
tree equals the tested PR head tree `081304e04b7da91a894e379fb0bc0b38f3cb399c`.
The official artifact is `11621709725`; its ZIP SHA-256 is
`487a46e29ab702f27d66464bba6c12a42ecc287b59ce769d531a3456c85d6a0d`.
The archive preserves all 14 original PNGs (826,508 bytes), report and manifest
unchanged, beyond CI retention. The separate review record contains each artwork
hash, the full-panel hashes, official artifact URLs and observed acceptance.

The earlier placeholder/cropped candidates are superseded. Native extension
installation, real Chrome/Edge permission dialogs and store submission remain
separate untested boundaries; no store action was performed.

## Generate and verify

Use the Windows Edge `UI visual acceptance` workflow at the intended commit.
Its existing extension stage runs:

```sh
node scripts/extension-locale-visual-acceptance.cjs build/extension-locales
```

No account, key, real model, website access, new permission or store upload is
needed. Chrome APIs and local-service replies are explicit fixtures. The actual
shipped panel/controller/styles render in Edge. The store artwork juxtaposes
two separately labeled views: the complete header/connection/course area before
sending and the complete result card after a synthetic task. The app itself is
not restyled or rearranged. The same authored English course remains unchanged
in Chinese and English UI scenes.

The four reproducible listing filenames are:

- `store-en-US-summary-1280x800.png`
- `store-en-US-transcript-1280x800.png`
- `store-zh-CN-summary-1280x800.png`
- `store-zh-CN-transcript-1280x800.png`

Download the official `ui-visual-<run id>` artifact before its 14-day expiration.
Check the extension stage, report source SHA and workflow source; report any
later unrelated failure without treating it as an extension-stage pass/fail.
Retain the source/result excerpts and full-panel captures for comparison. Verify:

```sh
node scripts/extension-store-visual-fixtures.cjs --verify <extension-locales-directory>
```

This reads the PNG dimensions and hashes and requires the corresponding passing
18-condition report. It is an integrity check, not a visual-review gate.

## Review the pixels before archiving

Inspect all four images at native 1280×800 and compare them with their full panel
captures. Confirm:

- The header and full course context are visible; neither source nor result card
  is clipped, and no sticky header obscures a capture.
- Product labels, note/subtitle text, timestamps and disclosure are legible.
- The two independent views are plainly labeled; the composition is not
  presented as one actual browser window or installed native Side Panel.
- English and Chinese product labels match their scene locale. Course title,
  authored note and all six subtitle cues stay in their original English.
- There are no stress-test placeholders, secrets, real user data or unsupported
  claims of actual generation. Synthetic course/service responses and absence of
  a model call/native installation are disclosed in both images and provenance.

If any image fails, fix only the store fixture, rerun CI and inspect all affected
images again. Do not edit PNGs to conceal product failures or alter their text.

## Archive subsequent reviewed captures

After visual review, create `extension/store-assets/<full-source-sha>/` and copy
the four listing PNGs, their `store-source-*`, `store-result-*` and
`store-full-panel-*` PNGs, `store-candidates.json` and `report.json` there unchanged.
The raw captures preserve the original UI and the manifest's hash chain beyond
CI retention. Re-run the integrity command against that directory.

Add a separate `review.json` recording the actual reviewer, UTC review time,
exact source SHA, workflow and artifact URLs, artifact ZIP SHA-256, the four
filenames and hashes, and observations against the checklist above. Keep the
generated manifest's `candidate-unreviewed` status and `visual_review: null`
unchanged: automated capture is not the review event. Do not fabricate a review.

Commit the image bytes and review record; then update the archive index with
links to the new four images and update `STORE_LISTING.md` and
`docs/EXTENSION_LOCALIZATION.md` with the observed outcome and exact evidence.
Verify the committed files remain readable. Only then may the screenshot portion
of #144 be accepted. This procedure does not submit or update a store listing.

## 简体中文

中英文各两张 1280×800 素材已通过 Codex 的 AI 助手逐张视觉审阅，并与独立视图原图、
完整侧栏截图、原始报告、SHA-256 和真实审阅记录一并归档。界面文案对应各自语言，
同一英文示例课程保持原文，来源与结果完整可读，合成示例及并列视图说明清晰可见。
这属于仓库本地化素材验收，不代表商店审核通过；未进行原生扩展安装、真实权限弹窗
验收或商店提交。后续替换素材仍需实际渲染、逐张检查并单独记录审阅结果。
