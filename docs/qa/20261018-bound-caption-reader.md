# Generation-bound caption preview

## Observed problem

The observer-off Windows reference run `39094163300` retained all 80 samples.
Sample index 67 exceeded the unchanged 5-second post-transcript visibility
limit: 16.890 seconds, with 17.5905 seconds from submission to visible outline.
Its selected-task GET took 15.890683 seconds on the host observation clock.
The draft event arrived while that request was pending; the ordinary edition
request began only after it completed. The edition request and final geometry
measurement were short. The 180-minute cohort p95 was 3.3636 seconds, which does
not erase the individual ACK failure.

A barrier-controlled synthetic test demonstrates that the existing task update
transaction can block both selected-task and personal-review reads. This proves
susceptibility, not the lock owner or underlying cause of that Windows sample.

## Narrow reader contract

The existing task-edition GET accepts an explicit `reader_snapshot=true` option
and an expected control generation. Ordinary edition reads, edits, exports,
mutation transactions, and legacy tasks keep their existing behavior.

An eligible generated caption draft has a publication witness in its current
pipeline attempt: control generation, attempt identity, sequence, exact body
hash, and a hash of the typed transcript plus source context. Publication binds
the intended bytes and brackets source context across the write. The reader
checks owned artifacts, task-directory incarnation, current attempt, personal
edition absence, and repeated source/body/manifest observations without taking
the task or personal-edition lock. Unavailable or changing snapshots return
409; an actually absent task returns 404. There is no locked fallback.

The initial publication-to-pointer gap has one explicit provisional form:
first attempt, retry count zero, running task, empty note pointer and empty
summary source. Retained retry pointers and conflicting publication state cannot
qualify for this provisional form. A provisional response is a read-only caption preview, not an
accepted final edition or verified source projection.

The browser uses a bounded independent read lane and fences older responses by
task, navigation epoch, generation, local source identity and request revision.
The preview disables editing, source/evidence actions and personal-review
actions. Exact same-body ordinary handoff restores normal behavior in place.
Only an exact unchanged initial empty-pointer snapshot can temporarily retain
the provisional body using the existing one-reconciliation budget. A changed
source, final/partial edition, deletion, retry or incompatible metadata retires
it. Selection continuity is not claimed across source enrichment or changes.

## Verification boundaries

Focused backend and browser-state tests cover intended-byte binding, missing
witnesses, retries, personal edits, source/body mismatch, directory replacement
at read boundaries, held metadata reads, reversed responses and navigation.
The prepared deterministic browser scenario uses synthetic endpoint responses
to test shipped rendering; backend binding is covered in focused tests. Local browser
launch was denied by the execution environment before any page opened.

Actual hosted browser evidence and the unchanged observer-off 80-sample timing
gate remain required. This change does not establish a latency guarantee,
resolve the unidentified Windows server stall, or verify customer model output.
