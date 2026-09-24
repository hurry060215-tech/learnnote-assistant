# Task progress stream reconnect acceptance

- Date: 2026-09-24
- Related issue: [#151](https://github.com/hurry060215-tech/learnnote-assistant/issues/151)
- Related PR: [#213](https://github.com/hurry060215-tech/learnnote-assistant/pull/213)
- Input: one synthetic active task and three synthetic SSE frames; no user task, transcript, cookie, or model credential.

## Browser path

`scripts/task-stream-reconnect-acceptance.cjs` opens the actual LearnNote web app in Microsoft Edge and uses an isolated local HTTP proxy. Static files and non-task API calls go to the local FastAPI backend. The proxy supplies only the task list/detail and a three-frame SSE stream so it can close each response deliberately and test the browser's native `EventSource` reconnection behavior.

The first connection sends event ID 1 and ends. The next request carries `Last-Event-ID: 1`; the second sends event ID 2 and ends. The third carries `Last-Event-ID: 2`, sends a terminal event, and the UI closes the stream. The task card reaches 100% and displays its completed state. All three URLs retain `after=0`, demonstrating that browser-managed `Last-Event-ID` carries the resume cursor when the original URL is unchanged. The browser reported no page errors.

Acceptance output:

```json
{"ok":true,"streamRequests":[{"after":"0","lastEventId":""},{"after":"0","lastEventId":"1"},{"after":"0","lastEventId":"2"}],"finalStatus":"success","finalProgress":100,"errors":[]}
```

The FastAPI stream route's persisted event replay and cursor handling have separate automated backend coverage in the reliability work package. This browser run proves the actual app UI and Edge EventSource reconnect loop against controlled frames; it does not claim that an in-progress real media task survived a server or network failure. A future task may extend this fixture to exercise a live backend task without controlling its processing phases.

## Reproduction

- Windows / Microsoft Edge; backend launched with `LEARNNOTE_DATA_DIR` set to an isolated `build/` directory.
- `node scripts/task-stream-reconnect-acceptance.cjs 8765 build/task-stream-reconnect-ui`
- Verified against the local backend on port 18784; screenshots and task payloads remain in ignored `build/` output.

## Remaining issue boundary

Keep #151 open. Real task reconnection while media is processing, replay idempotency across backend restart, refresh behavior with older completed tasks, incremental draft visibility, and cancelling a real task stopping new phases within two seconds still require end-to-end evidence.
