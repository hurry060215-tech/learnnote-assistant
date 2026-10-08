# Runtime issue acceptance, 2026-10-08

Base: `632b6076e847b3b1baa256c760e18f81a4821183`. This increment addresses
specific acceptance gaps in #130, #131 and #146; it does not claim all product
epics are complete.

## Changes and acceptance

- **#131 bounded uploads:** configurable positive byte limits preserve safe
  defaults; actual ENOSPC/EDQUOT produces a path-free 507 response, byte counts
  and cleanup. The real multipart parser closes its disk-spooled handles on
  size overflow and client disconnect. Declared-length rejection happens before
  reading the body. Concurrent reservations, process-crash reclamation and a
  restarted backend using a different data directory are covered. Existing
  staged/pending retention tests remain in the complete suite. See
  [the policy and reproduction commands](UPLOAD_ADMISSION.md).
- **#146 truthful routing:** auto visual mode discloses selected frames;
  configured remote ASR discloses audio; local vision endpoints are labeled
  local. Uncaptured platform subtitles no longer imply offline readiness.
  Settings passes the selected ASR model and route, shows possible outgoing
  data and the no-Key subtitle fallback. Unknown timing/cost/context limits are
  explicit, never fabricated. The planner performs no probe or model call.
  End-to-end provider quality and measured estimate ranges remain open.
- **#130 reliability freshness:** relevant PRs and main changes now run the
  existing synthetic 5/30/60/180-minute, cancellation, mixed-queue and full
  60-minute gates against the exact checkout. The public no-login audit stays
  on main/schedule/manual runs, not PR runs. Release-bound freshness remains
  mandatory. No required check or branch protection was relaxed.
- **Offline regression isolation:** CI now runs backend tests behind local
  DNS/socket/HTTP/yt-dlp rejection. Live integration tests remain separate.
  The runner preserves loopback fixtures and child-process module resolution.

## Local verification

- Backend: **664 tests passed, 1 optional OCR-runtime skip**, using
  `python scripts/test-backend-offline.py`.
- Script contracts: **100 tests passed, 2 PowerShell-only skips** on Linux.
- Desktop launcher: **28 tests passed**.
- Every `web/tests/*.test.mjs` and `extension/tests/*.test.mjs` script passed.
- Architecture guard and changed JavaScript syntax passed; `git diff --check`
  passed. PowerShell workflow syntax and publisher execution require Windows
  CI and are not counted as local passes.
- No private media, real credentials, paid model calls or store publication.

The initial unguarded backend command was blocked on an external fixture
request and is not counted as a pass. The completed results above are from
the network-denied runner. Browser visual acceptance and the exact commit's
remote reliability run must pass before merging this increment.
