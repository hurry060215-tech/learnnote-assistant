# Local upload admission policy

The versioned policy returned by `/api/storage` under `upload_policy`
reports the active byte limit, cumulative in-flight budget, required free disk
reserve, available disk space and available upload budget. It contains no paths
or file contents. Settings exposes the same storage capacity information.

Defaults are 4 GiB per video, 32 GiB cumulative in-flight upload bytes and a
512 MiB free-disk reserve. Multipart parsing is bounded before it can spool an
unlimited request, including when `Content-Length` is absent. Final-file writes
check capacity before every chunk. The preflight accounts for both spooled and
final copies. Quota and actual disk-full errors return HTTP 507 with the number
of bytes written/received and a recovery action; inaccessible storage returns a
path-free HTTP 503. Failed or disconnected uploads close their parser files,
remove partial final files and release byte reservations. Reservations from a
dead process are reclaimed on the next admission check.

## Explicit large-video configuration

Set these environment variables before starting the local backend, then restart:

- `LEARNNOTE_MAX_VIDEO_BYTES`: positive integer bytes per video.
- `LEARNNOTE_MAX_CONCURRENT_UPLOAD_BYTES`: positive integer total reserved bytes.
- `LEARNNOTE_UPLOAD_RESERVE_BYTES`: positive integer free bytes to retain.

For example, `LEARNNOTE_MAX_VIDEO_BYTES=6442450944` allows a 6 GiB video. Choose
an aggregate budget that covers both multipart and final-file copies. Raising a
limit does not bypass the free-disk check. Invalid, zero and negative settings
stop startup with a clear configuration error. Existing installations that do
not set these values retain the defaults. Limits are still enforced entirely
on the local computer and no upload is sent to LearnNote cloud storage.

After changing `LEARNNOTE_DATA_DIR`, restart the backend so the policy, spool,
uploads and reservation journal all point to the new data directory. Do not
move an active upload. Interrupted submissions can be retried once sufficient
space is available; completed staged files continue to use their existing
expiration/cleanup lifecycle.

## Reproducible acceptance

Run with the normal test environment and `PYTHONPATH=backend`:

`python -m unittest backend.tests.test_upload_limits backend.tests.test_upload_admission backend.tests.test_upload_process_budget`

The suite covers declared and chunked size overflow, real multipart disk-spool
cleanup on overflow/disconnect, low-space admission, injected OS disk-full on
the second write, cumulative concurrent admission and release, process-crash
reservation recovery, configurable large-video limits and a fresh interpreter
after selecting a different data directory. Disk-full injection proves the
error/cleanup contract without deliberately filling a user's disk. It is not a
claim of testing every filesystem, disk controller or network-mounted drive.
