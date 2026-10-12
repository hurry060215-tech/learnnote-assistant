import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

for (const filename of ["course-deletion-acceptance.cjs", "course-media-reuse-acceptance.cjs"]) {
  test(`${filename}: ignore only observation clocks, preserve all task comparisons`, () => {
    const source = readFileSync(new URL(`../../scripts/${filename}`, import.meta.url), "utf8");
    const declaration = source.slice(source.indexOf("const stableTask ="), source.indexOf("module.exports ="));
    const stableTask = new Function("assert", `${declaration}\nreturn stableTask;`)(assert);
    const first = { id: "synthetic-task", status: "cancelled", source: { text: "Synthetic unchanged evidence" },
      duration_estimate: { scope: "after_transcript_ready", status: "unknown", observed_at_unix_ms: 1000 },
      whole_task_duration_estimate: { scope: "current_processing_attempt", status: "unknown", sample_count: 0, observed_at_unix_ms: 1000 } };
    const original = structuredClone(first), later = structuredClone(first);
    later.duration_estimate.observed_at_unix_ms += 100;
    later.whole_task_duration_estimate.observed_at_unix_ms += 100;
    assert.deepEqual(stableTask(first), stableTask(later));
    assert.deepEqual(first, original, "The acceptance comparator must not mutate the API result");
    for (const mutate of [task => { task.status = "running"; }, task => { task.source.text = "changed"; },
      task => { task.duration_estimate.status = "estimated"; }, task => { task.whole_task_duration_estimate.sample_count = 5; },
      task => { task.whole_task_duration_estimate.scope = "changed"; }]) {
      const changed = structuredClone(later);
      mutate(changed);
      assert.notDeepEqual(stableTask(first), stableTask(changed), "Non-clock changes must still fail data-preservation comparisons");
    }
    delete later.whole_task_duration_estimate.observed_at_unix_ms;
    assert.throws(() => stableTask(later), "Missing observation fields must not be silently ignored");
  });
}
