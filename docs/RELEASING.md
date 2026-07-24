# Releasing LearnNote

This checklist is for maintainers publishing a desktop, extension, container, or website release.

## Required checks

1. Update `APP_VERSION`, the extension manifest version, installer fallback version, cache-busting asset versions, and release links together.
2. Run:

   ```powershell
   .\scripts\audit-stage.ps1
   .\scripts\audit-product-acceptance.ps1 -Browser edge -RequireRealSiteAudits
   ```

3. Build the Windows installer and run the fresh-install and previous-version upgrade smoke tests.
4. Confirm the extension package contains only reviewed runtime files and branded icons.
5. Confirm `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `PRIVACY.md`, `SECURITY.md`, and `SUPPORT.md` are present in the portable package.
6. Open a pull request. `main` requires the `checks` status and resolved review conversations.
7. After merge, create an annotated `vX.Y.Z` tag. The Desktop Release workflow publishes the installer, portable ZIP, extension ZIP, and checksums.

## Windows signing

The release workflow supports Authenticode signing for both `LearnNote.exe` and the installer. Configure these repository Actions secrets:

- `WINDOWS_SIGNING_CERT_BASE64`: base64-encoded PFX certificate;
- `WINDOWS_SIGNING_CERT_PASSWORD`: PFX password;
- `WINDOWS_SIGNING_TIMESTAMP_URL`: RFC 3161 timestamp URL, optional.

Without the certificate, builds remain reproducible and checksum-verified but Windows can display an unknown-publisher warning.

## Browser stores

Store publishing requires maintainer-owned Chrome Web Store and Microsoft Edge Add-ons accounts. The reviewed listing copy and permission rationale live in:

- `extension/STORE_LISTING.md`
- `extension/PERMISSION_JUSTIFICATION.md`
- `PRIVACY.md`
- `site/privacy.html`

Upload the versioned extension ZIP produced by the release workflow. Do not upload a source-tree ZIP containing tests, task artifacts, or local configuration.

After approval, add store IDs and official listing URLs to the website and README. Store-installed extensions update through the browser; unpacked development extensions still require the user to click **Reload** after a client update.

## Docker and website

- The container workflow publishes GHCR images from `main`.
- GitHub Pages deploys only after desktop/mobile visual acceptance.
- A remote Docker deployment changes the local-only security boundary. Follow `SECURITY.md` and require HTTPS and authentication.
