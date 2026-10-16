# Local player range and source identity acceptance

## Scope

The default `web/index.html` reader's actual `desk.js` / `desk-tools.js` player
and range dialog are covered. The legacy `app.js` is intentionally unchanged.
This supplements `local-range-acceptance.py`, which already checks real clipping,
restart recovery, and full-source upgrade without claiming browser acceptance.

The bounded UI changes:

- Bind the local media clock to the task ID, media URL, and current metadata.
  Preserve decimal seconds when filling the range form; never read the previous
  source's position while a new source is loading.
- Delay a citation seek until matching media metadata is ready. Latest seek wins;
  closing or replacing the source cancels pending work. Queued old metadata does
  not consume the new seek, and native player seeking supersedes an older intent.
  Nothing calls `play()` automatically.
- Show source title, current media duration and clip-relative versus original
  range units. Reject non-finite, reversed, negative or out-of-bounds ranges.
- Scope range and full-source requests to the dialog generation, selected task
  and navigation epoch. Duplicate submission cannot create a second task. A late
  reply after Close/navigation cannot reopen the dialog or replace the new note.
- Full-video upgrade retains the existing canonical ancestry traversal and
  explicit confirmation; it never guesses a whole-video URL.

## Hosted browser gate

Run on Windows with installed Microsoft Edge, test Python requirements, and the
existing Playwright dependency:

```
node scripts/local-player-visual-acceptance.cjs build/local-player-ui
```

The helper starts `local-player-fixture.py` in a new application-owned temporary
data directory, applies the existing loopback-only network guard, and generates
20-second synthetic H.264/AAC media with exact timed synthetic subtitles. Media,
clipping, task APIs, persistence and playback are real. Only summary generation is
a deterministic fixture. No external model, ASR, real website/account, extension
or native permission prompt is involved. The directory is removed after the run.

The actual UI sends 5.25–15.75 seconds, verifies the 10.5-second clip and its
relative transcript, creates a nested clip, then resolves and upgrades the full
20-second root source. HTTP request bodies are checked against the decimals entered
in rendered fields. The original media/transcript/note hashes remain unchanged.

Delayed real media responses exercise a new 20-second source replacing an already
loaded 5.25-second clip: latest citation seek, Close and source switch. Additional
flows reject an old source's clock during delayed edition navigation, preserve a
new native seek through delayed transcript rendering, and close/switch during an
accepted range POST whose response has not returned. Duplicate submits are counted.

The report asserts the rendered task ID, current media URL, readyState, exact
currentTime tolerance, duration and paused state. It retains viewport screenshots
at 1440/390 in light/dark for the range form, plus interrupted/source-switch states.
Screenshots require human inspection; geometry checks alone are not visual approval.
The existing `ui-visual.yml` Windows job runs this helper and uploads its directory.

## Local verification and limits

- `node web/tests/local_player.test.mjs`: deterministic metadata, clock and seek
  ordering regression, including old metadata dispatched after source replacement.
- `node web/tests/local_range_ui.test.mjs`: executes production range functions
  with controlled async responses; decimal payload, validation, duplicate, Close,
  same-source revisit, newer navigation and canonical upgrade assertions.
- `node scripts/local-player-visual-acceptance.cjs --self-test`: verifies that the
  report assertions reject wrong source, URL, time, hidden/unloaded media and
  autoplay. It does not launch a browser.
- `python scripts/local-player-fixture.py --data-dir EMPTY_DIR --seed-only`:
  validates actual synthetic fixture creation without opening a socket.

At implementation handoff the hosted Edge gate and screenshot inspection are
pending. Local Chromium socket binding is unavailable in the editing environment;
no local browser success or visual sign-off is claimed. Native desktop webview,
real course/website behavior, native optional-host permission acceptance, and
provider quality remain outside this gate. The native permission security-warning
boundary is unchanged and must not be bypassed.
