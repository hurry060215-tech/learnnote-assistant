# LearnNote release reliability matrix

This matrix defines repeatable gates for release packaging, upgrades, long-video
processing, provider presets, and public media acquisition. Scheduled gates do
not require user accounts, browser login state, or API keys.

## Gate matrix

| Gate | Command | Default scope | Network or credentials | Pass criteria |
| --- | --- | --- | --- | --- |
| Installer smoke | `.\scripts\test-release-installer.ps1 -InstallerPath .\LearnNote-Setup-x64.exe` | Clean install, startup, extension files, uninstall | None | App starts and external data survives uninstall |
| Cover upgrade | `.\scripts\test-upgrade-installer.ps1 -PreviousInstallerPath <old.exe> -CurrentInstallerPath <new.exe>` | Previous-to-current upgrade under `D:\LearnNoteUpgradeSmoke` | None | Configuration and external data survive, extension version increases, upgraded app starts |
| Long-video media | `python scripts/long-video-reliability.py` | Synthetic 60-minute MP4, media integrity, adaptive frames, 3x3 grids | None | Audio/video tracks, duration, timeline coverage, frames, and grids are valid |
| Provider presets | `python scripts/model-provider-contract.py` | Offline schema, URL, classifier, ASR, and vision checks | None | Every preset is internally consistent and no network call occurs |
| Explicit provider live check | `python scripts/model-provider-contract.py --live-provider kimi` | One short completion for the selected provider | Explicit provider API key | The configured model returns the contract marker |
| Public sample acquisition | `.\scripts\audit-real-site.ps1 "https://samplelib.com/sample-mp4.html" -TaskProbe -YtdlpProbe -RequireReady -Browser edge` | Public, no-login MP4 sample | Public internet only | Evidence reaches `ready_to_download` and a local download task succeeds |

## Upgrade safety contract

`test-upgrade-installer.ps1` accepts two existing Inno Setup installers. Every
temporary path is resolved and must remain below `D:\LearnNoteUpgradeSmoke`. Each
run receives a random directory with sibling `app` and `external-data` folders.

The test installs the previous version, writes a real `learnnote-config.json`
pointing to the external data directory, records configuration and data sentinels,
and installs the current version over the same application directory. It verifies:

1. The current extension manifest version is greater than the previous version.
2. The configuration file remains byte-for-byte unchanged.
3. The external data path and both sentinels remain unchanged.
4. The upgraded `LearnNote.exe --help` startup check succeeds.
5. The current uninstaller succeeds without deleting external data.

Use disposable release installers only. The gate rejects any path that escapes
the dedicated D-drive smoke directory.

## Long-video policy

The default long-video gate creates or reuses a low-bitrate 60-minute synthetic
video. It exercises media probing, track validation, adaptive frame extraction,
timeline coverage, and grid generation. It does not load faster-whisper,
transcribe audio, call a language model, or send images to a visual API.

```powershell
python scripts/long-video-reliability.py `
  --media D:\Samples\lecture.mp4 `
  --output-dir D:\LearnNoteReliability\lecture `
  --frame-interval 90 `
  --max-frames 60 `
  --keep-artifacts
```

Without `--keep-artifacts`, extracted frames and grids are removed after the
report is written. A valid generated synthetic video is retained and reused.

## Provider policy

The provider contract reads `MODEL_PROVIDER_PRESETS` from source with Python AST
literal evaluation. Offline mode validates required fields, unique keys, HTTPS
base URLs, provider classification, capability declarations, transcriber
compatibility, and model names.

Live checks are opt-in only:

```powershell
$env:LEARNNOTE_KIMI_API_KEY = "<key>"
python scripts/model-provider-contract.py --live-provider kimi
```

`--live-provider` is never used by the scheduled workflow. The script does not
print API keys. A provider-specific `LEARNNOTE_<PROVIDER>_API_KEY` is preferred,
with `LEARNNOTE_LLM_API_KEY` as an explicit local fallback.

## Scheduled workflow

`.github/workflows/reliability.yml` runs every Monday at 18:23 UTC and can also
be started manually. It has read-only repository permissions and two jobs:

- Offline reliability runs hardening contracts, the provider schema gate, and
  the full synthetic 60-minute media/frame test.
- Public sample audit checks a public MP4 page in Microsoft Edge and uploads
  redacted evidence.

The workflow does not use login state, private courses, cookies, or API keys.
Login-required learning platforms remain part of explicit local acceptance, not
unattended CI.
