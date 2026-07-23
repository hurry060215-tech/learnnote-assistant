# LearnNote Security

LearnNote is a local-first desktop application. This document describes the
security properties that are implemented today, the limits of those
properties, and how to report a problem.

For data handling details, see [PRIVACY.md](PRIVACY.md).

## Supported versions

Security fixes are provided for the latest published release. Before reporting
an issue, reproduce it with the latest version when possible. Older builds may
no longer receive fixes.

## Implemented security boundaries

- The Windows desktop client starts its FastAPI backend on `127.0.0.1` by
  default. It is not intended to accept connections from other machines.
- A custom Docker or server deployment changes that boundary. Operators are
  responsible for authentication, HTTPS termination, firewall rules, access
  logs, backups, and host security. Do not expose the service directly over
  unencrypted HTTP.
- The browser extension only connects to a configured local LearnNote origin
  on `127.0.0.1` or `localhost`. It observes media-related page and network
  evidence locally, then sends cookies and page evidence to the local backend
  when the user opens/runs preflight in the side panel or clicks the send
  action.
- Model API keys saved by the installed Windows client use Windows Credential
  Manager under a `LearnNote/model/<provider>` target. They are loaded into the
  running application when needed and are not intentionally written to task
  JSON, diagnostics, or export bundles.
- Persisted task snapshots and generated diagnostics redact cookie values,
  authorization headers, API keys, request bodies, and sensitive URL
  parameters where supported.
- The updater accepts the Windows installer only from the project's GitHub
  Releases path and verifies its SHA-256 value against release metadata or
  `SHA256SUMS.txt` before installation.

## Important limitations

- Localhost is not an authentication boundary against other software running
  as the same user. Keep the operating system and browser profile protected,
  and do not run untrusted local programs while LearnNote is processing
  authenticated content.
- SHA-256 verification detects a corrupted or substituted download relative to
  the published checksum. It does not replace operating-system publisher
  signing. Users should obtain releases only from this repository.
- To let `yt-dlp` reuse an authenticated browser session, LearnNote creates
  short-lived `cookies.txt` or `subtitle_cookies.txt` files in Netscape cookie
  format and removes them after each download attempt. A crash or forced
  termination can interrupt cleanup, so treat the LearnNote data directory as
  sensitive and remove any stale cookie files before sharing a task directory.
- A remote model or ASR provider receives the content required for the selected
  operation. The provider's own security, retention, and training policies are
  outside LearnNote's control.
- LearnNote does not bypass DRM, account permissions, paywalls, or website
  authorization. Only process content that you are permitted to access.

## Reporting a security issue

Do not include API keys, cookies, authorization headers, private video URLs,
personal data, or unredacted task archives in a public issue.

For a non-sensitive security hardening request, open a
[GitHub issue](https://github.com/hurry060215-tech/learnnote-assistant/issues/new)
with the affected version, Windows/browser version, reproduction steps, and a
redacted diagnostic report.

For a vulnerability that could expose data or credentials, use the repository
Security tab's **Report a vulnerability** option if it is available. If private
vulnerability reporting is unavailable, open a minimal public issue asking the
maintainer for a private contact channel, without disclosing technical details.

Reports should include:

- affected LearnNote and extension versions;
- whether the desktop client or a custom Docker/server deployment was used;
- the expected and observed behavior;
- minimal, redacted reproduction steps;
- the potential impact;
- whether the issue is already being exploited.

Please allow the maintainer time to investigate and publish a fix before
disclosing sensitive details.
