/* User-visible playback preconditions shared with offline fixture regressions. */
const assert = require("node:assert/strict");

async function openVisibleTranscript(page) {
  const transcript = page.locator("#sourceTranscript");
  if (!await transcript.evaluate(node => node.open)) await transcript.locator("summary").click();
  await page.locator("#sourceContent .cue").first().waitFor({ state: "visible" });
  assert.equal(await transcript.evaluate(node => node.open), true, "Playback acceptance explicitly opens the existing transcript disclosure");
}

function playbackTracksReady(claimId) {
  const transcript = document.querySelector("#sourceTranscript"), player = document.querySelector("#player");
  const cue = document.querySelector('#sourceContent .cue.active[aria-current="time"]');
  const claim = document.querySelector(`.note-claim-marker[data-claim-id="${claimId}"]`);
  return transcript?.open && player && !player.paused && cue?.getClientRects().length > 0
    && /Second synthetic window/.test(cue.innerText)
    && document.querySelector("#sourceWindow figure")?.dataset.windowId === "window-2"
    && claim?.getAttribute("aria-current") === "true";
}

module.exports = { openVisibleTranscript, playbackTracksReady };
