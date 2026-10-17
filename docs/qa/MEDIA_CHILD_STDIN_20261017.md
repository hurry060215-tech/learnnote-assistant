# Owned media subprocess stdin fix

Source fix: `319cae7de21d5b9431cfcce8ae14a69c2ae9bf3e`, based on `d579b954d24d2925e0ab59e3d8a2fef7ecab38a4`.

Status: local regression checks passed; the prior A/B diagnostic remains **failed** (`diagnostic_complete: false`), and combined-tree hosted Windows validation remains **pending**.

## Scope and caller contracts

Explicit subprocess.DEVNULL at these twelve launch boundaries:
1. media._run ordinary subprocess.run, used by normalize_video, extract_video_clip, extract_audio.
2. media._run cancellable subprocess.Popen, same callers under media_cancellation.
3. media.probe_duration ffprobe JSON query.
4. media.probe_duration FFmpeg duration fallback.
5. media._integrity_from_ffprobe stream/format metadata.
6. media._integrity_from_ffmpeg stream metadata fallback.
7. media.extract_embedded_subtitle.
8. media.detect_scene_change_timestamps.
9. media._extract_frame_batch.
10. media._extract_single_frame.
11. downloader.MediaDownloader._download_file_with_audio for separated video/audio inputs (called from _download_file).
12. downloader.MediaDownloader._download_manifest for HLS/DASH (called from _download_candidate).

All current production callers supply file paths or URLs as media input; none passes subprocess input bytes, a stdin pipe, pipe:0, or -i -. FFmpeg filter expressions are command-line arguments (-vf scale in clip extraction, -vf select/showinfo in scene detection), not scripts or bytes supplied through stdin. The scene detector's final '-' is the null-format output destination, not stdin input. No filter script input exists in these boundaries.

The yt-dlp CLI launch and shared runtime.text_subprocess_kwargs are unchanged. No product-wide subprocess monkeypatch, parent stdin mutation, diagnostic changes, dependency changes, or SLO changes. Test instrumentation is confined to owned test children. Existing communicate timeout polling, cancellation kill/reap/drain and error handling are unchanged.

## Documentation and bounded observed evidence

Official FFmpeg documentation checked 2026-10-17: [stdin option](https://ffmpeg.org/ffmpeg.html#stdin-option) says stdin interaction is enabled by default unless stdin is itself media input; disabling interaction is useful for background operation, and redirecting stdin to a null device has roughly the same effect. The [official FAQ section 3.19](https://ffmpeg.org/faq.html#How-do-I-run-ffmpeg-as-a-background-task_003f) discusses console polling and supports null-device redirection, including NUL on Windows. This supports child-local noninteractive stdin isolation without a shell; it does not establish every possible Windows hang's cause.

Retained owned Windows FFmpeg 8.1 normalization A/B: inherited arm supplied no final record at 25 seconds; DEVNULL arm completed in 0.875 seconds with exit 0, direct child reaped and reader threads drained. Both workers used cooperative cleanup. Same owned input and normalization command. Evidence: [GitHub Actions run 39020270521](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39020270521) (terminal failure at base `d579b954d24d2925e0ab59e3d8a2fef7ecab38a4`), retained artifact `12095594872`, report `media-stdin-probe/report.json`; artifact SHA256 51f15b9f20c0361a6172d8191e6ac8512e2605d342913f08ff70e0a97ae54b0a. This is bounded evidence for this normalization scenario, not a general root-cause claim or an end-to-end Windows acceptance pass.

## Verification

- Four focused stdin/cancellation tests passed in 0.263 seconds.
- Combined focused suite (new stdin, existing process cancellation, downloader priority): 62 tests passed in 32.461 seconds.
- New normal/cancellable normalization regression launches real owned Python children through the production subprocess boundary, asserts DEVNULL and EOF, produces more than pipe capacity on both streams, checks child reaping and closed output pipes, and checks atomically published output and temporary cleanup.
- New cancellation regression checks killed/reaped child, closed output pipes, removal of partial normalization output, and preservation of an existing destination.
- Metadata and extraction call-site tests assert child stdin disconnection, including FFmpeg duration fallback. Existing downloader manifest and separated audio/video tests now assert DEVNULL.
- compileall backend/app and git diff --check passed.
- Full `scripts/test-backend-offline.py` run passed on the unchanged source fix: 1,898 tests in 158.278 seconds, 21 skipped. Skips are not counted as passes. This local Linux run is not Windows acceptance.
- Hosted actual Windows normalization/control/cancellation and progressive pipeline remain to be validated on the combined tree. No visual acceptance claimed here.
