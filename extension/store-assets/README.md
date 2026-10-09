# Bilingual store image archive

Status: **replacement scenes prepared; rendered review and durable PNG archive
pending**. This directory intentionally contains no approved images yet. The
four older CI candidates were rejected for test-placeholder content and cropped
source context. Do not copy those images here or mark issue #144 complete.

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

The four intended listing files are:

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

## Make the reviewed result durable

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

Commit the image bytes and review record; then replace this pending status with
links to the archived four images and update `STORE_LISTING.md` and
`docs/EXTENSION_LOCALIZATION.md` with the observed outcome and exact evidence.
Verify the committed files remain readable. Only then may the screenshot portion
of #144 be accepted. This procedure does not submit or update a store listing.

## 简体中文

目前只有可复现的替换场景，尚无已审阅归档的图片。Windows Edge CI 生成中英文各两张
1280×800 素材，同时保存独立视图原图、完整侧栏截图与 SHA-256。请逐张检查实际像素、
原文保留、完整取景与合成示例说明，再将图片及真实审阅记录提交至上述目录。自动通过、
生成文件或校验哈希均不代表视觉验收；本流程不进行商店提交。
