from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.config import DATA_DIR
from app.media import _average_hash, _hamming_distance, _should_keep_sampled_frame, build_frame_grids, extract_audio, extract_embedded_subtitle, extract_frames, probe_duration
from app.runtime import ffmpeg_bin


TEST_RUN_DIR = DATA_DIR / "test-runs"


@unittest.skipUnless(ffmpeg_bin(), "ffmpeg is required for media pipeline tests")
class MediaPipelineTests(unittest.TestCase):
    def test_near_duplicate_frames_keep_periodic_timeline_anchors(self) -> None:
        self.assertFalse(
            _should_keep_sampled_frame(
                current_hash="same",
                current_average_hash=10,
                timestamp=4,
                last_hash="same",
                last_average_hash=10,
                last_kept_timestamp=0,
                coverage_gap=5,
            )
        )
        self.assertTrue(
            _should_keep_sampled_frame(
                current_hash="same",
                current_average_hash=10,
                timestamp=5,
                last_hash="same",
                last_average_hash=10,
                last_kept_timestamp=0,
                coverage_gap=5,
            )
        )
        self.assertTrue(
            _should_keep_sampled_frame(
                current_hash="changed",
                current_average_hash=27,
                timestamp=1,
                last_hash="same",
                last_average_hash=10,
                last_kept_timestamp=0,
                coverage_gap=5,
            )
        )

    def test_average_hash_detects_near_duplicate_frames(self) -> None:
        TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            base = root / "base.jpg"
            near = root / "near.jpg"
            different = root / "different.jpg"

            base_image = Image.new("RGB", (320, 180), (46, 92, 184))
            base_image.save(base)

            near_image = base_image.copy()
            near_image.putpixel((12, 12), (48, 94, 186))
            near_image.save(near)

            different_image = Image.new("RGB", (320, 180), (238, 242, 247))
            different_image.paste(Image.new("RGB", (160, 180), (8, 13, 23)), (0, 0))
            different_image.save(different)

            base_hash = _average_hash(base)
            near_hash = _average_hash(near)
            different_hash = _average_hash(different)

            self.assertLessEqual(_hamming_distance(base_hash, near_hash), 1)
            self.assertGreater(_hamming_distance(base_hash, different_hash), 3)

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
                window_label_area = image.crop((4, 4, 118, 34))
                blue_pixels = sum(
                    1
                    for red, green, blue in window_label_area.getdata()
                    if blue > red + 20 and blue > green + 10
                )
                self.assertGreater(blue_pixels, 20)
                label_area = image.crop((4, 154, 92, 178))
                dark_pixels = sum(1 for pixel in label_area.getdata() if sum(pixel[:3]) < 180)
                self.assertGreater(dark_pixels, 20)

    def test_static_video_keeps_periodic_visual_coverage(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = root / "static.mp4"
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
                    "color=c=navy:s=320x180:d=7",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )

            frames = extract_frames(video, root / "frames", interval=1)

            timestamps = [int(frame.stem.rsplit("_", 1)[-1]) for frame in frames]
            self.assertIn(0, timestamps)
            self.assertIn(5, timestamps)
            self.assertLess(len(frames), 7)

    def test_embedded_text_subtitle_can_be_extracted(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            subtitle = root / "lesson.srt"
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,500\nEmbedded subtitle line\n\n",
                encoding="utf-8",
            )
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
                    "testsrc=duration=2:size=320x180:rate=10",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
            muxed = root / "with-subtitle.mkv"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(video),
                    "-i",
                    str(subtitle),
                    "-map",
                    "0:v",
                    "-map",
                    "1:s",
                    "-c:v",
                    "copy",
                    "-c:s",
                    "srt",
                    str(muxed),
                ],
                check=True,
            )

            extracted = extract_embedded_subtitle(muxed, root / "embedded.srt")

            self.assertIsNotNone(extracted)
            assert extracted is not None
            self.assertTrue(extracted.exists())
            self.assertIn("Embedded subtitle line", extracted.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
