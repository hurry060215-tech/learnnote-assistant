# LearnNote Browser Extension Store Listing

## Product name

LearnNote Current Video Assistant

## Short description

Send the video currently playing in Chrome or Edge to the local LearnNote desktop client for transcription, visual slicing, and evidence-grounded study notes.

## Detailed description

LearnNote is a local-first video learning assistant. This extension is the browser handoff layer for the LearnNote Windows desktop client.

Use it to:

- identify the video currently playing in the active tab;
- collect downloadable MP4, HLS, DASH, subtitle, iframe, and player-request evidence;
- verify that the selected media belongs to the visible page;
- send the selected page and media evidence to the LearnNote service running on `127.0.0.1`;
- open the corresponding task in the desktop client.

The extension does not record the browser tab. Video download, transcription, frame extraction, visual understanding, note generation, question answering, and exports run in the LearnNote client or in model providers explicitly configured by the user.

LearnNote does not bypass DRM, account permissions, paywalls, or learning progress controls. Only process content that you are authorized to access.

## Single purpose

The extension's single purpose is to identify the video currently playing in the active browser page and hand the media evidence to the user's local LearnNote desktop client.

## Category

Productivity

## Language

- Primary: Simplified Chinese
- Secondary: English

## Support and policy URLs

- Homepage: https://hurry060215-tech.github.io/learnnote-assistant/
- Privacy policy: https://hurry060215-tech.github.io/learnnote-assistant/privacy.html
- Security policy: https://hurry060215-tech.github.io/learnnote-assistant/security.html
- Support: https://github.com/hurry060215-tech/learnnote-assistant/issues
- Source code: https://github.com/hurry060215-tech/learnnote-assistant

## Store review notes

1. Install and start the latest LearnNote Windows client.
2. Open a normal public MP4, HLS, DASH, Bilibili, or YouTube video page and start playback.
3. Open the LearnNote side panel.
4. The panel displays the current video, candidate count, duration, and media integrity state.
5. Click **Send to LearnNote**. The extension sends evidence only to `http://127.0.0.1:<local-port>`.
6. The local client creates the task and performs the remaining processing.

Authenticated-page testing requires a reviewer-owned account. LearnNote does not include test credentials or attempt to bypass site authorization.
