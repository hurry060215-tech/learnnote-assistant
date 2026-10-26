"""Fixture-only observer accounting, race, bound and actual owned-child checks."""
from contextlib import ExitStack, nullcontext
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import owned_process_tree_sample as module


class Missing(Exception):
    pass


class Denied(Exception):
    pass


class FakeProcess:
    def __init__(self, api, pid):
        self.api, self.pid = api, pid
        if pid not in api.rows:
            raise Missing(pid)

    def create_time(self):
        return self.api.rows[self.pid]["created"]

    def ppid(self):
        return self.api.rows[self.pid]["parent"]

    def children(self, recursive=False):
        assert recursive is False
        if self.api.deny_discovery:
            raise Denied()
        return [self.api.Process(pid) for pid, row in list(self.api.rows.items())
                if row["parent"] == self.pid]

    def oneshot(self):
        return nullcontext()

    def memory_info(self):
        row = self.api.rows[self.pid]
        if row.get("denied"):
            raise Denied()
        if row.get("disappear"):
            del self.api.rows[self.pid]
            raise Missing(self.pid)
        if row.get("reuse"):
            row["created"] += 1
        return SimpleNamespace(rss=row["rss"])

    def cpu_times(self):
        row = self.api.rows[self.pid]
        return SimpleNamespace(user=row["cpu"], system=1, children_user=1000, children_system=2000)


class FakeAPI:
    NoSuchProcess, AccessDenied = Missing, Denied
    __version__ = "test"

    def __init__(self):
        self.rows = {}
        self.deny_discovery = False

    def add(self, pid, parent=0, created=10, rss=100, cpu=0, **extra):
        self.rows[pid] = dict(parent=parent, created=created, rss=rss, cpu=cpu, **extra)

    def Process(self, pid):
        return FakeProcess(self, pid)


class AccountingTests(unittest.TestCase):
    def fixture(self):
        api = FakeAPI()
        api.add(1)
        sampler = module.OwnedProcessTreeSampler()
        sampler._api, sampler._root = api, (1, 10)
        sampler._started = time.monotonic()
        sampler._admit(sampler._root)
        return api, sampler

    def test_simultaneous_sum_own_cpu_only_and_reparented_identity(self):
        api, sampler = self.fixture()
        api.add(2, parent=1, created=20, rss=200, cpu=40)
        sampler._sample()
        api.rows[1]["cpu"] += 2
        api.rows[2].update(cpu=43, parent=999)
        report = sampler.stop()
        self.assertEqual(report["status"], "sampled")
        self.assertEqual(report["rss_observed_sum_peak_bytes"], 300)
        self.assertEqual(report["cpu_observed_seconds"], 5)
        self.assertEqual(len(report["processes"]), 2)
        self.assertEqual(report["budget_status"], "not_established")
        self.assertEqual(report, sampler.stop())
        report["processes"].clear()
        self.assertEqual(len(sampler.stop()["processes"]), 2)

    def test_exit_and_disappearance_are_counted_expected_gaps_not_zero_readings(self):
        api, sampler = self.fixture()
        api.add(2, parent=1, created=20, rss=200)
        sampler._sample()
        api.rows[2]["disappear"] = True
        report = sampler.stop()
        self.assertEqual(report["status"], "sampled")
        self.assertEqual(report["sampling_gaps"]["exits_observed"], 1)
        self.assertEqual(report["sampling_gaps"]["disappeared_during_read"], 1)
        self.assertEqual(report["recent_samples"][-1]["missing_readings"], 1)
        self.assertEqual(report["recent_samples"][-1]["processes_read"], 1)
        self.assertEqual(report["rss_observed_sum_peak_bytes"], 300)

    def test_pid_reuse_never_merges_foreign_rss_or_cpu(self):
        api, sampler = self.fixture()
        api.add(2, parent=1, created=20, rss=200)
        sampler._sample()
        api.rows[2].update(parent=999, created=30, rss=999999, cpu=999999)
        report = sampler.stop()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["rss_observed_sum_peak_bytes"], 300)
        self.assertEqual(report["cpu_observed_seconds"], 0)
        self.assertEqual(report["errors"]["identity_mismatch"], 1)

    def test_identity_change_during_read_rejects_entire_reading(self):
        api, sampler = self.fixture()
        api.add(2, parent=1, created=20, rss=999999, reuse=True)
        report = sampler.stop()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["rss_observed_sum_peak_bytes"], 100)
        self.assertIsNone(report["processes"][1]["last_cpu_s"])

    def test_denial_and_unsupported_do_not_become_success_or_zero(self):
        for failure in (Denied(), NotImplementedError(), ValueError()):
            with self.subTest(failure=type(failure).__name__):
                api, sampler = self.fixture()
                with patch.object(FakeProcess, "memory_info", side_effect=failure):
                    report = sampler.stop()
                self.assertEqual(report["status"], "unavailable")
                self.assertIsNone(report["rss_observed_sum_peak_bytes"])
                self.assertIsNone(report["cpu_observed_seconds"])
                self.assertEqual(sum(report["errors"].values()), 1)

    def test_partial_denial_is_incomplete_and_discovery_denial_is_visible(self):
        api, sampler = self.fixture()
        api.add(2, parent=1, created=20, denied=True)
        report = sampler.stop()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["errors"]["access_denied"], 1)
        api, sampler = self.fixture()
        api.deny_discovery = True
        self.assertEqual(sampler.stop()["status"], "incomplete")

    def test_fixed_identity_and_ring_limits_and_aggregate_survive_eviction(self):
        api, sampler = self.fixture()
        with patch.object(module, "MAX_IDENTITIES", 2), patch.object(module, "MAX_SAMPLES", 2):
            sampler._samples = module.deque(maxlen=2)
            api.add(2, parent=1, created=20, rss=200)
            api.add(3, parent=1, created=30, rss=300)
            sampler._sample()
            api.rows[2]["rss"] = 10
            sampler._sample()
            sampler._sample()
            report = sampler.stop()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(len(report["processes"]), 2)
        self.assertEqual(len(report["recent_samples"]), 2)
        self.assertEqual(report["sample_details_dropped"], 2)
        self.assertEqual(report["errors"]["identity_capacity"], 4)
        self.assertEqual(report["rss_observed_sum_peak_bytes"], 300)

    def test_missing_dependency_and_root_exit_are_unavailable(self):
        sampler = module.OwnedProcessTreeSampler()
        with patch.dict(sys.modules, {"psutil": None}):
            report = sampler.start().stop()
        self.assertEqual(report["status"], "unavailable")
        self.assertIsNone(report["cpu_observed_seconds"])
        self.assertEqual(report["errors"]["dependency_unavailable"], 1)
        api, sampler = self.fixture()
        sampler._sample()
        del api.rows[1]
        self.assertEqual(sampler.stop()["status"], "unavailable")

    def test_counter_reset_is_incomplete_and_sampling_skew_is_retained(self):
        with patch.object(module.time, "monotonic", return_value=128.0) as clock:
            api, sampler = self.fixture()
            api.rows[1]["cpu"] = 2
            sampler._sample()
            api.rows[1]["cpu"] = 1
            # Exact binary timestamps, independent of OS clock tick resolution.
            clock.side_effect = [128.25, 128.3125, 128.3125]
            report = sampler.stop()
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["errors"]["invalid_counter"], 1)
        self.assertEqual(report["maximum_gap_seconds"], .25)
        self.assertGreater(report["maximum_gap_seconds"], .2)
        self.assertEqual(report["sampling_gaps"]["late_samples"], 1)
        self.assertEqual(report["maximum_collection_span_seconds"], .0625)
        json.dumps(report, allow_nan=False)

    def test_same_tick_decimal_gap_preserves_observed_representation(self):
        with patch.object(module.time, "monotonic", return_value=256.0):
            _, sampler = self.fixture()
            sampler._sample()
            sampler._last_start -= .2
            report = sampler.stop()
        expected_gap = 256.0 - (256.0 - .2)
        self.assertLess(expected_gap, .2)  # Original Windows failure representation.
        self.assertEqual(report["maximum_gap_seconds"], expected_gap)
        self.assertEqual(report["sampling_gaps"]["late_samples"], 1)
        self.assertEqual(report["maximum_collection_span_seconds"], 0)
        self.assertEqual(report["status"], "sampled")

    def test_stuck_observer_has_static_unavailable_report_and_one_bounded_join(self):
        _, sampler = self.fixture()
        sampler._thread = Mock()
        sampler._thread.is_alive.return_value = True
        sampler._processes = Mock()  # Accessing mutable state would fail.
        report = sampler.stop()
        self.assertEqual(report["status"], "unavailable")
        self.assertTrue(report["observer_still_running"])
        self.assertIsNone(report["sample_count"])
        self.assertIsNone(report["rss_observed_sum_peak_bytes"])
        sampler._thread.is_alive.return_value = False  # Later recovery cannot relabel the first result.
        self.assertEqual(report, sampler.stop())
        sampler._thread.join.assert_called_once_with(timeout=2)


class ActualChildTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("psutil"), "optional benchmark psutil dependency not installed")
    def test_owned_child_memory_cpu_and_reap(self):
        sampler = module.OwnedProcessTreeSampler().start()
        child = subprocess.Popen([sys.executable, "-c", """
import os, sys, time
data = bytearray(b'x') * (32 * 1024 * 1024)
print('ready', os.getpid(), flush=True)
deadline = time.monotonic() + .4
while time.monotonic() < deadline:
    sum(range(1000))
sys.stdin.readline()
"""], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            ready, worker = child.stdout.readline().strip().split()
            self.assertEqual(ready, "ready")
            worker_pid = int(worker)
            time.sleep(.55)
            child.communicate("done\n", timeout=5)
            time.sleep(module.INTERVAL_SECONDS * 3)
            report = sampler.stop()
            self.assertEqual(report["status"], "sampled", report["errors"])
            # Windows venv python.exe can be a waiting redirector. Its child
            # owns the allocation and CPU work, and must be sampled separately.
            launch_rows = [row for row in report["processes"] if row["pid"] == child.pid]
            self.assertEqual(len(launch_rows), 1)
            self.assertTrue(launch_rows[0]["exited_observed"])
            rows = [row for row in report["processes"] if row["pid"] == worker_pid]
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["exited_observed"])
            self.assertGreater(rows[0]["last_cpu_s"] - rows[0]["baseline_cpu_s"], .05)
            peak = report["rss_peak_sample"]
            self.assertGreaterEqual(len(peak["processes"]), 2)
            self.assertEqual(peak["rss_observed_sum_bytes"], sum(r["rss_bytes"] for r in peak["processes"]))
            self.assertGreater(peak["rss_observed_sum_bytes"], max(r["rss_bytes"] for r in peak["processes"]))
            self.assertGreater(next(r["rss_bytes"] for r in peak["processes"] if r["pid"] == worker_pid), 32 * 1024 * 1024)
            self.assertEqual(child.returncode, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
            sampler.stop()


class HarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("fixture_long_video", SCRIPTS / "long-video-reliability.py")
        cls.harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.harness)

    def run_harness(self, *, enabled=True, observer_status="sampled", media_error=None, stop_error=None):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            media = root / "input.mp4"
            media.write_bytes(b"synthetic")
            grid = root / "grid.jpg"
            grid.write_bytes(b"synthetic")
            argv = ["fixture", "--output-dir", str(root / "output"), "--media", str(media),
                    "--duration-seconds", "5", "--frame-interval", "1"]
            if enabled:
                argv.append("--sample-process-tree")
            observer = Mock()
            observer.start.return_value = observer
            observer.stop.return_value = {"status": observer_status, "budget_status": "not_established"}
            observer.stop.side_effect = stop_error
            stack.enter_context(patch.object(module, "OwnedProcessTreeSampler", return_value=observer))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(sys, "stdout", io.StringIO()))
            stack.enter_context(patch.object(sys, "stderr", io.StringIO()))
            monitor = Mock()
            monitor.start.return_value = monitor
            monitor.stop.return_value.as_dict.return_value = {"rss_peak_bytes": 100, "disk_free_min_bytes": 1000}
            stack.enter_context(patch.object(self.harness, "ResourceMonitor", return_value=monitor))
            integrity = SimpleNamespace(status="ready", has_video=True, has_audio=True, duration=5,
                file_size=9, sha256="fixture", probe_backend="fixture", video_codec="fixture", audio_codec="fixture")
            stack.enter_context(patch.object(self.harness, "probe_media_integrity", return_value=integrity))
            stack.enter_context(patch.object(self.harness, "extract_frames_adaptive",
                return_value=([media, media], [SimpleNamespace(timestamp=0), SimpleNamespace(timestamp=4)]),
                side_effect=media_error))
            stack.enter_context(patch.object(self.harness, "build_frame_grids", return_value=[SimpleNamespace(path=grid)]))
            code = self.harness.main()
            report = json.loads((root / "output" / "report.json").read_text())
            return code, report, observer

    def test_opt_in_success_is_measurement_not_tree_budget_acceptance(self):
        code, report, observer = self.run_harness()
        self.assertEqual(code, 0)
        self.assertTrue(report["media_pipeline_completed"])
        self.assertEqual(report["process_tree_measurement"]["budget_status"], "not_established")
        observer.start.assert_called_once()
        self.assertGreaterEqual(observer.stop.call_count, 1)

    def test_disabled_keeps_existing_media_path(self):
        code, report, observer = self.run_harness(enabled=False)
        self.assertEqual(code, 0)
        self.assertEqual(report["process_tree_measurement"]["status"], "disabled")
        observer.start.assert_not_called()

    def test_unavailable_and_incomplete_enabled_observer_are_nonzero(self):
        for status in ("unavailable", "incomplete"):
            with self.subTest(status=status):
                code, report, _ = self.run_harness(observer_status=status)
                self.assertEqual(code, 1)
                self.assertTrue(report["media_pipeline_completed"])
                self.assertEqual(report["process_tree_measurement"]["status"], status)

    def test_primary_media_error_survives_observer_stop_failure(self):
        code, report, _ = self.run_harness(media_error=RuntimeError("primary media failure"),
                                         stop_error=RuntimeError("secondary observer failure"))
        self.assertEqual(code, 1)
        self.assertEqual(report["error"], "primary media failure")
        self.assertFalse(report["media_pipeline_completed"])
        self.assertEqual(report["process_tree_measurement"]["reason"], "observer_stop_failed")


if __name__ == "__main__":
    unittest.main()
