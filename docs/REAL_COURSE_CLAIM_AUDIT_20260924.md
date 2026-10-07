# Stanford CS224N public lecture claim audit

- Date: 2026-09-24
- Candidate code commit: `2c8360fd77418aac39c3ea750f77dd847bab70da`
- Related issue: [#129](https://github.com/hurry060215-tech/learnnote-assistant/issues/129)
- Course page: [Stanford CS224N](https://web.stanford.edu/class/cs224n/)
- Video: [Lecture 1 – Intro and Word Vectors](https://www.youtube.com/watch?v=DzpHeXVSC5I)
- Video ID: `DzpHeXVSC5I`, duration: 4,816.887 seconds (80:16.887)
- Local caption input SHA-256: `ed348109b402b9ddf489886053ef560d7ba7cf8ded8efcdeb4226878d2389962`
- Local input: ignored `D:/learnnote-assistant-pkg4/build/package4/public-course/stanford-cs224n-lecture1.en-orig.vtt`

The Stanford course page links its publicly available Spring 2024 lecture playlist. The audit downloaded the English-original YouTube captions with `yt-dlp` without cookies, then parsed 3,322 timed caption segments locally. The VTT and video are not committed or distributed. Claims and gold labels are short human-written paraphrases anchored to two reviewed ranges about one-hot word encodings and softmax probabilities.

The fixture keeps only paraphrased evidence expectations and claim labels; it contains no transcript excerpts. Candidate evidence IDs and cue times are created from the downloaded local VTT at run time. The report is saved under ignored `D:/learnnote-assistant-pkg4/build/package4/public-course/real-course-claim-audit.json` for this checkout.

## Results

Eleven manually labeled claims were evaluated against the timestamped video transcript with the existing claim projection code:

- Gold labels: 5 direct semantic support, 2 located-only contradictions, 2 inferences, and 2 pending-review claims.
- None of the five supported paraphrases received the system's `direct` status; all five were `located_only`. Direct-support recall was 0/5. No claims were marked direct, so direct precision is undefined for this sample.
- The review gate retained all six non-direct gold claims (`recall = 1.00`) but also sent the five direct paraphrases for review (`precision = 6/11 = 0.545).
- Both pending-review claims received candidate time locations because their stated ranges overlap source captions. They remained reviewable and were not promoted to direct support.

This is a small English-only, single-lecture audit, not general semantic accuracy. It demonstrates that literal-clause support is conservative for real lecture paraphrases and that a timestamp/candidate match must not be presented as proof. A human must inspect the claim and linked segment. The automatic YouTube captions are themselves imperfect and were not treated as ground truth without manual review of the selected ranges.

## Reproduction

Download the public caption track without a browser profile, cookies, or login:

```powershell
& 'D:\learnnote-assistant\.venv\Scripts\yt-dlp.exe' `
  --skip-download --write-auto-subs --sub-langs en-orig --sub-format vtt `
  --no-cookies --no-cache-dir `
  --output 'build\stanford-cs224n-lecture1.%(ext)s' `
  'https://www.youtube.com/watch?v=DzpHeXVSC5I'
```

Run the audit from the repository root:

```powershell
D:\learnnote-assistant\.venv\Scripts\python.exe `
  scripts\real-course-claim-audit.py `
  --captions build\stanford-cs224n-lecture1.en-orig.vtt `
  --output build\real-course-claim-audit.json
```

The script stores only statuses, evidence locators and timestamped video URLs in its JSON output; it does not save transcript text. Unit coverage uses a constructed two-cue VTT and makes no network requests.

## Remaining #129 boundary

Keep #129 open. This audit adds a real public course transcript sample, but a production video task still needs a full path from generated note claims through evidence anchors to visible UI/source jumps. A larger, manually reviewed real-course set is also needed before changing the existing 60-case benchmark or making a wider accuracy claim.
