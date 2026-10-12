# Native runtime privacy guard

The optional ONNX Runtime 1.30.0 dependency has a native telemetry transport.
Its Python API disables non-essential events, but cannot prevent an initial
event created before that API is called. The official versioned documentation
requires `ORT_DISABLE_TELEMETRY=1` **before initialization** for the complete
non-Windows process-lifetime opt-out:
[ONNX Runtime 1.30 privacy controls](https://github.com/microsoft/onnxruntime/blob/v1.30.0/docs/Privacy.md#disabling-telemetry).

LearnNote now sets that opt-out before model imports in the app package,
offline runner, standalone decoder probe, Docker image and build workflows.
Hugging Face's dedicated usage telemetry is also disabled before library initialization.
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

## Hugging Face Hub 2.2 compatibility boundary

Hub 2.2 remains compatible with the guard and the explicit local-model preparation
path when paired with tokenizers 0.23.3. The latter raises its supported Hub upper
bound to `<3`; older tokenizers 0.23.2 rejects Hub 2.x. The real helper's legacy
`local_dir_use_symlinks` argument is still accepted and discarded by Hub validation.

The dedicated telemetry opt-out does **not** disable every form of server-side
download counting. Hub 2.2 adds `X-HF-Download-Counter: 1` to existing download
requests. It introduces no separate request or user identifier, but it is not
controlled by `HF_HUB_DISABLE_TELEMETRY`. Normal explicitly requested model
downloads still disclose their requested model and network metadata to the model
host. See the [upstream download-counter change](https://github.com/huggingface/huggingface_hub/pull/4613).
No actual model download or credential transmission is part of this compatibility
test; local fixtures do not establish remote TLS, proxy or transfer-recovery behavior.

Hub's shared Xet cache retains snapshots and refs while deduplicating payloads
under the existing cache root. LearnNote recognizes those files without rewriting
them, and explicit preparation uses ordinary local output files. No migration or
cache deletion is performed. If rolling back Hub, avoid using an older Hub cache
deletion client against this newer shared cache: upstream documents that old
deletion logic can follow symlinks to a payload shared by another model repository.
LearnNote does not invoke those deletion APIs. See the
[upstream shared-cache change](https://github.com/huggingface/huggingface_hub/pull/4498).
