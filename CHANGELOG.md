# Changelog

All notable changes to LearnNote are documented here. The project follows semantic versioning while the `0.x` series is under active development.

## Unreleased

## 0.1.39 - 2026-07-24

### Added

- Apache-2.0 open-source governance and third-party notices.
- Branded application, installer, website, and browser-extension assets.
- Browser-store listing, permission, privacy, and review documentation.
- CodeQL, dependency review, Dependabot, scheduled reliability checks, and protected-branch contribution flow.
- Previous-version upgrade, synthetic long-video, and model-provider contract gates.

### Changed

- Browser extension setup now distinguishes install, reload, and version update actions.
- Windows release signing covers the desktop executable as well as the installer when a certificate is configured.

## 0.1.38 - 2026-07-24

### Added

- Reproducible real teaching-video case on the public website.
- Privacy and security policies.
- Installed-release smoke testing and SHA-256 release checksums.

### Fixed

- Rejected or repaired notes containing unsupported duration, terminology, or example claims.
- Media-export integrity metadata now describes the exported media file.
- Temporary downloader cookie files are cleaned up after success or failure.
- Current Edge extension smoke tests use the current side-panel controls.
