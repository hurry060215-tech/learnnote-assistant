from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit-real-site.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_real_site", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_real_site = load_module()


def context(resources=None, *, cookies=0, cookie_domains=None, page=None):
    return {
        "page": page or {"title": "Course", "active_video": {}, "drm_detected": False},
        "resources": resources or [],
        "captured_count": len(resources or []),
        "cookie_count": cookies,
        "cookie_domain_count": len(cookie_domains or []),
        "cookie_domains": cookie_domains or [],
    }


def audit_from_profile(profile):
    return {
        "url": "https://example.test/course",
        "evidence": {"profile": profile},
    }


class AuditRealSiteSignalProfileTest(unittest.TestCase):
    def test_learning_platform_post_api_without_cookie_needs_auth_context(self):
        profile = audit_real_site.signal_profile(context([
            {
                "url": "https://mooc1.chaoxing.com/ananas/status/play",
                "kind": "video",
                "method": "POST",
                "frame_url": "https://mooc1.chaoxing.com/player.html",
                "request_headers": {
                    "Referer": "https://mooc1.chaoxing.com/course",
                    "Origin": "https://mooc1.chaoxing.com",
                    "X-Requested-With": "XMLHttpRequest",
                },
                "request_body": {
                    "type": "form",
                    "content": "objectid=local-object-001&dtoken=local-dtoken-001",
                },
            }
        ]))

        self.assertEqual(profile["readiness"], "needs_auth_context")
        self.assertEqual(profile["failure_reason"], "auth_required")
        self.assertTrue(profile["learning_platform"]["detected"])
        self.assertTrue(profile["learning_platform"]["ananas"])
        self.assertTrue(profile["learning_platform"]["objectid"])
        self.assertTrue(profile["learning_platform"]["dtoken"])
        self.assertIn("auth_context", profile["missing_steps"])
        self.assertTrue(profile["request_context"]["has_referer"])
        self.assertTrue(profile["request_context"]["has_origin"])
        self.assertTrue(profile["request_context"]["has_x_requested_with"])

    def test_direct_media_with_cookie_and_preflight_is_ready(self):
        profile = audit_real_site.signal_profile(
            context([
                {
                    "url": "https://cdn.example.test/video/master.m3u8",
                    "kind": "hls",
                    "method": "GET",
                    "request_headers": {"Referer": "https://example.test/course"},
                }
            ], cookies=2, cookie_domains=[".example.test"]),
            {"report": {"ready": True, "candidate_count": 1, "probed_count": 1, "downloadable_count": 1}},
        )

        self.assertEqual(profile["readiness"], "ready_to_download")
        self.assertEqual(profile["failure_reason"], "")
        self.assertEqual(profile["missing_steps"], [])
        self.assertTrue(profile["signals"]["direct_media"])
        self.assertTrue(profile["signals"]["manifest"])
        self.assertEqual(profile["auth_context"]["cookie_domain_count"], 1)

    def test_task_probe_can_prove_yt_dlp_page_fallback_ready(self):
        profile = audit_real_site.signal_profile(
            context([], page={"title": "YouTube lesson", "page_url": "https://www.youtube.com/watch?v=demo", "active_video": {}, "drm_detected": False}),
            None,
            {
                "ready": True,
                "task": {
                    "id": "task-ytdlp",
                    "status": "success",
                    "phase": "completed",
                    "mode": "download_only",
                    "source_type": "current_page",
                    "media_path": "D:/Projects/learnnote-assistant/data/tasks/task-ytdlp/media.mp4",
                },
            },
        )

        self.assertEqual(profile["readiness"], "ready_to_download")
        self.assertEqual(profile["failure_reason"], "")
        self.assertNotIn("download_preflight", profile["missing_steps"])
        self.assertTrue(profile["task_probe"]["ready"])
        self.assertEqual(profile["task_probe"]["task_id"], "task-ytdlp")

    def test_task_probe_timeout_is_reported_as_task_failure(self):
        profile = audit_real_site.signal_profile(
            context([], page={"title": "YouTube lesson", "page_url": "https://www.youtube.com/watch?v=demo", "active_video": {}, "drm_detected": False}),
            None,
            {
                "ready": False,
                "task_id": "task-ytdlp-timeout",
                "status": "timeout",
                "error_code": "task_probe_timeout",
                "error_detail": "Timed out waiting for task.",
                "task": {
                    "id": "task-ytdlp-timeout",
                    "status": "running",
                    "phase": "downloading",
                    "mode": "download_only",
                    "source_type": "current_page",
                    "media_path": "",
                },
            },
        )

        self.assertEqual(profile["readiness"], "task_probe_failed")
        self.assertEqual(profile["failure_reason"], "task_probe_timeout")
        self.assertIn("download_task_probe", profile["missing_steps"])
        self.assertIn("longer", profile["next_step"])

    def test_blob_without_manifest_is_structured_failure(self):
        profile = audit_real_site.signal_profile(context(
            page={"title": "Blob player", "active_video": {"src": "blob:https://example.test/abc"}, "drm_detected": False}
        ))

        self.assertEqual(profile["readiness"], "blocked")
        self.assertEqual(profile["failure_reason"], "blob_without_manifest")
        self.assertIn("media_candidate", profile["missing_steps"])
        self.assertIn("local upload", profile["next_step"].lower())

    def test_require_ready_gate_passes_only_downloadable_profile(self):
        ready_profile = audit_real_site.signal_profile(
            context([{"url": "https://cdn.example.test/video.mp4", "kind": "video"}]),
            {"report": {"ready": True, "downloadable_count": 1}},
        )
        blocked_profile = audit_real_site.signal_profile(context(
            page={"title": "Blob player", "active_video": {"src": "blob:https://example.test/abc"}, "drm_detected": False}
        ))

        failures = audit_real_site.audit_gate_failures(
            [audit_from_profile(ready_profile), audit_from_profile(blocked_profile)],
            require_ready=True,
        )

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["gate"], "require_ready")
        self.assertEqual(failures[0]["readiness"], "blocked")
        self.assertEqual(failures[0]["failure_reason"], "blob_without_manifest")

    def test_learning_profile_gate_reports_missing_signals(self):
        profile = audit_real_site.signal_profile(context([
            {
                "url": "https://mooc1.chaoxing.com/ananas/status/play",
                "kind": "video",
                "method": "POST",
                "request_body": {"type": "form", "content": "objectid=local-object-001"},
            }
        ]))

        failures = audit_real_site.audit_gate_failures(
            [audit_from_profile(profile)],
            learning_required_signals=["ananas", "playurl", "objectid", "dtoken", "iframe", "cookie"],
        )

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["gate"], "require_learning_profile")
        self.assertIn("playurl", failures[0]["missing_signals"])
        self.assertIn("dtoken", failures[0]["missing_signals"])
        self.assertIn("iframe", failures[0]["missing_signals"])
        self.assertIn("cookie", failures[0]["missing_signals"])
        self.assertNotIn("ananas", failures[0]["missing_signals"])
        self.assertNotIn("objectid", failures[0]["missing_signals"])

    def test_parse_learning_required_signals_rejects_unknown(self):
        self.assertEqual(
            audit_real_site.parse_learning_required_signals("ananas, cookie"),
            ["ananas", "cookie"],
        )
        with self.assertRaises(ValueError):
            audit_real_site.parse_learning_required_signals("ananas,password")


if __name__ == "__main__":
    unittest.main()
