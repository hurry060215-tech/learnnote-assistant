from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit-product-readiness.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_product_readiness", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit_product_readiness = load_module()


class ProductReadinessAuditTest(unittest.TestCase):
    def test_matrix_contains_objective_areas(self):
        rows = audit_product_readiness.build_matrix()
        keys = {row.key for row in rows}

        for expected in {
            "side_panel_product_flow",
            "non_recording_direct_extraction",
            "local_video_pipeline",
            "visual_slice_notes",
            "learning_platform_diagnostics",
            "local_regression_samples",
            "startup_onboarding",
            "generic_adapter_direction",
            "product_acceptance_gate",
            "real_site_chaoxing",
        }:
            self.assertIn(expected, keys)

    def test_static_product_gates_do_not_fail(self):
        rows = audit_product_readiness.build_matrix()
        static_rows = [row for row in rows if not row.key.startswith("real_site_")]
        failures = [row for row in static_rows if row.status == "fail"]

        self.assertEqual([], [(row.key, row.detail) for row in failures])

    def test_acceptance_gate_can_be_skipped_for_self_audit(self):
        rows = audit_product_readiness.build_matrix(include_acceptance_gate=False)
        keys = {row.key for row in rows}

        self.assertNotIn("product_acceptance_gate", keys)
        self.assertIn("startup_onboarding", keys)
        self.assertIn("real_site_ytdlp", keys)

    def test_learning_audit_requires_full_signal_set(self):
        complete = {
            "path": Path("audit.json"),
            "entry": {
                "url": "https://mooc1.chaoxing.com/course",
                "evidence": {
                    "profile": {
                        "learning_platform": {
                            "detected": True,
                            "ananas": True,
                            "playurl": True,
                            "objectid": True,
                            "dtoken": True,
                            "iframe": True,
                            "cookie": True,
                        }
                    }
                }
            },
        }
        missing = {
            "path": Path("audit.json"),
            "entry": {
                "url": "https://mooc1.chaoxing.com/course",
                "evidence": {
                    "profile": {
                        "learning_platform": {
                            "detected": True,
                            "ananas": True,
                            "playurl": True,
                            "objectid": True,
                            "dtoken": False,
                            "iframe": True,
                            "cookie": True,
                        }
                    }
                }
            },
        }

        self.assertIsNone(audit_product_readiness.learning_audit([missing]))
        self.assertIs(audit_product_readiness.learning_audit([complete]), complete)

    def test_learning_audit_does_not_count_local_mock_as_real_site(self):
        local = {
            "path": Path("audit.json"),
            "entry": {
                "url": "http://127.0.0.1:8777/chaoxing-mock.html",
                "evidence": {
                    "profile": {
                        "learning_platform": {
                            "detected": True,
                            "ananas": True,
                            "playurl": True,
                            "objectid": True,
                            "dtoken": True,
                            "iframe": True,
                            "cookie": True,
                        }
                    }
                }
            },
        }

        self.assertIsNone(audit_product_readiness.learning_audit([local]))
        self.assertIs(audit_product_readiness.learning_audit([local], include_local=True), local)

    def test_learning_audit_accepts_completed_direct_task_evidence(self):
        completed = {
            "path": Path("D:/audit.json"),
            "entry": {
                "url": "https://mooc1.chaoxing.com/course",
                "evidence": {
                    "profile": {
                        "readiness": "ready_to_download",
                        "learning_platform": {
                            "detected": True,
                            "direct_task": {
                                "ready": True,
                                "download_success": True,
                                "processing_success": True,
                                "no_tab_recording": True,
                                "no_drm_bypass": True,
                            },
                        },
                    }
                },
            },
        }

        self.assertIs(audit_product_readiness.learning_audit([completed]), completed)

    def test_ready_site_audit_filters_by_readiness_and_token(self):
        ready = {
            "path": Path("audit.json"),
            "entry": {
                "url": "https://example.test/mp4-page",
                "evidence": {"profile": {"readiness": "ready_to_download"}},
            },
        }
        blocked = {
            "path": Path("audit.json"),
            "entry": {
                "url": "https://youtube.com/watch?v=demo",
                "evidence": {"profile": {"readiness": "blocked"}},
            },
        }

        self.assertIs(audit_product_readiness.ready_site_audit([blocked, ready], ["mp4"]), ready)
        self.assertIsNone(audit_product_readiness.ready_site_audit([blocked, ready], ["youtube"]))

    def test_ready_site_audit_does_not_count_local_by_default(self):
        local_ready = {
            "path": Path("audit.json"),
            "entry": {
                "url": "http://127.0.0.1:8777/mp4.html",
                "evidence": {"profile": {"readiness": "ready_to_download"}},
            },
        }

        self.assertIsNone(audit_product_readiness.ready_site_audit([local_ready], ["mp4"]))
        self.assertIs(audit_product_readiness.ready_site_audit([local_ready], ["mp4"], include_local=True), local_ready)

    def test_ytdlp_supported_audit_requires_task_and_extractor_evidence(self):
        complete = {
            "path": Path("audit.json"),
            "entry": {
                "url": "https://samplelib.com/sample-mp4.html",
                "evidence": {
                    "profile": {
                        "readiness": "ready_to_download",
                        "task_probe": {"ready": True},
                        "ytdlp_probe": {"ready": True, "extractor": "generic"},
                    }
                },
            },
        }
        missing_probe = {
            "path": Path("audit.json"),
            "entry": {
                "url": "https://youtube.com/watch?v=demo",
                "evidence": {
                    "profile": {
                        "readiness": "ready_to_download",
                        "task_probe": {"ready": True},
                        "ytdlp_probe": {"ready": False, "extractor": ""},
                    }
                },
            },
        }

        self.assertIsNone(audit_product_readiness.ytdlp_supported_audit([missing_probe]))
        self.assertIs(audit_product_readiness.ytdlp_supported_audit([complete]), complete)

    def test_acceptance_report_allows_manual_logged_in_learning_gate_only(self):
        report = """
# LearnNote product acceptance gate
- PASS doctor (2s)
- PASS real browser extension smoke: local MP4/HLS/API/blob/learning mock (12s)
- PASS yt-dlp supported real-site task probe (54s)
- PASS learning-platform local mock gate (9s)
- MANUAL logged-in learning-platform real gate: provide -LearningUrl after logging in and opening the lesson page
- PASS product readiness matrix (0s)
"""
        missing = report.replace("- PASS real browser extension smoke: local MP4/HLS/API/blob/learning mock (12s)\n", "")
        failed = report + "\n- FAIL product readiness matrix (1s): broken\n"

        self.assertTrue(audit_product_readiness.acceptance_report_ready(report))
        self.assertFalse(audit_product_readiness.acceptance_report_ready(missing))
        self.assertFalse(audit_product_readiness.acceptance_report_ready(failed))

    def test_latest_acceptance_report_prefers_complete_report_over_newer_skip(self):
        complete = """
# LearnNote product acceptance gate
- PASS doctor (2s)
- PASS real browser extension smoke: local MP4/HLS/API/blob/learning mock (12s)
- PASS yt-dlp supported real-site task probe (54s)
- PASS learning-platform local mock gate (9s)
- MANUAL logged-in learning-platform real gate: provide -LearningUrl after logging in and opening the lesson page
- PASS product readiness matrix (0s)
"""
        skipped = """
# LearnNote product acceptance gate
- PASS doctor (2s)
- SKIP real browser extension smoke
- SKIP yt-dlp supported real-site task probe
- PASS product readiness matrix (0s)
"""
        original = audit_product_readiness.PRODUCT_ACCEPTANCE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "20260709-010000" / "summary.md"
            newer = root / "20260709-020000" / "summary.md"
            older.parent.mkdir(parents=True)
            newer.parent.mkdir(parents=True)
            older.write_text(complete, encoding="utf-8")
            newer.write_text(skipped, encoding="utf-8")
            audit_product_readiness.PRODUCT_ACCEPTANCE_DIR = root
            try:
                selected = audit_product_readiness.latest_product_acceptance_report()
            finally:
                audit_product_readiness.PRODUCT_ACCEPTANCE_DIR = original

        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], older)


if __name__ == "__main__":
    unittest.main()
