# Local recall, self-assessment and stability

The study workspace keeps four kinds of evidence separate:

- Reading/view events say that a local source or card was opened. They do not establish an answer attempt or comprehension.
- Objective attempts compare a submitted term with an exact, source-grounded cloze answer. Counts show matched answers / submitted attempts, not a general ability score.
- Self-explanations record the action only; their free-text explanation is not saved. FSRS ratings remain the user's own memory assessment.
- FSRS stability comes from those self-ratings and the existing schedule. An objective answer does not change the schedule or manufacture a rating.

The one supported objective format blanks a named subject from a complete English or Chinese definition/relation. The entire card answer must still occur verbatim in current canonical evidence accepted by the shared quiz eligibility gate. Missing, generated-note, community, corrupt or otherwise ineligible sources cannot produce an objective question. Other cards continue to support self-assessment. No model or external service is used.

Scoring ignores letter case and leading/trailing whitespace, and collapses repeated whitespace to a single space. It does not interpret synonyms, paraphrases or punctuation differences. The UI explains that a mismatch does not establish a lack of understanding. The recall heading is withheld while the cloze is active so it cannot reveal the missing term. Revealing/skipping the answer ends the current unsubmitted cloze without recording correctness.

## API and history

`GET /api/study/cards/{id}/quiz` returns the eligible prompt, source anchors, scorer version and revision, never the expected answer. Reading this endpoint is read-only. `POST /api/study/cards/{id}/answer` accepts only the revision, submitted answer and required idempotency key. The server rebuilds the question from current card/source content and rejects stale questions before writing. It does not accept client-supplied correctness or answer keys.

One logical submission has one key and one frozen payload. Repeated requests replay the original result; a conflicting payload is rejected. An already-saved result may be replayed after editing, but cannot add another attempt. Deleted cards cannot be answered. Paused plans and suspended cards block new attempts. Closing a UI does not cancel an action already submitted, and late replies cannot update a newer view.

Each attempt preserves its question, answer key, submitted term, result, source IDs, scorer and timestamp. Editing a card retains that snapshot and the FSRS history. Objective mismatches and self-assessed “Again” records are displayed with different labels. Both link to their canonical source. Aggregate measures explicitly cover all local sources and all recorded time; the existing activity grid retains its 14-day scope. Generic historical `answer` events are unscored, and historical ratings remain self-assessments. Neither is backfilled into correct answers.

## Migration and deletion

The SQLite migration is additive: a new attempt table and an optional activity idempotency column/index. It does not rewrite old cards, ratings or events. Study backups now use schema 4, include all attempts, and still accept schema 3. Restore validates the complete snapshot before writing and merges without replacing existing entries. Old backups restore with no invented objective history. Returning to the older application leaves its original tables/data usable; retain the schema 4 export to preserve objective attempts because older releases cannot import the new backup format.

The existing confirmed per-card, source-removal and all-study deletion paths also remove objective attempts. Study pause blocks recording; export remains available. No new permission, dependency, telemetry or network destination is introduced.

## Acceptance

Backend fixtures cover independent view/answer/self-assessment/schedule records, exact matching, legacy migration, concurrent retries, changed sources and cards, pause/suspension/deletion, source-scoped mistakes and backup round trips. DOM behavior tests cover repeated submission, uncertain-response retry, reveal/skip and stale responses after close/navigation. The existing Windows Edge visual job invokes `study-quiz-acceptance.cjs` against its isolated synthetic fixture to exercise exact-source navigation, lost-response retry and close/reopen races on the actual default UI. It is a CI acceptance step, not a claim of local browser execution.
