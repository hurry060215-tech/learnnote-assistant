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
        navigation = capture_sequence(client, args.output, "navigation")

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
        click(client, '[data-tab="slices"]')
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
        playback_frames = [screenshot_metrics(client, args.output, "playback-start")]
        time.sleep(1)
        playback_frames.append(screenshot_metrics(client, args.output, "playback-1s"))
        time.sleep(2.5)
        playback_frames.append(screenshot_metrics(client, args.output, "playback-3.5s"))
        playback_after_poll = client.evaluate(
            """
            (() => {
              const video = document.querySelector('#detail video');
              if (!video) return null;
              return {
                currentTime: video.currentTime,
                paused: video.paused,
                sameNode: video.dataset.flickerAudit === 'same-node',
                readyState: video.readyState,
                src: video.currentSrc || video.src
              };
            })()
            """
        )

        all_frames = [baseline, *navigation, *slices, *playback_frames]
        playback_continuous = bool(
            playback_started
            and playback_after_poll
            and playback_after_poll.get("sameNode")
            and playback_after_poll.get("currentTime", 0) >= 2.5
            and not playback_after_poll.get("paused")
        )
        report = {
            "target_url": page.get("url"),
            "frames": all_frames,
            "max_black_ratio": max(item["black_ratio"] for item in all_frames),
            "max_dark_ratio": max(item["dark_ratio"] for item in all_frames),
            "video_before": video_before,
            "video_after": video_after,
            "playback_after_poll": playback_after_poll,
            "playback_continuous": playback_continuous,
            "passed": all(item["black_ratio"] < 0.01 for item in all_frames) and playback_continuous,
        }
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
