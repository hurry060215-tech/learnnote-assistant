# Reliability gates on current main

- Date: 2026-09-24
- Main SHA tested: `7c26264fdac8aa2f56a95d264a8976fefe3d2041`
- Workflow: [Reliability gates run 36022676436](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/36022676436)
- Related issue: [#130](https://github.com/hurry060215-tech/learnnote-assistant/issues/130)

The workflow completed successfully on the stated `main` SHA. Checkout freshness passed, followed by release-hardening contracts, the offline provider contract, synthetic 60-minute media/frame validation, the synthetic 30/60/180-minute resource matrix, cancellation, mixed durable scheduling, and the full local 60-minute task path. The public sample audit also passed with an unauthenticated browser profile and no private cookies.

The run uploaded `offline-reliability-36022676436` and `public-sample-audit-36022676436`. The 180-minute resource result is synthetic media/frame processing. The full 60-minute local task uses prepared subtitle input and an offline summary fixture; neither measures real 60-minute ASR or a model-generated note. Real public-course ASR measurements are recorded separately in [RELIABILITY_CLOSEOUT_20260924.md](RELIABILITY_CLOSEOUT_20260924.md).

Release workflows run `scripts/reliability-freshness.py` against the release SHA. Each future release candidate therefore needs its own current or demonstrably equivalent successful evidence; this run does not authorize or trigger a Release.
