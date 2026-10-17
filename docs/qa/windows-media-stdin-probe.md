# Windows media child-stdin diagnostic

Run after the existing pinned FFmpeg/FFprobe provisioning:

```powershell
python scripts/windows-media-stdin-probe.py build/media-stdin-probe
```

Dependencies are the existing Python test requirements and installed FFmpeg and
FFprobe. There are no downloads or provider requests. Upload only `report.json`
and the command log, never the temporary media or data directory.

The probe generates one owned 36-second A/V source with embedded synthetic SRT.
It then runs the actual `media.normalize_video` command twice, in fresh Python
workers. Their explicitly resolved FFmpeg/FFprobe paths are passed through and
checked against the actual child launch record. Both workers complete native imports before starting the same blocking
stdin control reader used by the visual fixture. Only the FFmpeg child's stdin
changes: first inherited from that worker's piped control input, then explicitly
`DEVNULL`. The parent's and worker's control channels remain intact. No command
flags, source bytes, tool version, or production media behavior are changed.

The report retains both cases, exact normalized command arguments, input/output
hashes, tool paths/version lines, direct child PID/exit evidence, final pipe byte
counts when available, elapsed time, and bounded startup/error records. Child
launch identity is emitted before waiting, so a worker timeout retains its known
command/PID even without a completed result. Each normalization has a 15-second
cancellation deadline; the parent waits at most 25 seconds for a result, then
requests cooperative shutdown. On Windows, an unnamed Job Object with
kill-on-close owns the worker and its descendants. Assignment must succeed
before a one-time stdin start handshake allows any child creation; failure is
closed, with no breakaway flag or fallback. POSIX uses an owned isolated process
group. Cleanup checks the retained tree even if the worker has already exited,
then terminates remaining descendants and closes the job handle. It never kills
by process name. Direct child reaping, parent exit and pipe reader drain are
reported separately from emergency tree cleanup. The ordinary stdin control
reader starts later and retains its shutdown channel.

A measured normalization timeout or FFmpeg error is diagnostic data. A missing
result, invalid identity, malformed output, control failure or cleanup failure
makes the command exit nonzero, with the attempted cases retained. A completed
probe is never a visual acceptance pass. Linux runs are marked
`windows_evidence: false`; only the actual hosted Windows comparison informs the
Windows hypothesis. A difference between the two runs is evidence about this
owned-input scenario, not by itself a general production root-cause proof. Both
outcomes remain visible, including timeouts; there is no winning-sample selection.

The independent 80-row reference gate and joined visual gate retain their own
full inputs, timings, thresholds and failure results. This probe neither retries
those gates nor changes production stdin or user cancellation behavior.

Focused contracts:

```powershell
python -m unittest scripts.tests.test_windows_media_stdin_probe -v
```

Windows containment follows the [Microsoft Job Objects contract](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) and [assignment semantics](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject).
