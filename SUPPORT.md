# LearnNote Support

## Where to ask

Use a GitHub issue for reproducible product problems and feature proposals:

- **Bug report**: client, extension, export, transcription, visual slicing, or
  note behavior.
- **Media/site compatibility**: a public or redacted page that LearnNote cannot
  detect or download.
- **Feature request**: a concrete learning workflow that fits LearnNote's
  local-first boundaries.

For a possible vulnerability, credential leak, unauthorized data access, or
privacy failure, do not open a detailed public issue. Follow
[SECURITY.md](SECURITY.md).

Community support is best effort. There is no guaranteed response time or
private one-to-one support channel.

## Before filing

1. Update the desktop client and browser extension to the same latest version.
2. Confirm the client is running and the extension reports that the local
   service is connected.
3. For a current-page task, refresh the page, play the intended video for
   several seconds, then run detection again.
4. Try a local video to distinguish a page-detection problem from a
   transcription or model problem.
5. Export a redacted diagnostic report when the client provides one.

## Safe diagnostic information

Useful:

- LearnNote and extension versions;
- Windows, Chrome, or Edge version;
- task phase and structured error code;
- whether the source was local, direct URL, MP4, HLS, DASH, or `blob:`/MSE;
- whether local or remote transcription and text or vision summarization were
  selected;
- redacted logs, screenshots, and a minimal public test page.

Never post:

- API keys, cookies, authorization headers, browser profiles, or credentials;
- private or signed media URLs and URL query tokens;
- personal data or unredacted course/account information;
- copyrighted videos, paid course files, or complete task directories you are
  not allowed to redistribute.

## Product boundaries

LearnNote attempts to reuse media resources that the current authorized browser
session can access, or processes a local file supplied by the user. It does not
record the browser tab, bypass DRM or access controls, grant download rights,
complete lessons, or fabricate learning progress.

When a site exposes only protected or non-reusable playback data, the supported
fallback is a user-authorized local video or page-text note. Compatibility with
a site can change when its player or authorization flow changes.

## Deployment boundary

The desktop backend listens on `127.0.0.1` by default. A Docker or server
deployment is an operator-managed mode and requires authentication, HTTPS,
network controls, backups, and a deliberate data-retention policy. Do not
expose the raw LearnNote API to the public internet.
