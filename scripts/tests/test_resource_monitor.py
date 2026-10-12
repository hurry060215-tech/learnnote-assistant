from __future__ import annotations

import ctypes
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app import resource_monitor
from backend.app.resource_monitor import ResourceMonitor


class ResourceMonitorTests(unittest.TestCase):
    def test_collects_local_process_and_disk_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            monitor = ResourceMonitor(Path(temporary) / "data", interval_seconds=0.01).start()
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
            summary = ResourceMonitor(Path(temporary) / "data").start().stop()
        payload = summary.as_dict()
        self.assertIn("rss_peak_bytes", payload)
        self.assertIn("disk_free_min_bytes", payload)

    def test_posix_rss_units(self) -> None:
        usage = SimpleNamespace(RUSAGE_SELF=0, getrusage=Mock(return_value=SimpleNamespace(ru_maxrss=123)))
        for platform, expected in (("linux", 123 * 1024), ("darwin", 123)):
            with self.subTest(platform=platform), patch.object(resource_monitor, "os", SimpleNamespace(name="posix")), patch.object(resource_monitor, "sys", SimpleNamespace(platform=platform)), patch.object(resource_monitor, "_resource", usage):
                self.assertEqual(resource_monitor._process_rss_bytes(), expected)

    def test_unavailable_posix_rss_is_none(self) -> None:
        with patch.object(resource_monitor, "os", SimpleNamespace(name="posix")), patch.object(resource_monitor, "_resource", None):
            self.assertIsNone(resource_monitor._process_rss_bytes())
        for error in (AttributeError, OSError, ValueError):
            usage = SimpleNamespace(RUSAGE_SELF=0, getrusage=Mock(side_effect=error))
            with self.subTest(error=error), patch.object(resource_monitor, "os", SimpleNamespace(name="posix")), patch.object(resource_monitor, "_resource", usage):
                self.assertIsNone(resource_monitor._process_rss_bytes())

    def test_windows_preserves_working_set_and_pointer_sized_handle(self) -> None:
        handle = 0x123456789

        def fill_counters(process, counters, size):
            self.assertEqual(process, handle)
            self.assertEqual(size, ctypes.sizeof(counters._obj))
            counters._obj.WorkingSetSize = 456
            counters._obj.PeakWorkingSetSize = 999
            return 1

        api = Mock(side_effect=fill_counters)
        get_process = Mock(return_value=handle)
        windll = SimpleNamespace(psapi=SimpleNamespace(GetProcessMemoryInfo=api), kernel32=SimpleNamespace(GetCurrentProcess=get_process))
        with patch.object(resource_monitor, "os", SimpleNamespace(name="nt")), patch.object(resource_monitor.ctypes, "windll", windll, create=True):
            self.assertEqual(resource_monitor._process_rss_bytes(), 456)
        self.assertIs(get_process.restype, ctypes.c_void_p)
        self.assertIs(api.argtypes[0], ctypes.c_void_p)

    def test_windows_api_lookup_and_query_failures_are_none(self) -> None:
        for windll in (SimpleNamespace(), Mock(psapi=Mock(GetProcessMemoryInfo=Mock(return_value=0))), Mock(psapi=Mock(GetProcessMemoryInfo=Mock(side_effect=OSError)))):
            with self.subTest(windll=windll), patch.object(resource_monitor, "os", SimpleNamespace(name="nt")), patch.object(resource_monitor.ctypes, "windll", windll, create=True):
                self.assertIsNone(resource_monitor._process_rss_bytes())

    def test_reliability_workflow_includes_cancellation_gate(self) -> None:
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "reliability.yml").read_text(encoding="utf-8")
        self.assertIn("cancel-reliability.py", workflow)
        self.assertIn("build/reliability/cancel/report.json", workflow)
        self.assertIn("scheduler-reliability.py", workflow)
        self.assertIn("build/reliability/scheduler/report.json", workflow)
        self.assertIn("full-local-task-reliability.py", workflow)
        self.assertIn("build/reliability/full-local-task/report.json", workflow)


if __name__ == "__main__":
    unittest.main()
