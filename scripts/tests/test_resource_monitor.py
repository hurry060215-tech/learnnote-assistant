from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from backend.app.resource_monitor import ResourceMonitor


class ResourceMonitorTests(unittest.TestCase):
    def test_collects_local_process_and_disk_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            monitor = ResourceMonitor(Path(temporary), interval_seconds=0.01).start()
            time.sleep(0.03)
            summary = monitor.stop()

        self.assertGreaterEqual(summary.sample_count, 2)
        self.assertTrue(summary.monitoring_supported)
        self.assertIsNotNone(summary.disk_free_before_bytes)
        self.assertIsNotNone(summary.disk_free_after_bytes)
        self.assertGreater(summary.disk_free_min_bytes or 0, 0)
        self.assertGreaterEqual(summary.process_cpu_percent_peak or 0, 0)
        self.assertIsNotNone(summary.rss_peak_bytes)
        self.assertGreater(summary.rss_peak_bytes or 0, 0)

    def test_summary_is_json_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = ResourceMonitor(Path(temporary)).start().stop()
        payload = summary.as_dict()
        self.assertIn("rss_peak_bytes", payload)
        self.assertIn("disk_free_min_bytes", payload)

    def test_reliability_workflow_includes_cancellation_gate(self) -> None:
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "reliability.yml").read_text(encoding="utf-8")
        self.assertIn("cancel-reliability.py", workflow)
        self.assertIn("build/reliability/cancel/report.json", workflow)


if __name__ == "__main__":
    unittest.main()
