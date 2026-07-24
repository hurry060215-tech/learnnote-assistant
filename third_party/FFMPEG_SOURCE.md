# Bundled FFmpeg source and license

The Windows LearnNote distribution currently includes the FFmpeg executable shipped in the `imageio-ffmpeg 0.6.0` Windows wheel:

```text
ffmpeg-win-x86_64-v7.1.exe
ffmpeg version 7.1-essentials_build-www.gyan.dev
```

The executable reports `--enable-gpl --enable-version3` and is therefore distributed under **GNU GPL version 3 or later**, not LGPL. The complete GPLv3 text is included at `third_party/licenses/GPL-3.0.txt`.

## Corresponding source

- FFmpeg 7.1 source tag: https://github.com/FFmpeg/FFmpeg/tree/n7.1
- FFmpeg 7.1 source archive: https://github.com/FFmpeg/FFmpeg/archive/refs/tags/n7.1.tar.gz
- Gyan Windows build project and release metadata: https://github.com/GyanD/codexffmpeg
- Gyan FFmpeg 7.1 release: https://github.com/GyanD/codexffmpeg/releases/tag/7.1
- Build provider documentation and external-library list: https://www.gyan.dev/ffmpeg/builds/
- imageio-ffmpeg source: https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0

The exact enabled-library configuration is preserved in the executable and can be printed with:

```powershell
ffmpeg-win-x86_64-v7.1.exe -version
```

LearnNote calls FFmpeg as a separate command-line program. LearnNote's own source is licensed under Apache-2.0; that license does not replace the GPL terms that apply to the bundled FFmpeg executable.

Redistributors who replace the bundled executable must inspect the replacement's `-version` output, update this document, include the applicable license text, and satisfy the corresponding-source obligations for that build. A build containing `--enable-nonfree` must not be distributed.
