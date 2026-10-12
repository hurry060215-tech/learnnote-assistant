# Public-media ASR benchmark resource measurements

`scripts/benchmark-public-media-asr.py` takes a local WAV prepared from a public
or explicitly authorized input. It still invokes LearnNote's real
`transcribe_audio` entry, including resumable 300-second windows for long WAVs.
It saves aggregate counts and timings, not transcript text. This resource fix
adds no downloads, model calls, dependencies, or new input sources.

## Interpreting the report

The top-level `status` and process exit code describe transcription: `pass`
requires `faster-whisper` output with at least one segment. Resource availability
has its own `resource_usage.status`; a successful transcription does not prove
that every resource was measured.

- `complete`: every scheduled sample has RSS, CPU, and disk observations.
- `partial`: samples exist, but one or more resource observations are missing.
- `unavailable`: no resource observations were collected, including when the run
  completes before the first one-second sampling tick.
- `error`: the sampler stopped with an unexpected exception. `sampler_error`
  contains its class name only, without arbitrary exception text. Any earlier
  observations remain available and are not presented as a complete record.

Missing measurements are JSON `null`, never invented zeros. `sample_count`
counts sampling ticks that produced a record; `rss_sample_count`,
`process_cpu_sample_count`, and `disk_sample_count` count available observations
for each metric. A measured zero remains a valid numeric value. Failed RSS or
disk observations do not discard the other metrics from the same tick.

Existing measurement semantics are preserved where supported:

- Windows uses `GetProcessMemoryInfo` current working-set bytes and reports the
  maximum observed working set. Process handles retain pointer-sized types.
- Linux and macOS use the existing resource helper's `getrusage` process-lifetime
  high-water RSS, converting Linux KiB to bytes and retaining macOS bytes. This
  can include a peak before the benchmark timer; it is not instantaneous RSS or
  a process-tree measurement.
- CPU percentages remain differences in process CPU time divided by wall time
  for each one-second interval. They can exceed 100% for multiple cores; the
  report retains the arithmetic mean and maximum of those intervals.
- Disk metrics are for the WAV's directory. The historical `before`/`after`
  field names refer to the first/last scheduled sample, not separate measurements
  taken exactly at inference boundaries. If that endpoint observation fails,
  it stays `null` even when another disk sample succeeded.

Sampling is still periodic, so sub-second peaks and short runs may have no
observations. Consumers that require a complete resource record must check
`resource_usage.status`, in addition to the transcription result.

## Deterministic regression evidence

On the pre-fix Linux script, a one-tick sampler with a synthetic one-second WAV
and a stub `WhisperModel` through the real `transcribe_audio` entry produced:

```text
sampler: AttributeError: module 'ctypes' has no attribute 'WinDLL'
status: pass
sample_count: 0
rss_peak_bytes: 0
process_cpu_percent_mean: 0
process_cpu_percent_peak: 0
```

The regression tests schedule a fixed number of ticks without sleeping for real
inference. They cover native resource collection, zero samples, missing RSS,
disk errors and endpoint gaps, interval CPU values, sampler exceptions before
and after a valid sample, transcript failure, and aggregate-only output.
Resource-helper tests also exercise Linux/macOS RSS units and mocked Windows
working-set, pointer-width, unavailable-API, and query-failure behavior.

Focused tests, with `PYTHONPATH=backend:.` (use the platform's path separator):

```text
python -m unittest scripts.tests.test_public_media_asr_benchmark scripts.tests.test_resource_monitor
```

For guarded verification, load `scripts/test-backend-offline.py` and run these
unittest modules inside its `offline_network()` context. Set `LEARNNOTE_DATA_DIR`
to a fresh isolated directory ending in `/data`, blank provider API environment
variables, and set `HF_HUB_DISABLE_TELEMETRY=1`, `ORT_DISABLE_TELEMETRY=1`,
`HF_HUB_OFFLINE=1`, and `TRANSFORMERS_OFFLINE=1` before imports.

These fixtures verify resource reporting and inference dispatch. They are not
an ASR accuracy or throughput benchmark, and mocked platform branches are not
native Windows/macOS execution evidence.
