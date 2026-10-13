"""Official count declarations and real batching with an offline provider stub."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from app import model_capabilities as caps
from app.models import FrameGrid, TaskOptions, TranscriptResult, TranscriptSegment
from app.model_route import plan_route
from app.summarizer import _compatible_completion, summarize_with_llm, SummarizationCancelled
from app.summary_diagnostics import build_summary_diagnostics

BASE = "https://api.groq.com/openai/v1"
MODEL = "qwen/qwen3.8-27b"


class DeclaredImageLimitTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch("app.token_usage.record_usage"))
        self.stack.enter_context(patch("app.model_capabilities.DATA_DIR", self.root))
        self.options = TaskOptions(llm_base_url=BASE, llm_model=MODEL, llm_api_key="synthetic-only",
            use_saved_connection=False, vision_batch_size=4, vision_concurrency=1)
        self.transcript = TranscriptResult(source="fixture", full_text="Synthetic lesson.",
            segments=[TranscriptSegment(start=0, end=80, text="Synthetic lesson.")])
        self.grids = []
        for index in range(8):
            image = self.root / f"grid-{index}.jpg"
            image.write_bytes(f"synthetic image bytes {index}".encode())
            self.grids.append(FrameGrid(path=str(image), url=f"/fixtures/grid-{index}.jpg",
                start=index * 10, end=(index + 1) * 10, frame_count=1))
        self.calls, self.sections, self.events = [], [], []

    def response(self, text="Synthetic completed batch."):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])

    def run_summary(self, count=4, completion=None, callback=None, cancel=None, options=None):
        def create(**kwargs):
            self.calls.append(kwargs)
            return completion(kwargs) if completion else self.response()
        provider = types.SimpleNamespace(OpenAI=lambda **_kwargs: types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))))
        with patch.dict(sys.modules, {"openai": provider}), \
             patch("app.summarizer._validated_generated_note", return_value="# Synthetic lesson\n\nSynthetic lesson."):
            return summarize_with_llm("Synthetic lesson", self.transcript, self.grids[:count], options or self.options,
                events=self.events, vision_cache_dir=self.root / "cache", cancel_check=cancel,
                section_callback=callback or self.sections.append)

    def vision_calls(self):
        return [call for call in self.calls if isinstance(call["messages"][0]["content"], list)]

    def image_counts(self):
        return [sum(item.get("type") == "image_url" for item in call["messages"][0]["content"])
                for call in self.vision_calls()]

    def test_official_declaration_has_exact_scope_and_dated_source(self):
        item = caps.declared_image_limit(BASE + "/", MODEL)
        self.assertEqual(item["value"], 3)
        self.assertEqual(item["status"], "declared")
        self.assertEqual(item["checked_on"], "2026-10-13")
        self.assertEqual(item["source_url"], "https://console.groq.com/docs/vision")
        self.assertEqual(item["api"], "chat.completions")
        self.assertIn("未实测", item["detail"])
        self.assertIn("上下文", item["detail"])
        with patch.object(caps, "image_probe_verified", return_value=True):
            self.assertEqual(caps.route_capabilities("groq", BASE, MODEL, configured=True,
                vision_allowed=True, remote_asr=False, local_asr_available=False)["image_limit"]["status"], "declared")

    def test_other_endpoints_models_and_apis_do_not_inherit(self):
        cases = [(url, MODEL, "chat.completions") for url in (
            "http://api.groq.com/openai/v1", BASE + "?key=fixture", BASE + "#fragment",
            "https://api.groq.com:8443/openai/v1", "https://user@api.groq.com/openai/v1",
            "https://proxy.invalid/openai/v1", "https://api.groq.com.evil.invalid/openai/v1",
            "https://api.groq.com/v1", BASE + "/chat/completions", BASE + "//")]
        cases += [(BASE, name, "chat.completions") for name in ("qwen3.8-27b", "Qwen/qwen3.8-27b", MODEL + "-latest", "meta-llama/llama-4-scout-17b-16e-instruct")]
        cases += [(BASE, MODEL, "responses")]
        for url, model, api in cases:
            with self.subTest(url=url, model=model, api=api):
                self.assertIsNone(caps.declared_image_limit(url, model, api)["value"])

    def test_requested_sizes_preserve_every_original_window(self):
        for requested, counts in ((1, [1] * 8), (3, [3, 3, 2]), (4, [3, 3, 2]), (8, [3, 3, 2])):
            with self.subTest(requested=requested):
                self.calls.clear(); self.sections.clear()
                with patch("app.summarizer._read_vision_cache", return_value=""):
                    self.run_summary(8, options=self.options.model_copy(update={"vision_batch_size": requested}))
                self.assertEqual(self.image_counts(), counts)
                self.assertEqual([window["index"] for section in self.sections for window in section["source_windows"]], list(range(8)))
                self.assertEqual(len({s["generation_revision"] for s in self.sections}), 1)

    def test_four_split_three_one_and_cache_replay_does_not_resend_images(self):
        self.run_summary()
        self.assertEqual(self.image_counts(), [3, 1])
        original = list(self.sections)
        self.calls.clear(); self.sections.clear()
        self.run_summary()
        self.assertEqual(self.image_counts(), [])
        self.assertEqual(self.sections, original)
        self.assertEqual(len(self.calls), 1)  # Final text merge only.
        self.assertEqual(sum(e["stage"] == "vision_cache" for e in self.events), 2)

    def test_changed_batch_partition_does_not_reuse_old_generation(self):
        self.run_summary(options=self.options.model_copy(update={"vision_batch_size": 2}))
        before = self.sections[0]["generation_revision"]
        self.calls.clear(); self.sections.clear()
        self.run_summary()
        self.assertEqual(self.image_counts(), [3, 1])
        self.assertNotEqual(self.sections[0]["generation_revision"], before)

    def test_partial_failure_preserves_success_and_resumes_only_missing_batch(self):
        def fail_second(kwargs):
            content = kwargs["messages"][0]["content"]
            if isinstance(content, list) and "批次：2" in content[0]["text"]:
                raise RuntimeError("synthetic batch failure")
            return self.response()
        self.run_summary(completion=fail_second)
        self.assertEqual([w["index"] for s in self.sections for w in s["source_windows"]], [0, 1, 2])
        merge = self.calls[-1]["messages"][0]["content"]
        self.assertIn("1 vision batch(es) failed", merge)
        self.assertIn("W004", merge)
        self.calls.clear(); self.sections.clear()
        self.run_summary()
        self.assertEqual(self.image_counts(), [1])
        self.assertEqual([w["index"] for s in self.sections for w in s["source_windows"]], [0, 1, 2, 3])

    def test_callback_cancellation_stops_next_batch_and_resume_uses_cache(self):
        cancelled = False
        def callback(section):
            nonlocal cancelled
            self.sections.append(section)
            cancelled = True
        with self.assertRaises(SummarizationCancelled):
            self.run_summary(callback=callback, cancel=lambda: cancelled)
        self.assertEqual(self.image_counts(), [3])
        self.assertEqual(len(self.calls), 1)
        self.calls.clear(); self.sections.clear()
        self.run_summary()
        self.assertEqual(self.image_counts(), [1])
        self.assertEqual(len(self.sections), 2)

    def test_missing_file_keeps_original_window_identity(self):
        Path(self.grids[1].path).unlink()
        self.run_summary()
        self.assertEqual(self.image_counts(), [2, 1])
        self.assertEqual([w["index"] for s in self.sections for w in s["source_windows"]], [0, 1, 2, 3])
        first = str(self.vision_calls()[0]["messages"])
        self.assertIn("W002", first)
        self.assertIn("W003", first)

    def test_unknown_endpoint_retains_requested_batch_size(self):
        self.run_summary(options=self.options.model_copy(update={"llm_base_url": "https://proxy.invalid/v1"}))
        self.assertEqual(self.image_counts(), [4])

    def test_concurrent_capped_batches_keep_source_windows(self):
        self.run_summary(options=self.options.model_copy(update={"vision_concurrency": 2}))
        self.assertEqual(sorted(self.image_counts()), [1, 3])
        self.assertEqual(sorted(w["index"] for s in self.sections for w in s["source_windows"]), [0, 1, 2, 3])

    def test_final_payload_limit_prevents_provider_and_usage_dispatch(self):
        client = Mock()
        messages = [{"role": role, "content": [{"type": "image_url", "image_url": {"url": "data:fixture"}}] * 2}
                    for role in ("user", "assistant")]
        with patch("app.summarizer.tracked_completion") as tracked:
            with self.assertRaisesRegex(ValueError, "declared_image_limit_exceeded"):
                _compatible_completion(client, events=[], stage="vision_batch", base_url=BASE, model=MODEL, messages=messages)
        tracked.assert_not_called()

    def test_retry_rechecks_final_messages(self):
        messages = [{"role": "user", "content": [{"type": "image_url"}] * 3}]
        failure = RuntimeError("synthetic unsupported sampling option")
        failure.status_code = 400
        failure.body = {"code": "unsupported_parameter", "param": "temperature"}
        def mutate_then_reject(*args, **kwargs):
            messages[0]["content"].append({"type": "image_url"})
            raise failure
        with patch("app.summarizer.tracked_completion", side_effect=mutate_then_reject) as tracked:
            with self.assertRaisesRegex(ValueError, "declared_image_limit_exceeded"):
                _compatible_completion(Mock(), events=[], stage="vision_batch", base_url=BASE,
                    model=MODEL, messages=messages, temperature=0.2)
        self.assertEqual(tracked.call_count, 1)

    def test_diagnostics_preflight_and_execution_agree_without_cost_estimates(self):
        result = plan_route(self.options)
        self.assertEqual(result["vision_batch_plan"]["effective_size"], 3)
        self.assertEqual(result["vision_batch_plan"]["requested_size"], 4)
        self.assertIn("每批最多 3 张", result["capability_catalog"]["image_limit"]["detail"])
        self.assertIsNone(result["estimates"]["cost"])
        with patch("app.summary_diagnostics.TASK_DIR", self.root):
            diagnostics = build_summary_diagnostics("fixture", "Synthetic", "", self.options,
                self.grids[:4], [], "vision-llm", "")
        self.assertEqual(diagnostics["vision_batch_size"], 3)
        self.assertEqual(diagnostics["vision_requested_batch_size"], 4)
        self.assertEqual([p["window_ids"] for p in diagnostics["vision_call_plan"]], [["W001", "W002", "W003"], ["W004"]])

    def test_settings_preflight_uses_saved_batch_preference_without_provider(self):
        from app.routers.system import api_model_route
        (self.root / "preferences.json").write_text(json.dumps({"task_options": {"vision_batch_size": 1}}))
        selected = {"configured": False, "model": {"base_url": BASE, "model": MODEL}}
        with patch("app.routers.system.DATA_DIR", self.root), \
             patch("app.model_connections.selected_connection_status", return_value=selected), \
             patch("app.local_models.model_status", return_value={"status": "not_downloaded"}), \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=Mock(side_effect=AssertionError("no provider")))}):
            result = api_model_route()
        self.assertEqual(result["vision_batch_plan"]["effective_size"], 1)
        self.assertEqual(result["capability_catalog"]["image_limit"]["value"], 3)

    def test_malformed_saved_preferences_fall_back_without_rewriting_bytes(self):
        from app.routers.system import api_model_route
        selected = {"configured": False, "model": {"base_url": BASE, "model": MODEL}}
        for raw in ("null", "[]", '"invalid"', "{truncated", '{"task_options":{"vision_batch_size":0}}'):
            with self.subTest(raw=raw), patch("app.routers.system.DATA_DIR", self.root), \
                 patch("app.model_connections.selected_connection_status", return_value=selected), \
                 patch("app.local_models.model_status", return_value={"status": "not_downloaded"}):
                path = self.root / "preferences.json"
                path.write_text(raw)
                result = api_model_route()
                self.assertEqual(result["vision_batch_plan"]["requested_size"], 4)
                self.assertEqual(result["vision_batch_plan"]["effective_size"], 3)
                self.assertEqual(path.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
