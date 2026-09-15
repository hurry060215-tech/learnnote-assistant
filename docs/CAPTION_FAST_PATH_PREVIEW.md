# Caption fast-path preview (2026-09-15)

Extension preview 0.2.9; the published client and submitted store extension are not replaced by this preview.

The previous panel initialized local discovery before reading captions. Collection waited for every frame before querying Bilibili, and successful captions expired after 30 seconds. Concurrent refresh/send calls could duplicate the request.

Changes:

- Start local discovery and source collection concurrently.
- Query captions concurrently with page collection; Bilibili video pages collect only the top-frame player, avoiding unrelated embeds.
- Use matching current-player video metadata to skip the view request. Reuse a player API resource URL only when its exact origin, endpoint, video and part match; otherwise retain the existing API fallback.
- Coalesce concurrent caption requests; retain successful results for five minutes in memory, keyed by tab, video and part. Recheck the active source after collection.
- Show measured query duration or an explicit cache label. Preview/search precedes generation options, with collapsible original text.
- Refine the client and extension with consistent paper colors, stronger hierarchy and a visible active-note marker.

Validation: 54 extension tests and 58 web tests passed. The new browser fixture checks captions appearing before a slow backend connection, measured-time presentation, search, preview ordering and 320px overflow. Fixture timing is not a Bilibili speed measurement. Store ZIP validation passed.

Live limitation: the browser tool confirmed the signed-in Bilibili homepage, but opening/controlling the target video repeatedly timed out. No successful authenticated live subtitle extraction or seconds-level latency is claimed. A real video acceptance run is still required before treating the preview as a verified production fix. No cookies or credentials were exported, and no paid model request was made.
