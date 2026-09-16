# Post-0.2.10 pull request cleanup

The release tag remains immutable. This maintenance change consolidates open dependency PRs without replacing published 0.2.10 artifacts.

Included proposals: #166 (ReportLab 5.0.1), #168 (Pages deploy patch), #175 (OpenAI 3.13.0), #176 (filelock 3.32.6), #178 (NumPy 2.5.3), #179 (Playwright 1.63.0), #180 and #181 (matching CodeQL init/analyze 4.38.0).

Rejected proposal: #177 changes only pydantic-core to 2.49.0 while the lock pins Pydantic 2.13.5, whose installed distribution metadata requires pydantic-core == 2.46.5. Retain the compatible pair.

CodeQL's split updates failed with a configuration-version mismatch between 4.38.0 and 4.37.9. Upgrade both actions together. Dependabot now groups their future updates and groups Python minor/patch updates for coordinated resolution.

Windows CI now resolves both the production lock and test requirements, so incompatible transitive lock edits fail before tests. Playwright manifest changes now trigger the full browser acceptance workflow. Validate the consolidated branch with CI, CodeQL, UI acceptance and a non-publishing desktop build/install workflow before merging and closing the superseded PRs.
