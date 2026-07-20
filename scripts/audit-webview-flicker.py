from __future__ import annotations

import argparse
import base64
import io
import json
import time
from pathlib import Path
from urllib.request import urlopen

from PIL import Image
from websockets.sync.client import connect


class CdpClient:
    def __init__(self, websocket_url: str):
        self.socket = connect(websocket_url, origin=None, open_timeout=5)
        self.request_id = 0

    def close(self) -> None:
        self.socket.close()

    def call(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        request_id = self.request_id
        self.socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv(timeout=10))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error']}")
            return message.get("result") or {}

    def evaluate(self, expression: str):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        value = result.get("result") or {}
        if value.get("subtype") == "error":
            raise RuntimeError(value.get("description") or "Runtime.evaluate failed")
        return value.get("value")


def screenshot_metrics(client: CdpClient, output: Path, label: str) -> dict:
    encoded = client.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})["data"]
    data = base64.b64decode(encoded)
    target = output / f"{label}.png"
    target.write_bytes(data)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    pixel_source = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    pixels = list(pixel_source)
    black = sum(1 for red, green, blue in pixels if red < 12 and green < 12 and blue < 12)
    dark = sum(1 for red, green, blue in pixels if red < 40 and green < 40 and blue < 40)
    return {
        "label": label,
        "width": image.width,
        "height": image.height,
        "black_ratio": round(black / max(1, len(pixels)), 6),
        "dark_ratio": round(dark / max(1, len(pixels)), 6),
        "path": str(target),
    }


def capture_sequence(client: CdpClient, output: Path, prefix: str) -> list[dict]:
    captures = [screenshot_metrics(client, output, f"{prefix}-immediate")]
    previous = 0
    for milliseconds in (50, 150, 500):
        time.sleep((milliseconds - previous) / 1000)
        captures.append(screenshot_metrics(client, output, f"{prefix}-{milliseconds}ms"))
        previous = milliseconds
    return captures


def click(client: CdpClient, selector: str) -> None:
    clicked = client.evaluate(
        """
        (() => {
          const element = document.querySelector(%s);
          if (!element) return false;
          element.click();
          return true;
        })()
        """ % json.dumps(selector)
    )
    if not clicked:
        raise RuntimeError(f"Missing click target: {selector}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit LearnNote WebView repaint stability through CDP.")
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--playback-seconds", type=float, default=15.0)
    parser.add_argument("--sample-interval", type=float, default=5.0)
    parser.add_argument("--task-id", default="")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with urlopen(f"http://127.0.0.1:{args.port}/json", timeout=5) as response:
        targets = json.load(response)
    page = next((item for item in targets if item.get("type") == "page"), None)
    if not page:
        raise RuntimeError("No WebView page target was found")

    client = CdpClient(page["webSocketDebuggerUrl"])
    try:
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.evaluate(
            """
            (() => {
              const overlay = document.querySelector('#onboardingOverlay');
              if (!overlay || overlay.hidden) return false;
              document.querySelector('#skipOnboardingButton')?.click();
              return true;
            })()
            """
        )
        time.sleep(0.15)
        baseline = screenshot_metrics(client, args.output, "baseline")

        click(client, '[data-app-view="workspace"]')
        time.sleep(0.25)
        click(client, '[data-app-view="notes"]')
        if args.task_id:
            selected = False
            render_deadline = time.monotonic() + 15
            while time.monotonic() < render_deadline and not selected:
                selected = client.evaluate(
                    """
                    (async () => {
                      const taskId = %s;
                      if (typeof selectTask !== 'function' || typeof renderDetail !== 'function') return false;
                      if (!Array.isArray(tasks)) return false;
                      if (!tasks.some(task => task.id === taskId)) {
                        const response = await fetch(apiUrl(`/api/tasks/${encodeURIComponent(taskId)}`));
                        if (!response.ok) return false;
                        const task = taskFromPayload(await response.json());
                        if (!task?.id) return false;
                        tasks = [task, ...tasks];
                      }
                      selectTask(taskId);
                      showAppView('notes');
                      renderTasks();
                      await renderDetail();
                      return selectedTaskId === taskId;
                    })()
                    """ % json.dumps(args.task_id)
                )
                if not selected:
                    time.sleep(0.5)
            if not selected:
                raise RuntimeError(f"Task {args.task_id} could not be selected")
        navigation = capture_sequence(client, args.output, "navigation")

        click(client, '[data-tab="slices"]')
        video_deadline = time.monotonic() + 15
        while time.monotonic() < video_deadline:
            if client.evaluate("Boolean(document.querySelector('#detail video'))"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("The visual timeline did not render a video player")

        video_before = client.evaluate(
            """
            (() => {
              const video = document.querySelector('#detail video');
              if (!video) return null;
              video.dataset.flickerAudit = 'same-node';
              return { currentTime: video.currentTime, paused: video.paused, src: video.currentSrc || video.src };
            })()
            """
        )
        slices = capture_sequence(client, args.output, "slices")
        video_after = client.evaluate(
            """
            (() => {
              const video = document.querySelector('#detail video');
              if (!video) return null;
              return {
                currentTime: video.currentTime,
                paused: video.paused,
                sameNode: video.dataset.flickerAudit === 'same-node',
                src: video.currentSrc || video.src
              };
            })()
            """
        )

        playback_started = client.evaluate(
            """
            (async () => {
              const video = document.querySelector('#detail video');
              if (!video) return false;
              video.dataset.flickerAudit = 'same-node';
              video.muted = true;
              await video.play();
              return true;
            })()
            """
        )
        playback_initial = client.evaluate(
            """
            (() => {
              const video = document.querySelector('#detail video');
              return video ? { currentTime: video.currentTime, src: video.currentSrc || video.src } : null;
            })()
            """
        )
        playback_frames = [screenshot_metrics(client, args.output, "playback-start")]
        playback_samples = []
        playback_started_at = time.monotonic()
        next_sample = min(max(0.5, args.sample_interval), max(0.5, args.playback_seconds))
        while True:
            elapsed = time.monotonic() - playback_started_at
            if elapsed >= args.playback_seconds:
                break
            sleep_for = min(next_sample - elapsed, args.playback_seconds - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)
            elapsed = time.monotonic() - playback_started_at
            sample = client.evaluate(
                """
                (() => {
                  const video = document.querySelector('#detail video');
                  if (!video) return null;
                  return {
                    currentTime: video.currentTime,
                    paused: video.paused,
                    ended: video.ended,
                    sameNode: video.dataset.flickerAudit === 'same-node',
                    readyState: video.readyState,
                    networkState: video.networkState,
                    src: video.currentSrc || video.src
                  };
                })()
                """
            )
            playback_samples.append({"elapsed": round(elapsed, 3), "video": sample})
            playback_frames.append(screenshot_metrics(client, args.output, f"playback-{round(elapsed)}s"))
            next_sample += max(0.5, args.sample_interval)
        playback_after_poll = playback_samples[-1]["video"] if playback_samples else None

        all_frames = [baseline, *navigation, *slices, *playback_frames]
        active_playback_frames = playback_frames[1:] or playback_frames
        playback_continuous = bool(
            playback_started
            and playback_initial
            and playback_after_poll
            and playback_after_poll.get("sameNode")
            and playback_after_poll.get("currentTime", 0) - playback_initial.get("currentTime", 0) >= max(2.5, args.playback_seconds * 0.7)
            and playback_after_poll.get("readyState", 0) >= 2
            and (not playback_after_poll.get("paused") or playback_after_poll.get("ended"))
            and all(
                sample.get("video")
                and sample["video"].get("sameNode")
                and sample["video"].get("readyState", 0) >= 2
                and sample["video"].get("src") == playback_after_poll.get("src")
                for sample in playback_samples
            )
        )
        report = {
            "target_url": page.get("url"),
            "frames": all_frames,
            "max_black_ratio": max(item["black_ratio"] for item in all_frames),
            "max_dark_ratio": max(item["dark_ratio"] for item in all_frames),
            "max_active_playback_black_ratio": max(item["black_ratio"] for item in active_playback_frames),
            "video_before": video_before,
            "video_after": video_after,
            "playback_after_poll": playback_after_poll,
            "playback_initial": playback_initial,
            "playback_seconds": args.playback_seconds,
            "playback_samples": playback_samples,
            "playback_continuous": playback_continuous,
            "blank_frame_detected": any(item["black_ratio"] >= 0.85 for item in active_playback_frames),
            "passed": all(item["black_ratio"] < 0.85 for item in active_playback_frames) and playback_continuous,
        }
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
