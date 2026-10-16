from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TimelinePlaybackFixtureTests(unittest.TestCase):
    def test_visible_disclosure_and_all_playback_tracks_are_required(self):
        subprocess.run(["node", str(ROOT / "scripts/tests/timeline-playback-fixture.cjs")], check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
