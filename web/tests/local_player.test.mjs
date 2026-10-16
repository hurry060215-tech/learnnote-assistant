import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../local-player.js", import.meta.url), "utf8");
const {createLocalPlayer, localPlaybackPosition, localMediaUrl, localMediaSource} = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
class Player extends EventTarget {
  ownerDocument = {baseURI:"http://127.0.0.1/"};
  dataset = {}; attributes = {}; readyState = 0; currentTime = 0; duration = NaN; pauses = 0; plays = 0;
  getAttribute(key) { return this.attributes[key]; }
  set src(value) { this.attributes.src = value; this.readyState = 0; this.currentTime = 0; }
  hasAttribute(key) { return key in this.attributes; }
  removeAttribute(key) { delete this.attributes[key]; }
  load() { this.readyState = 0; }
  pause() { this.pauses++; }
  play() { this.plays++; }
  metadata(duration = 20) { this.currentSrc = "http://127.0.0.1" + this.attributes.src; this.duration = duration; this.readyState = 1; this.dispatchEvent(new Event("loadedmetadata")); }
}
const player = new Player(), controller = createLocalPlayer(player);
controller.setSource("source/a");
assert.equal(player.getAttribute("src"), localMediaUrl("source/a"));
assert.equal(localPlaybackPosition(player, "source/a"), null);
assert(controller.seek(5.25)); assert.equal(player.currentTime, 0);
controller.seek(8.75); player.metadata(); assert.equal(player.currentTime, 8.75, "Newest pending seek wins");
assert.equal(localPlaybackPosition(player, "source/a"), 8.75);
assert.equal(localPlaybackPosition(player, "other"), null, "Another source cannot supply the range clock");
controller.seek(6.125); assert.equal(player.currentTime, 6.125);
for (const value of [NaN, Infinity, -1, "10", null, undefined]) assert.equal(controller.seek(value), false);
controller.seek(100); assert.equal(player.currentTime, 20, "Seek is bounded by actual metadata");
controller.setSource("slow"); controller.seek(12.5); controller.cancelSeek(); player.metadata();
assert.equal(player.currentTime, 0, "Metadata after Close cannot apply a pending seek");
controller.setSource("slow"); player.readyState = 0; controller.seek(11.5); controller.setSource("replacement"); player.metadata();
assert.equal(player.currentTime, 0, "Metadata after source replacement cannot apply an old position");
controller.setSource("manual"); controller.seek(4.5); player.currentTime = 2.75; player.dispatchEvent(new Event("seeking")); player.metadata();
assert.equal(player.currentTime, 2.75, "A newer player control seek cancels a pending citation seek");
controller.setSource("failed"); controller.seek(9); player.dispatchEvent(new Event("error")); player.metadata(); assert.equal(player.currentTime, 0);
// Preserve the old browser metadata through src assignment to exercise the
// asynchronous resource-selection interval that a simple fake normally hides.
const old = new Player(); old.src = localMediaUrl("old"); old.metadata(3);
Object.defineProperty(old, "src", {set(value) { this.attributes.src = value; }});
const changing = createLocalPlayer(old); changing.setSource("long-new");
assert.equal(localPlaybackPosition(old, "long-new"), null);
changing.seek(12.5); assert.equal(old.currentTime, 0, "Do not clamp a new seek to the old 3-second media");
old.dispatchEvent(new Event("loadedmetadata"));
assert.equal(old.currentTime, 0, "Queued old metadata cannot consume the new pending intent");
old.metadata(20); assert.equal(old.currentTime, 12.5);
controller.setSource(null); assert.equal(player.dataset.sourceTaskId, undefined); assert.equal(localPlaybackPosition(player, "failed"), null);
const child = {kind:"task",id:"child",source_media_path:"parent.mp4",learning_range:{start:5.25,end:15.75},status:"queued"};
assert.equal(localMediaSource(child), null, "Pending range cannot use its parent fallback");
assert.deepEqual(localMediaSource({...child,status:"running",range_media_ready:true,media_integrity:{sha256:"clip"}}), {id:"child",revision:"clip"}, "An atomically completed clip is available during summary generation");
assert.deepEqual(localMediaSource({...child,learning_range:{}}), {id:"child",revision:""}, "Full-source reuse keeps its fallback");
controller.setSource("same-task", "old-digest"); player.metadata(20); controller.seek(6);
const pauses = player.pauses;
controller.setSource("same-task", "old-digest"); assert.equal(player.pauses, pauses, "Unchanged media does not reset playback");
controller.setSource("same-task", "clip-digest"); controller.seek(5.25);
assert.equal(localPlaybackPosition(player, "same-task", "old-digest"), null);
player.readyState = 1; player.currentSrc = "http://127.0.0.1" + localMediaUrl("same-task", "old-digest");
player.dispatchEvent(new Event("loadedmetadata")); assert.equal(player.currentTime, 0, "Old same-task revision metadata cannot consume the new seek");
player.metadata(10.56); assert.equal(player.currentTime, 5.25);
assert.equal(localPlaybackPosition(player, "same-task", "clip-digest"), 5.25);
player.currentSrc += "&unexpected=1"; assert.equal(localPlaybackPosition(player, "same-task", "clip-digest"), null);
player.currentSrc = "http://other.test" + localMediaUrl("same-task","clip-digest");
assert.equal(localPlaybackPosition(player, "same-task", "clip-digest"), null, "Same path/revision on another origin is not the canonical source");
assert.equal(player.plays, 0, "Source and seek controls never autoplay");
console.log("Local player: subsecond seconds, identity, metadata ordering, latest seek, Close, replacement, native seek, errors and no autoplay passed");
