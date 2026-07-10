from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "test-runs" / "samples"


def ffmpeg_executable() -> str:
    if os.environ.get("FFMPEG_BINARY"):
        return os.environ["FFMPEG_BINARY"]
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
        try:
            result = subprocess.run(
                [str(venv_python), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                check=True,
                capture_output=True,
                text=True,
            )
            path = result.stdout.strip()
            if path:
                return path
        except Exception:
            pass
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    raise RuntimeError("ffmpeg not found. Run .\\start-backend.ps1 once to install backend dependencies, or set FFMPEG_BINARY.")


def run_ffmpeg(args: list[str]) -> None:
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(command, check=True)


def ensure_media(data_dir: Path) -> None:
    media_dir = data_dir / "media"
    hls_dir = data_dir / "hls"
    media_dir.mkdir(parents=True, exist_ok=True)
    hls_dir.mkdir(parents=True, exist_ok=True)
    sample_mp4 = media_dir / "sample.mp4"
    master = hls_dir / "master.m3u8"
    if not sample_mp4.exists():
        run_ffmpeg([
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=44100",
            "-t",
            "8",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-shortest",
            str(sample_mp4),
        ])
    if not master.exists():
        run_ffmpeg([
            "-i",
            str(sample_mp4),
            "-c",
            "copy",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            str(hls_dir / "seg_%03d.ts"),
            str(master),
        ])


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; background: #f5f7fb; color: #101828; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 28px; display: grid; gap: 18px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    a, button {{ border: 1px solid #cbdaf0; border-radius: 7px; background: #fff; color: #1557a8; padding: 8px 11px; font-weight: 750; text-decoration: none; cursor: pointer; }}
    section {{ border: 1px solid #dbe7f5; border-radius: 8px; background: #fff; padding: 16px; display: grid; gap: 12px; }}
    video {{ width: 100%; max-height: 460px; background: #0f172a; border-radius: 8px; }}
    code, pre {{ background: #eef4ff; border-radius: 6px; padding: 2px 5px; }}
    pre {{ white-space: pre-wrap; padding: 10px; }}
    .hint {{ color: #667085; font-size: 13px; line-height: 1.5; }}
  </style>
</head>
<body>
  <main>
    <nav>
      <a href="/">样例首页</a>
      <a href="/mp4.html">MP4</a>
      <a href="/hls.html">HLS</a>
      <a href="/blob-iframe.html">Blob iframe</a>
      <a href="/post-api.html">POST play API</a>
      <a href="/generic-player.html">Generic API</a>
      <a href="/chaoxing-mock.html">学习通 mock</a>
    </nav>
    {body}
  </main>
</body>
</html>""".encode("utf-8")


class SampleHandler(BaseHTTPRequestHandler):
    data_dir: Path = DEFAULT_DATA_DIR

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), format % args))

    def send_bytes(self, payload: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".m3u8":
            content_type = "application/vnd.apple.mpegurl"
        if path.suffix == ".ts":
            content_type = "video/mp2t"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With")
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/play", "/api/lesson/resolve", "/ananas/status/play"}:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length).decode("utf-8", "replace")
        if parsed.path == "/ananas/status/play":
            payload = {
                "title": "Chaoxing-style ananas play mock",
                "received_body": body,
                "objectid": "local-object-001",
                "dtoken": "local-dtoken-001",
                "httpmd": "mock-httpmd",
                "sources": [
                    {"type": "application/vnd.apple.mpegurl", "url": "/hls/master.m3u8"},
                    {"type": "video/mp4", "url": "/media/sample.mp4"},
                ],
                "playUrl": "/hls/master.m3u8",
            }
        elif parsed.path == "/api/lesson/resolve":
            payload = {
                "title": "Generic nested player API mock",
                "received_body": body,
                "lesson": {
                    "id": "generic-lesson-001",
                    "media": {
                        "primary": {"streamUrl": "/media/sample.mp4", "mime": "video/mp4"},
                        "manifest": {"manifestUrl": "/hls/master.m3u8", "mime": "application/vnd.apple.mpegurl"},
                        "alternatives": [
                            {"label": "direct mp4 backup", "src": "/media/sample.mp4"},
                            {"label": "hls backup", "sourceUrl": "/hls/master.m3u8"},
                        ],
                    },
                },
                "playback": {
                    "play_url": "/media/sample.mp4",
                    "referer": "/generic-player.html",
                },
            }
        else:
            payload = {
                "title": "POST play API mock",
                "received_body": body,
                "sources": [
                    {"type": "video/mp4", "url": "/media/sample.mp4"},
                    {"type": "application/vnd.apple.mpegurl", "url": "/hls/master.m3u8"},
                ],
                "playUrl": "/media/sample.mp4",
            }
        self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/":
            self.send_bytes(page("LearnNote regression samples", """
<section>
  <h1>LearnNote 本地回归样例</h1>
  <p class="hint">这些页面用于真实浏览器扩展验证，不依赖外部网站。先启动后端和扩展，再打开任一页面点击 Side Panel 的“总结当前视频”或“预检资源”。</p>
  <pre>MP4: 直接 video src
HLS: DOM 暴露 master.m3u8
Blob iframe: 外层页面只有 iframe，内部 fetch mp4 后创建 blob URL
POST play API: 通过 POST /api/play 返回 playUrl/sources
Generic API: 非学习通播放器 POST 接口返回嵌套 streamUrl/manifestUrl/play_url
学习通 mock: 外层课程页 + iframe 播放器 + ananas POST + objectid/dtoken/cookie</pre>
</section>"""))
            return
        if path == "/mp4.html":
            self.send_bytes(page("MP4 direct sample", """
<section>
  <h1>MP4 直链样例</h1>
  <video controls autoplay muted src="/media/sample.mp4"></video>
  <p class="hint">预期：扩展从 DOM 或 webRequest 识别 <code>/media/sample.mp4</code>，后端直接下载。</p>
</section>"""))
            return
        if path == "/hls.html":
            self.send_bytes(page("HLS manifest sample", """
<section>
  <h1>HLS manifest 样例</h1>
  <video controls muted>
    <source src="/hls/master.m3u8" type="application/vnd.apple.mpegurl">
  </video>
  <p class="hint">Chrome 可能不直接播放 HLS，但扩展应能从 DOM 候选里看到 <code>/hls/master.m3u8</code>，后端用 ffmpeg 合并。</p>
</section>"""))
            return
        if path == "/blob-iframe.html":
            self.send_bytes(page("Blob iframe sample", """
<section>
  <h1>Blob iframe 样例</h1>
  <iframe src="/player/blob-source.html" style="width:100%;height:520px;border:1px solid #dbe7f5;border-radius:8px;background:#fff"></iframe>
  <p class="hint">预期：外层只暴露 iframe；扩展把 frame URL 和 blob/MSE 线索传给后端 fallback。</p>
</section>"""))
            return
        if path == "/player/blob-source.html":
            self.send_bytes(page("Blob source player", """
<section>
  <h1>iframe 内 Blob 播放器</h1>
  <video id="video" controls autoplay muted></video>
  <p class="hint" id="status">fetch mp4 后创建 blob URL...</p>
</section>
<script>
(async () => {
  const response = await fetch('/media/sample.mp4');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const video = document.querySelector('#video');
  video.src = url;
  document.querySelector('#status').textContent = 'blob URL 已创建：' + url;
})();
</script>"""))
            return
        if path == "/post-api.html":
            self.send_bytes(page("POST play API sample", """
<section>
  <h1>POST play API 样例</h1>
  <video id="video" controls autoplay muted></video>
  <p class="hint" id="status">等待 POST play API...</p>
  <button id="reload">重新请求播放 API</button>
</section>
<script>
async function load() {
  const response = await fetch('/api/play', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest' },
    body: 'lesson=post-mock&objectid=local-demo&dtoken=sample-token'
  });
  const data = await response.json();
  document.querySelector('#status').textContent = JSON.stringify(data);
  document.querySelector('#video').src = data.playUrl;
}
document.querySelector('#reload').onclick = load;
load();
</script>"""))
            return
        if path == "/generic-player.html":
            self.send_bytes(page("Generic nested player API sample", """
<section>
  <h1>通用播放器 API 样例</h1>
  <video id="video" controls autoplay muted></video>
  <p class="hint">这个页面不是学习通专用：它模拟任意网站的播放器接口，POST 后返回嵌套的 <code>streamUrl</code>、<code>manifestUrl</code>、<code>play_url</code> 和备选 sources。</p>
  <p class="hint" id="status">等待 /api/lesson/resolve...</p>
  <button id="reload">重新请求通用播放 API</button>
</section>
<script>
window.lessonPlayerConfig = {
  lessonId: 'generic-lesson-001',
  resolver: '/api/lesson/resolve',
  media: { backup: '/hls/master.m3u8' }
};
async function load() {
  const response = await fetch('/api/lesson/resolve?lesson=generic-lesson-001', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify({ lessonId: 'generic-lesson-001', want: ['streamUrl', 'manifestUrl', 'play_url'] })
  });
  const data = await response.json();
  document.querySelector('#status').textContent = JSON.stringify(data);
  document.querySelector('#video').src = data.playback.play_url;
}
document.querySelector('#reload').onclick = load;
load();
</script>"""))
            return
        if path == "/chaoxing-mock.html":
            self.send_bytes(page("学习通/超星 mock sample", """
<section>
  <h1>学习通风格课程页 mock</h1>
  <p class="hint">外层页面模拟课程章节，iframe 内播放器请求 <code>/ananas/status/play</code>；预期扩展抓到 ananas/playurl/objectid/dtoken/iframe/cookie/Referer/Origin/XHR 证据。</p>
  <div class="course-title">学习通课程：本地直取诊断</div>
  <div class="chapter-title">章节 1.1 播放接口证据</div>
  <iframe src="/chaoxing/player.html?objectid=local-object-001&dtoken=local-dtoken-001&playurl=%2Fananas%2Fstatus%2Fplay" style="width:100%;height:540px;border:1px solid #dbe7f5;border-radius:8px;background:#fff"></iframe>
</section>
<script>
document.cookie = 'LEARNNOTE_COURSE_SESSION=mock-session; path=/; SameSite=Lax';
</script>"""))
            return
        if path == "/chaoxing/player.html":
            self.send_bytes(page("Chaoxing ananas player mock", """
<section data-objectid="local-object-001" data-dtoken="local-dtoken-001" data-playurl="/ananas/status/play">
  <h1>iframe 内 ananas 播放器 mock</h1>
  <video id="video" controls autoplay muted></video>
  <p class="hint" id="status">等待 ananas/status/play...</p>
  <button id="reload">重新请求 ananas 播放接口</button>
</section>
<script>
window.ananasVideoInfo = {
  objectid: 'local-object-001',
  dtoken: 'local-dtoken-001',
  playUrl: '/ananas/status/play',
  sources: [{ url: '/hls/master.m3u8', type: 'application/vnd.apple.mpegurl' }]
};
async function load() {
  const response = await fetch('/ananas/status/play?objectid=local-object-001&dtoken=local-dtoken-001&playurl=1', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest' },
    body: 'clazzid=local-class&courseid=local-course&objectid=local-object-001&dtoken=local-dtoken-001&playurl=1'
  });
  const data = await response.json();
  document.querySelector('#status').textContent = JSON.stringify(data);
  document.querySelector('#video').src = data.playUrl;
}
document.querySelector('#reload').onclick = load;
load();
</script>"""))
            return
        if path == "/ananas/status/local-object-001":
            payload = {
                "status": "success",
                "objectid": "local-object-001",
                "dtoken": "local-dtoken-001",
                "duration": 8,
                "filename": "chaoxing-objectid-direct.mp4",
                "http": "/media/sample.mp4",
                "download": "/media/sample.mp4",
            }
            self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path.startswith("/media/"):
            self.send_file(self.data_dir / path.lstrip("/"))
            return
        if path.startswith("/hls/"):
            self.send_file(self.data_dir / path.lstrip("/"))
            return
        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve LearnNote local regression sample pages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    ensure_media(data_dir)
    SampleHandler.data_dir = data_dir
    server = ThreadingHTTPServer((args.host, args.port), SampleHandler)
    print(f"LearnNote samples: http://{args.host}:{args.port}")
    print(f"Media fixtures: {data_dir}")
    server.serve_forever()


if __name__ == "__main__":
    main()
