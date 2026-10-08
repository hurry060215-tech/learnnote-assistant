# Release transaction acceptance, 2026-10-08

Scope: #134, based on main `61f6c5d`. Existing draft reuse and download-hash
verification were present, but an unexpected extra asset left in a draft could
be published without appearing in the reviewed checksum manifest.

The publisher now fails closed unless the complete remote asset inventory has
exactly the expected names and byte sizes, followed by the existing downloaded
SHA-256 checks. Empty local assets fail before any GitHub operation. A changed
tag/draft state aborts verification. Unexpected files are not automatically
deleted. The existing per-tag workflow concurrency guard is unchanged.

The offline PowerShell harness invokes the real publisher with a disk-backed
`gh` function and no GitHub connection. Its lifecycle now covers initial draft
creation, partial upload failure, unexpected-asset quarantine, wrong remote
size, interrupted verification download, same-tag resume, exactly one create,
published rerun with no writes and corrupted published asset with no replacement.
The production workflow retains version checks, installation/upgrade smoke and
release-bound freshness before invoking the publisher.

Linux local checks: release/source contracts pass; three PowerShell-dependent
tests are explicitly skipped because PowerShell is unavailable. Windows CI
must execute those cases without skips before this increment is merged or the
issue is considered resolved. No new tag or real Release is created to test
the transaction, and no historical asset is modified.
