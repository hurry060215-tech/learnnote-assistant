# Native runtime privacy guard

The optional ONNX Runtime 1.30.0 dependency has a native telemetry transport.
Its Python API disables non-essential events, but cannot prevent an initial
event created before that API is called. The official versioned documentation
requires `ORT_DISABLE_TELEMETRY=1` **before initialization** for the complete
non-Windows process-lifetime opt-out:
[ONNX Runtime 1.30 privacy controls](https://github.com/microsoft/onnxruntime/blob/v1.30.0/docs/Privacy.md#disabling-telemetry).

LearnNote now sets that opt-out before model imports in the app package,
offline runner, standalone decoder probe, Docker image and build workflows.
Hugging Face usage telemetry is also disabled before library initialization.
Both scanned-PDF and frame OCR use one initializer; the API opt-out remains as
the documented Windows control and additional protection. These are app/process
settings, not changes to the user's OS telemetry or network configuration.

When embedding LearnNote in an existing Python process, set the environment
before importing any ONNX-dependent library and restart the process. This does
not retroactively describe or undo traffic from earlier processes. CI passing
alone was insufficient evidence because CI environments can suppress native
telemetry differently from normal desktop execution.

## Verification and limits

- First, a full restored-environment test was blocked by the execution reviewer
  on an unexpected Microsoft telemetry attempt. Payload was not established.
- Merely centralizing PDF initialization and calling the API early did not fix
  it: a second full run was also blocked. Neither interrupted run is a pass.
- After the documented pre-initialization opt-out, a fresh process completed
  **724 backend tests without skips**, including real local OCR, with no repeat
  of the blocked attempt. Eleven focused privacy/cache tests passed.
- Tests prove app import sets the opt-out before native import, PDF/frame OCR
  share the initializer, API ordering is retained, and new direct OCR
  constructors cannot silently bypass the guard. No proxy, firewall or access
  control was weakened, and no telemetry transmission was authorized.

This evidence is specific to the fresh process and tested dependency pins. It
does not claim an exhaustive audit of all third-party native libraries or the
operating system. Future dependency updates must preserve the startup guard.
