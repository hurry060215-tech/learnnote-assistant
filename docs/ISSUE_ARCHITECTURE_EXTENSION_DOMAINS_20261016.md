# Extension product-domain boundaries (#143, 2026-10-16)

This independently reversible stage extracts active extension decisions from
`background.js` and `content.js`. It preserves the existing capture permission
and epoch gates, wire objects, API paths, capture-log format, pairing storage,
subtitle-only cookie exclusion, and browser/store permissions. It introduces no
network destination, dependency, telemetry, recording, or persistent data.

## Migration map

```text
background (browser events, permission/epoch checks, capture state, handoff)
  -> source-identity (title selection, identity projection and comparison)
  -> request-context (request normalization, persistence and response projection)
       -> capture-classification (supplied URL/MIME/header policy)
  -> cookie-context (target/partition planning; injected cookie-read adapter)
  -> backend-transport (injected storage/network/timers; existing retry policy)
  -> capture-ranking -> capture-classification

content (DOM observation, subtitle evidence, resource collection and notification)
  -> content-media-hints (supplied text/JSON/URL decisions)
       -> capture-classification
  -> content-study-evidence
```

The background `importScripts` list is explicit. Content injection loads
`capture-classification.js`, `content-study-evidence.js`,
`content-media-hints.js`, then `content.js`, in the content script's isolated
realm. Loading a provider in the service worker does not satisfy this contract.
No new page-world script is injected.

`page_hook.js` remains unchanged. At this baseline it is packaged and exercised
by historical offline tests, but is neither registered in the manifest nor
injected by the active production scripts. This stage does not reactivate it or
claim to finish its decomposition. Remaining #143 acceptance still includes
that script and the other web/backend stages, combined-tree real-extension
smoke, visual acceptance where applicable, and long-task recovery.

## Public inputs and outputs

All module namespaces are frozen. Importing a module or constructing an adapter
registers no listener, performs no browser read, and starts no request/timer.

- `LearnNoteSourceIdentity`: `bestPageTitle(...titles)` returns a string;
  `buildSourceIdentity(tab, page, resources, capturedAt)` returns the existing
  identity object (`tab_id`, canonical page URL, platform/video/BVID fields,
  title, active-video source, fingerprint, ISO capture time);
  `sourceIdentityMatches(expected, actual)` returns a boolean. The optional
  `capturedAt` retains its original current-time default. Token changes and
  title updates retain the existing identity behavior.
- `LearnNoteRequestContext`: accepts browser header arrays, string-valued
  header maps, request body form/raw arrays, and the existing resource object.
  Header/body normalization returns the same map or `form`/`text`/`dropped`
  record (or the same empty/null result); it retains the 64 KiB bound.
  Persistence removes credential headers exactly as before. URL transitions
  preserve authorization only for the existing strict same-origin rule.
  `responseResource(details, headers, requestHeaders, requestBody, kind,
  resolvedUrl, label, now)` projects the shared completed/redirected request
  fields into the existing resource schema; `now` is evaluated only if the
  original request lacks a truthy timestamp. Capture permission, response
  classification, epoch validation, storage and notifications stay in background.
- `LearnNoteCookieContext`: `cookieUrlsForContext(page, tab, resources)` and
  `cookieLookupDetailsForUrls(urls, partitionKeys)` return the same ordered,
  deduplicated target/lookup arrays. `cookieContextSummary(cookies, urls,
  partitionKeys)` returns counts and domain/count pairs, never cookie values.
  `createCookieContext({getCookies})` takes a caller-supplied Chrome-compatible
  cookie API accessor and returns `cookiePartitionKeysForContext` and
  `cookiesForUrls`. Existing partition preference, lookup order, deduplication,
  inaccessible-frame handling and unsupported-lookup fallbacks are retained.
  Only the permission-checked handoff calls the adapter.
- `LearnNoteBackendTransport.createBackendTransport` accepts explicit storage,
  fetch/availability, clock, extension-version, timer and abort-controller ports,
  plus the existing default backend URL and protocol version. It returns the
  existing stored-URL, pairing-header, heartbeat, error/JSON response and
  `postJsonWithRetry` operations. URL selection remains loopback-only. Cached
  pairing retains the same expiry margin and storage keys. POST retry defaults
  remain two attempts, with a 250 ms first delay; the caller's `beforeSend`
  authorization/epoch callback runs after pairing on every attempt. Failure
  still returns the existing `ok:false` response; heartbeat returns a boolean.
- `LearnNoteContentMediaHints.createMediaHints({getPageUrl})` returns the URL,
  string decoding, classification, scoring, MIME hint and split-base JSON
  helpers used by content collection. Inputs are strings/plain objects, outputs
  are strings, booleans, scores or ordered URL/value arrays. The URL accessor is
  evaluated at use time so SPA navigation cannot freeze the original page URL.
  There is no DOM traversal, fetch, cookie read or capture state in this module.
  Shared classification accepts an optional explicit `baseUrl`; omitted means
  the exact original background behavior. Content's distinct classification
  precedence is retained rather than silently replaced with background policy.

Private parser/identity helpers are not copied into orchestration globals.
The existing caller-used background entry names remain available. The only
removed unused content declaration was its uncalled `inferManifestUrl` wrapper;
manifest inference remains available in the shared classification contract.

## Budgets and dependency gates

| File | Baseline lines | Current lines | Previous cap | New cap |
| --- | ---: | ---: | ---: | ---: |
| `background.js` | 2472 | 1752 | 2500 | 1800 |
| `content.js` | 2176 | 1823 | 2200 | 1850 |
| `source-identity.js` | — | 164 | — | 170 |
| `request-context.js` | — | 247 | — | 260 |
| `cookie-context.js` | — | 221 | — | 230 |
| `backend-transport.js` | — | 119 | — | 125 |
| `content-media-hints.js` | — | 400 | — | 405 |

The full capture group, including every new transitive dependency, remains
under the unchanged **335000-byte** budget: 331999 bytes at baseline, 334722
bytes here. There is no aggregate allowance increase. Shared classification,
request-response projection and cache eviction remove duplicate decisions;
individual file reduction is not the sole acceptance evidence.

The JavaScript graph now knows all five providers and their permitted edges.
CI rejects reverse dependencies, cycles, missing helpers, incorrect content
realm load order and a helper omitted from the aggregate budget. Distribution
and desktop-update allowlists, Windows and macOS packaging and release-tree
validation include all five helpers. The LF/autocrlf byte regression covers the
entire capture group.

## Behavior evidence and recovery

- `extension/tests/fixtures/product-domain-snapshot-v1.json` was evaluated from
  original functions at `b590e55169cebd4ca34a7312b16fef1aa3ecec01` before changing
  their bodies. It includes source SHA-256 hashes, synthetic-only URLs/cookies,
  source identity, request headers/body redaction, redirect authorization,
  partition selection, content parsing and current-page resolution outputs.
  `helpers/product-domain-scenarios.mjs` defines its input cases.
- `product_domain_boundaries.test.mjs` compares the new contracts against that
  snapshot without ambient Chrome, DOM or fetch access. It additionally checks
  body bounds, inaccessible cookie APIs, current-URL refresh after navigation,
  pairing cache/expiry, retry revocation, structured errors and absent fetch.
- Existing background/source/authorization/request and content/encoded/static
  hint tests exercise the entry scripts. The permission-handoff race fixture
  now reads the extracted retry implementation; its assertions are unchanged.
- `scripts/tests/test_javascript_graph.py` includes negative tests for every
  new reverse dependency/cycle/budget omission and cross-realm load order.
  `test_store_package.py` rejects a package missing any new helper.

Parsing and cookie-read failures retain their previous empty/null/fallback
results; no fallback becomes verified evidence. Transport failures preserve
existing retry limits and visible errors. No data migration or index rebuild
is needed. Revert this stage's code and distribution-list changes together to
roll back; preexisting task JSON, exports and extension storage remain readable.

Validation for this stage: 197 script tests run (194 pass, 3 existing platform
skips), 47 desktop tests run (46 pass, 1 platform skip), all 72 extension test
programs pass, all extension JavaScript syntax checks pass, and the architecture
gate passes. Real browser/combined-tree
acceptance must be recorded separately; an offline VM test is not that evidence.

## Hosted combined-tree smoke gate

`ui-visual.yml` now has a separate `extension-runtime` Windows job using the
existing `e2e-extension-smoke.py` with Edge, a fresh temporary profile and dynamic
loopback ports. It checks actual service-worker startup/heartbeat, content helper
injection, synthetic MP4/HLS/POST and iframe/cookie evidence, and Side Panel
handoff. It uses no account/store credentials and the workflow retains
`contents: read`. Artifacts contain a commit-stamped scope/exit-code report and
synthetic test logs; browser profiles are removed and are not uploaded.

This is a gate definition, **not a passing browser result**. Dispatch/run status
must be verified on the final integrated commit. Native optional-permission
prompts, store installation/update, real authenticated sites and long-task
recovery are explicitly excluded. Local PowerShell syntax execution was not
available in this Linux environment; the Windows job validates it at runtime.
The added workflow contract test brings the local script suite to 198 tests
(195 passed, 3 existing platform skips).
