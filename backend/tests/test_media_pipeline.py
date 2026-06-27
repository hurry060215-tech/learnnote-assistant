from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.config import DATA_DIR
from app.media import build_frame_grids, extract_audio, extract_frames, probe_duration
from app.runtime import ffmpeg_bin


TEST_RUN_DIR = DATA_DIR / "test-runs"


@unittest.skipUnless(ffmpeg_bin(), "ffmpeg is required for media pipeline tests")
class MediaPipelineTests(unittest.TestCase):
    def test_synthetic_video_generates_audio_frames_and_grid(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = root / "synthetic.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=3:size=320x180:rate=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=3",
                    "-shortest",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )

            self.assertGreater(probe_duration(video), 2.5)

            audio = extract_audio(video, root / "audio.wav")
            self.assertTrue(audio.exists())
            self.assertGreater(audio.stat().st_size, 1024)

            frames = extract_frames(video, root / "frames", interval=1)
            self.assertGreaterEqual(len(frames), 2)

            grids = build_frame_grids("unit", frames, root / "grids", columns=3, rows=3, interval=1)
            self.assertEqual(len(grids), 1)
            self.assertTrue(Path(grids[0].path).exists())
            self.assertEqual(grids[0].frame_timestamps[:2], [0.0, 1.0])
            with Image.open(grids[0].path) as image:
                label_area = image.crop((4, 154, 92, 178))
                dark_pixels = sum(1 for pixel in label_area.getdata() if sum(pixel[:3]) < 180)
                self.assertGreater(dark_pixels, 20)


if __name__ == "__main__":
    unittest.main()
