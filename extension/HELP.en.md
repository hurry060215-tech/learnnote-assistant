# LearnNote extension help (English)

## Connect the local workspace

1. Install the [latest LearnNote desktop client](https://github.com/hurry060215-tech/learnnote-assistant/releases/latest).
2. Open a specific video page you are authorized to use and start playback.
3. Open the LearnNote side panel. Choose **Open workspace** and accept the browser's app-launch prompt if shown. For the portable client, start the app yourself first.
4. Wait for **Local workspace connected**. If the panel reports incompatible protocols, update the extension and client, then reconnect with the top-right button.

The extension only connects to a local LearnNote service at `127.0.0.1` or `localhost`. No LearnNote cloud account is required.

## Choose the right mode

- **Extract transcript:** saves existing subtitle text. It does not download video, recognize speech, or call a model. When subtitles are unavailable, the task stops and explains why.
- **Generate text note:** uses available subtitles with your configured text model. When subtitles are missing, review and confirm local speech recognition in the workspace. It does not analyze images.
- **Generate visual note:** uses the video, subtitles, and selected frames with a vision model configured in the workspace. Review the model and scope before starting.

The panel checks whether a model is configured; it cannot guarantee the provider's quota or availability before the actual request. Transcript-only mode does not require a model.

Use **Study a section** to set start/end seconds, or fill the end from the current playback position. The range is applied when you send. Search the original transcript and select a timestamp to return to the source video. A changed source invalidates old preflight results.

## Permissions and privacy

Opening the panel reads subtitle and player evidence from the active tab. Media preflight and task sending require authorization for that site. The browser's permission request appears when needed.

For an authorized site, source preflight can send media candidates to the local workspace. Video processing may read cookies for the relevant page and media hosts; they go only to the local workspace, never to a model. Transcript-only mode does not read cookies. Remote models explicitly chosen in the client may receive task subtitles or selected frames.

Open **Site permissions and data flow** to revoke a site. Revocation clears related capture caches and stops future capture. Tasks already handed to the local workspace remain available there and can be cancelled or deleted there.

The extension does not record browser tabs, bypass DRM or paywalls, or modify course progress. Only process content you have permission to use.

## Language and original content

The extension follows the browser display language: English browsers use English; other unsupported languages fall back to Simplified Chinese, the manifest default. Change the browser display language and reopen the panel to switch. Both catalogs are bundled, so missing browser messages have a local fallback.

Language changes affect product labels, status messages, and accessibility text. Course titles, subtitles, notes, model answers, questions, and custom instructions remain in their original language. Unknown service/provider diagnostics are shown verbatim rather than machine-translated or hidden.

## Troubleshooting

- **No source:** open a specific video rather than a homepage preview, play a few seconds, then identify again.
- **Sign-in required:** sign in on the original site, refresh the video, and identify again. LearnNote does not supply credentials or bypass authorization.
- **Permission denied/revoked:** no new task is created. Click Send and authorize again if you want to continue.
- **Client offline:** open the client and reconnect. A task remains associated with the workspace that created it.
- **No response while launching:** check the browser's launch prompt and installation. The panel does not repeatedly launch the app automatically.

For help, open a [support issue](https://github.com/hurry060215-tech/learnnote-assistant/issues). Include the extension/client versions and redacted error text. Never attach cookies, API keys, signed media URLs, private course material, or personal information.
