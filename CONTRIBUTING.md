# Contributing to LearnNote

Thank you for helping improve LearnNote. Contributions should preserve the
project's local-first design, truthful media handling, and evidence-grounded
notes.

By submitting a contribution, you agree that it is licensed under the
[Apache License 2.0](LICENSE), as described in section 5 of that license.

## Before opening an issue

- Use the latest release or current `main` branch.
- Search existing issues.
- Remove API keys, cookies, authorization headers, signed media URLs, private
  course names, personal data, and unredacted task artifacts.
- Use the security reporting process in [SECURITY.md](SECURITY.md) for a
  vulnerability or possible credential/data exposure.
- Use [SUPPORT.md](SUPPORT.md) for setup and usage help.

LearnNote does not record browser tabs, bypass DRM or access controls, fake
course progress, or grant permission to download media. Do not request or
submit code intended to add those behaviors.

## Development setup

The primary supported development environment is Windows with Python 3.12,
Node.js, Chrome or Edge, and FFmpeg. Keep repositories, build caches, task data,
models, and test media on a user-selected data drive where practical. Do not
hard-code `D:\LearnNote`; paths must remain configurable.

Install the backend test dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.test.txt
```

Install website test dependencies:

```powershell
npm ci
```

Never commit real API keys or authenticated browser data. Use local environment
variables, Windows Credential Manager through the client, or test doubles.

## Making changes

1. Create a focused branch from current `main`.
2. Keep the browser extension small: it detects the active page and explicitly
   hands evidence to the local client; processing belongs in the client/backend.
3. Bind the desktop backend to `127.0.0.1` by default. A remote Docker/server
   mode must be treated as a separate trust boundary with explicit deployment
   guidance.
4. Collect cookies or page evidence only after a user action. Redact sensitive
   values from logs, task snapshots, diagnostics, fixtures, screenshots, and
   exports.
5. Preserve the no-recording and no-DRM-bypass boundary. Return a clear,
   actionable failure when direct media is unavailable.
6. Ground generated notes in transcript and visual evidence. Never turn a
   model guess into a reported fact or silently report a fallback as success.
7. Keep the local data directory configurable and do not delete files outside
   the exact task or application-owned path.
8. Add focused tests for the changed behavior and failure path.

## Validation

Run the checks relevant to the change. Before a broad pull request, run the
same core checks as CI:

```powershell
$env:PYTHONPATH = "backend"
python -m compileall backend\app
python -m unittest discover backend\tests
python -m unittest discover scripts\tests -p "test_*.py"
python -m unittest desktop.tests.test_desktop_launcher

node --check extension\background.js
node --check extension\content.js
node --check extension\page_hook.js
node --check extension\sidepanel.js
node --check web\app.js
Get-ChildItem extension\tests\*.test.mjs | ForEach-Object { node $_.FullName }
node web\tests\markdown_render.test.mjs
```

For website changes:

```powershell
npm run test:site
```

For current-page media changes, include a redacted test matrix covering the
affected path (for example direct MP4, HLS/DASH, `blob:`/MSE evidence, expired
authentication, and unsupported DRM). Do not attach copyrighted or private
course media to the repository.

## Pull requests

Complete the pull request template. A reviewable PR should:

- explain the user-visible problem and exact scope;
- identify privacy, security, media-rights, and data-migration impact;
- include tests and visual evidence when UI changes;
- disclose new dependencies, bundled binaries, network destinations, or
  permissions;
- update `THIRD_PARTY_NOTICES.md` when dependency obligations change;
- avoid drive-by formatting, generated artifacts, and unrelated refactors.

Maintainers may ask for changes, split an oversized PR, or close work that
conflicts with the project's safety and product boundaries.

## Community conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
