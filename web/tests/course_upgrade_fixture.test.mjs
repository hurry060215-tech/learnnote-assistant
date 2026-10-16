import assert from "node:assert/strict";
import test from "node:test";
import fixture from "../../scripts/course-upgrade-acceptance.cjs";

const { childEventStream } = fixture;
const url = new URL("http://127.0.0.1:18940/api/tasks/visual-child/events/stream?after=0");
const child = { id: "visual-child", status: "queued", mode: "video", source_task_id: "video-a" };

test("synthetic queued child serves an idle SSE heartbeat without changing identity or state", () => {
  const tasks = [structuredClone(child)], before = JSON.stringify(tasks);
  const response = childEventStream("GET", url, {}, tasks);
  assert.equal(response.contentType, "text/event-stream");
  assert.equal(response.headers["Cache-Control"], "no-cache, no-transform");
  assert.equal(response.body, ": heartbeat\n\n");
  assert.equal(JSON.stringify(tasks), before);
});

test("synthetic stream is exact, GET-only, cursor-bound and available only after admission", () => {
  assert.equal(childEventStream("POST", url, {}, [child]), null);
  assert.equal(childEventStream("GET", new URL("/api/tasks/other/events/stream?after=0", url), {}, [child]), null);
  for (const query of ["", "?after=1", "?after=0&extra=1", "?after=0&after=0"])
    assert.throws(() => childEventStream("GET", new URL(url.pathname + query, url), {}, [child]));
  assert.throws(() => childEventStream("GET", url, { "last-event-id": "1" }, [child]));
  assert.throws(() => childEventStream("GET", url, {}, []), /before upgrade admission/);
  for (const change of [{ status: "success" }, { mode: "subtitle_only" }, { source_task_id: "other" }])
    assert.throws(() => childEventStream("GET", url, {}, [{ ...child, ...change }]));
});
