# Third-Party Notices

LearnNote is licensed under the Apache License, Version 2.0. It uses
third-party software under separate licenses. Those licenses apply to the
respective components and are not replaced by the LearnNote license.

This document covers the principal direct runtime components and release tools
declared by this repository. Python and JavaScript package installations can
include additional direct and transitive dependencies. The authoritative
copyright notices and license texts are the ones distributed by each upstream
project and installed package.

## Media acquisition and processing

| Component | Use in LearnNote | Upstream | License |
| --- | --- | --- | --- |
| FFmpeg | Media probing, remuxing, audio extraction, frame extraction, HLS/DASH processing | <https://ffmpeg.org/> | The bundled Windows 7.1 Gyan essentials build reports `--enable-gpl --enable-version3` and is GPL v3 or later |
| imageio-ffmpeg | Locates and can provide an FFmpeg executable when a system FFmpeg is unavailable | <https://github.com/imageio/imageio-ffmpeg> | BSD 2-Clause for the Python package; bundled FFmpeg executables retain the applicable FFmpeg license |
| yt-dlp | Resolves and downloads media that the user is authorized to access | <https://github.com/yt-dlp/yt-dlp> | The Unlicense for the source/Python distribution used by LearnNote |
| Pillow | Image decoding, resizing, frame grids, and exports | <https://python-pillow.github.io/> | MIT-CMU (HPND-style) |

The bundled executable's GPLv3 text and corresponding-source references are
included under `third_party/`. The release audit rejects an FFmpeg binary built
with `--enable-nonfree`. Redistributors must repeat that audit when replacing
the binary. LearnNote does not grant rights to download or process third-party
media; users and redistributors remain responsible for authorization and
applicable website terms.

The upstream yt-dlp project documents different licensing for some of its
standalone release artifacts, including GPL-covered PyInstaller executables.
LearnNote declares the Python distribution in `backend/requirements.txt`;
redistributors must re-audit notices before substituting a standalone yt-dlp
binary or adding optional yt-dlp components.

## Transcription and model clients

| Component | Use in LearnNote | Upstream | License |
| --- | --- | --- | --- |
| faster-whisper | Optional local speech-to-text engine | <https://github.com/SYSTRAN/faster-whisper> | MIT |
| CTranslate2 | Inference runtime used by faster-whisper | <https://github.com/OpenNMT/CTranslate2> | MIT |
| OpenAI Python | OpenAI-compatible API client for transcription and note generation | <https://github.com/openai/openai-python> | Apache License 2.0 |

Models are separate works from these libraries. Whisper-compatible model
weights and remote model services can have their own licenses, acceptable-use
terms, privacy policies, retention rules, and geographic restrictions. A model
being selectable in LearnNote does not mean that LearnNote redistributes or
licenses that model.

## Application runtime

| Component | Use in LearnNote | Upstream | License |
| --- | --- | --- | --- |
| FastAPI | Local HTTP API | <https://github.com/fastapi/fastapi> | MIT |
| Uvicorn | Local ASGI server | <https://github.com/Kludex/uvicorn> | BSD 3-Clause |
| Pydantic | Request, settings, and task data validation | <https://github.com/pydantic/pydantic> | MIT |
| Requests | HTTP client | <https://github.com/psf/requests> | Apache License 2.0 |
| python-multipart | Local video upload parsing | <https://github.com/Kludex/python-multipart> | Apache License 2.0 |
| PyWebView | Windows desktop application shell | <https://github.com/r0x0r/pywebview> | BSD 3-Clause |

PyWebView can use the Microsoft Edge WebView2 Runtime on Windows. WebView2 is
provided under Microsoft's terms and is not licensed by this repository.

## Development and release tooling

| Component | Use in LearnNote | Upstream | License |
| --- | --- | --- | --- |
| Playwright | Website visual acceptance tests | <https://github.com/microsoft/playwright> | Apache License 2.0 |

The Windows build and installer can also use PyInstaller, Inno Setup, and
platform tooling. Their licenses and any notices included with a generated
artifact continue to apply. Container base images and operating-system
packages likewise retain their own licenses.

## No endorsement

Names and trademarks are used only to identify compatible components and
services. Their owners do not sponsor or endorse LearnNote.

## Updating this file

When adding, removing, or changing a runtime dependency or bundled binary:

1. verify the license from the upstream source or installed package metadata;
2. update this file and any release-time license bundle;
3. check whether the new license imposes source, notice, attribution, patent,
   or redistribution obligations;
4. document whether user content or credentials leave the local machine.

This file is an attribution aid, not legal advice.
