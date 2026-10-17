# Additional owned Edge zoom acceptance (#153)

The existing evidence-source gate now requests native browser presets 90%, 125%
and 150% in its fresh, owned Edge process before retaining the original 200%
source/cue gate. This is an acceptance-only change. No production UI, browser
profile, extension permission, OS scaling or security setting changes.

Each added case sends Ctrl+0 followed by the exact native minus/plus preset keys,
then checks actual devicePixelRatio and inverse CSS viewport dimensions. Body and
document CSS zoom remain 1 and visualViewport.scale remains 1. There is no device
metrics or page-scale emulation. Source marker Enter seeks to 10 seconds without
playing; Home/Enter on the source cues returns to the first cue. Existing strict
source geometry checks and owned-window capture run at each level. The reader's
secondary-action disclosure is keyboard opened, its export/study controls are
checked for full viewport containment, captured, and closed with Escape/focus
restoration. Each case and final cleanup verify the measured 100% baseline.

Images use `native-<percent>-<view>-owned-window.png`; Playwright/CDP images remain
diagnostics. The same verified owned PID, unique foreground HWND, single 96-DPI
display and unchanged wholly-contained DWM window bounds govern every OS capture.
No capture crops or moves the window. Nonblank pixels alone can include browser
chrome, so a human must inspect the visible reading/source/control content.

The report retains each requested preset, observed metrics, captures, keyboard
assertions and reset outcome, including partial cases on failure. Cleanup closes
all created resources and keeps the original failure when reset/report/close also
fails. Local tests use inert adapters only; actual native execution and screenshot
inspection are pending the reviewed hosted run.

This proves only the actual hosted window dimensions recorded in that run. It is
not a 390/768/1024/1440 physical-device matrix, low-end performance benchmark,
native macOS WebView zoom result, or approved ImageGen-concept fidelity review.

## First hosted run and retained visual limitation

Exact `4d8ec2f7883bdad1b002e75642d881dd523680f2` passed
[UI 39000583101](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39000583101),
CI 39000583034 and CodeQL 39000583087. Artifact `12088629477` has SHA-256
`6ec440a2045414ac08c82ec0ef58eeea989aa25f589b21aecb424b5f976b7a41`.
All 11 owned-window images were inspected. Actual claims and focused captions
rendered, but Edge's translation offer occluded upper-right content and Export
at 90/125%. These original images remain evidence of that limitation, not clean
secondary-control visual acceptance. The native metrics and keyboard assertions
passed: 90% 1128×706/DPR0.899999976, 125% 813×509/1.25, 150% 677×424/1.5,
200% 508×318/2, with final restoration to 1016×636/DPR1.

The follow-on invokes only the exact native translation offer's “Not now” control
in the verified disposable Edge window before the keyboard baseline. It requires
an exact English heading, paired Translate button, non-document subtree, process
ownership, visibility, bounds and InvokePattern; ambiguous candidates fail closed.
It does not translate, change preferences, send Escape or dismiss security UI.
Absence is reported rather than claimed as a dismissal. Actual Windows UI
Automation behavior and unobscured replacement images still require a new hosted
run and manual visual inspection; local contract/fault tests are not that proof.
