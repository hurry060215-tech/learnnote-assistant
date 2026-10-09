# Evidence navigation increment

Related scopes: #129, #139 and #159. Existing source evidence IDs now select the exact saved document excerpt in the source panel. The complete original remains visible even if other index entries are missing. Duplicate or missing IDs are reported instead of selecting a similarly worded paragraph.

Video citations can carry a persisted `window_id`. The source panel displays that task's exact image window using local task assets; absent or ambiguous window IDs never select a substitute. Playback also follows the actual containing window and clears the image in uncovered time gaps. Image captions explicitly ask the reader to compare the original image with the transcript. This feature adds navigation and does not classify an image or a generated claim as verified evidence.

Card source lookups share an explicit request order with claim-inspector navigation, so an older lookup cannot win over a newer click. Transcript timestamps remain the seek target. The existing frame-index view continues to show all grids independently.

Validation includes production-function DOM regressions for canonical document IDs, full-original preservation, frame asset ownership, missing/ambiguous windows, playback selection, and reordered card lookups. The default studio's actual Edge acceptance checks a document-card backlink. A second isolated Edge flow uses a generated WAV, two local JPEGs and one canonical evidence card to check playback following and card-to-window navigation. No downloads, user files, or models are required by those fixtures. Actual browser results must be recorded from the final CI head.

Remaining boundaries: this change does not establish general paraphrase verification, migrate historical claim IDs, validate native WebView behavior, or complete every acceptance condition in the related epics.
