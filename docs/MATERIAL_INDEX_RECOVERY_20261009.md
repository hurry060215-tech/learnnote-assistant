# Rebuild document evidence from local originals

Related scope: #157. The original material record must still exist; recovery of a missing or structurally corrupt entire SQLite database remains outstanding.

The document's **笔记工具 → 从本机原文件重建出处索引** action calls `POST /api/library/materials/{id}/rebuild`. It restores missing evidence rows and their full-text search entries from the saved TXT, Markdown, HTML or text-PDF source. Existing citation IDs, source revision, page/section locators, study cards and schedules remain intact. Video registrations keep using their original task recovery path.

Recovery checks the source hash and extraction revision before writing. Existing OCR documents use the verified local OCR cache, retain incomplete-page status and remain unverified; repair never reruns recognition or transmits content. Changed/missing originals, invalid OCR caches, inconsistent IDs, a concurrently changed material record, and an evidence ID owned by another source stop recovery without replacing existing records. Evidence and material updates share one SQLite transaction.

Verification uses synthetic local files and temporary databases:

- Real TXT, Markdown, HTML and two-page PDF imports: erase evidence rows, rebuild, compare exact IDs/text/locators, recover search results and existing card backlinks.
- Recreate missing evidence tables with the original GB18030 decoding choice.
- Restore a cached partial OCR projection while recognition is explicitly disabled.
- Reject altered original bytes and altered OCR cache; retain existing rows.
- Roll back on a foreign evidence identity, injected SQLite failure, and concurrent material update.
- Exercise the actual HTTP repair endpoint and missing-source response.
- Execute the production UI action with late replies, dismissal and newer navigation.
- The existing Windows/Edge UI workflow now clicks the real repair control against its isolated backend and checks stable citation IDs, reread content and completion feedback. Its result must be verified on the final PR head; the local script self-test is not browser acceptance.

This increment covers damaged document evidence projections. It does not add whole-database disaster recovery or establish every other #157 acceptance condition.
