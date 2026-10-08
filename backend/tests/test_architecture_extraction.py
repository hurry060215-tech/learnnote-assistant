"""Behavior snapshots and independent contracts for the #143 module split."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from app import media_discovery, media_manifests, qa_evidence, qa_history
from app.models import TaskOptions, TaskQuestionRequest, TaskRecord

FIXTURE = Path(__file__).parent / "fixtures" / "architecture_extraction_v1.json"


def discovery_snapshot(module):
    base = "https://course.example.test/lessons/index.html"
    cases = {
        "empty": "",
        "html": '<video src="../video.mp4"></video><track src="captions.vtt" kind="captions"><video src="../video.mp4">',
        "encoded": r'var playUrl="https%3A%2F%2Fcdn.example.test%2Flecture.mp4%3Fid%3Dfixture";',
        "json": json.dumps({"sources": [{"url": "https://cdn.example.test/master.m3u8", "type": "application/vnd.apple.mpegurl"}, {"url": "../clip.webm"}]}),
        "split_json": json.dumps({"baseUrl": "https://cdn.example.test/media/", "videos": [{"path": "part.mp4"}]}),
        "malformed_json": '{"videoUrl": "../clip.mp4",',
        "escaped": r'window.player={"src":"https:\/\/cdn.example.test\/lesson.mp4?x=1\u0026y=2"}',
        "noise": "This is a plain page with no media evidence.",
    }
    return {name: [item.model_dump(mode="json") for item in module.extract_media_resources_from_text(text, base)] for name, text in cases.items()}


def manifest_snapshot(module):
    hls = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"\n#EXTINF:2\npart.ts\n'
    dash = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><BaseURL>media/</BaseURL><Period><SegmentTemplate media="seg-$Number$.m4s" initialization="init.mp4"/></Period></MPD>'
    base = "https://cdn.example.test/course/master.m3u8"
    return {
        "hls": module._rewrite_hls_manifest_for_local_file(hls, base),
        "dash": module._rewrite_dash_manifest_for_local_file(dash, base),
        "malformed_dash": module._rewrite_dash_manifest_for_local_file('<MPD><BaseURL>media/</BaseURL><SegmentURL media="p.m4s">', base),
        "aes": list(module._hls_encryption_flags(hls)),
        "drm": list(module._hls_encryption_flags('#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://fixture"')),
        "html_is_not_manifest": list(module._manifest_kind_from_body('<html>Login required</html>', 'application/dash+xml')),
    }


def qa_snapshot(module):
    citations = [
        {"source": "note", "label": "开头", "text": "梯度下降每次更新参数。"},
        {"source": "transcript", "label": "字幕 00:10", "text": "这里把学习率设为 0.01", "start": 10, "end": 40, "granularity": "window"},
        {"source": "transcript", "label": "字幕 01:00", "text": "下一步检查梯度", "start": 60, "end": 90, "granularity": "window"},
        {"source": "visual_window", "label": "W001", "text": "画面包含参数设置", "start": 0},
        {"source": "note", "text": ""},
    ]
    segments = [{"start": 0, "end": 12, "text": "梯度下降"}, {"start": 14, "end": 20, "text": "更新学习率"}, {"start": 130, "end": 140, "text": "检查收敛"}]
    note = '# 梯度\n\n更新参数。\n\n- Page context: captured from the current browser page\n  Player toolbar\n\n## 检查\n\n核对收敛。'
    return {
        "terms": sorted(module._question_terms("只根据字幕解释学习率，不要使用笔记")),
        "strict": module._strict_transcript_evidence_requested("只根据字幕解释学习率，不要使用笔记"),
        "note": module._note_evidence_chunks(note, source_id="fixture-task"),
        "windows": module._transcript_window_chunks(segments, task_id="fixture-task"),
        "ranked": module._rank_citations_for_question(citations, module._question_terms("学习率字幕原话")),
        "summary": module._summary_citations(citations),
        "local_answer": list(module._local_task_answer("学习率", citations[:2])),
        "prompt": module._qa_evidence_prompt(citations[:3]),
        "history_messages": module._qa_history_messages([{"question": "  参数  怎么更新？", "answer": "Historical answer must not become fact evidence"}]),
    }


class ExtractionSnapshotTests(unittest.TestCase):
    def test_page_discovery_matches_pre_split_snapshot(self):
        self.assertEqual(discovery_snapshot(media_discovery), json.loads(FIXTURE.read_text())["discovery"])

    def test_manifest_rewriting_matches_pre_split_snapshot(self):
        self.assertEqual(manifest_snapshot(media_manifests), json.loads(FIXTURE.read_text())["manifests"])

    def test_main_qa_compatibility_matches_pre_split_snapshot(self):
        from app import main
        self.assertEqual(qa_snapshot(main), json.loads(FIXTURE.read_text())["qa"])

    def test_qa_and_export_api_contracts_match_pre_split_snapshot(self):
        from app import main
        snapshot = json.loads(FIXTURE.read_text())["api_paths"]
        self.assertEqual({path: main.app.openapi()["paths"][path] for path in snapshot}, snapshot)

    def test_pure_modules_import_without_api_downloader_or_processor(self):
        script = (
            "import sys; from app import media_discovery, media_manifests, qa_evidence, qa_history; "
            "assert not {'app.main', 'app.downloader', 'app.processor'} & sys.modules.keys()"
        )
        subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)

    def test_downloader_keeps_compatibility_exports(self):
        from app import downloader
        self.assertIs(downloader.extract_media_resources_from_text, media_discovery.extract_media_resources_from_text)
        self.assertIs(downloader._hls_encryption_flags, media_manifests._hls_encryption_flags)
        self.assertEqual(discovery_snapshot(downloader), discovery_snapshot(media_discovery))


class IndependentQABoundaryTests(unittest.TestCase):
    def test_trust_policy_is_explicit_and_main_patchable(self):
        rejected = {"text": "player controls", "source": "transcript"}
        accepted = {"text": "course evidence", "source": "transcript"}
        self.assertFalse(qa_evidence.citation_is_trusted(rejected, is_player_ui=lambda text: True))
        self.assertEqual(qa_evidence.sanitize_citations([rejected, accepted], is_trusted=lambda item: item is accepted), [accepted])
        from app import main
        with patch.object(main, "browser_subtitle_text_is_player_ui", return_value=True):
            self.assertEqual(main._sanitize_citations([accepted]), [])
            self.assertEqual(main._transcript_window_chunks([{"text": "course evidence", "start": 0, "end": 1}]), [])
        with patch.object(main, "_sanitize_citations", return_value=[]):
            self.assertEqual(main._rank_citations_for_question([accepted], {"course"}), [])
            self.assertEqual(main._summary_citations([accepted]), [])

    def test_ranking_and_timeline_use_only_supplied_evidence(self):
        citations = [{"source": "transcript", "text": "alpha", "start": 0}, {"source": "note", "text": "beta"}]
        selected = qa_evidence.rank_citations_for_question(citations, {"alpha"}, sanitize_citations=lambda values: values)
        self.assertEqual(selected, [citations[0]])
        self.assertIs(selected[0], citations[0])
        self.assertEqual(qa_evidence.local_task_answer("missing", [])[1], [])

    def test_history_round_trip_keeps_v1_schema_and_storage_boundary(self):
        task = TaskRecord(id="fixture-task", title="课堂", source_type="local", created_at="2026-10-08", updated_at="2026-10-08", options=TaskOptions())
        request = TaskQuestionRequest(question="  核对\n证据  ")
        history = []
        writes = []
        result = {"answer": "原文回答", "source": "local-extractive", "citations": [{"source": "transcript", "text": "出处", "start": 1, "end": 2}]}
        item, items = qa_history.append_task_qa_history(
            task, request, result, read_history=lambda task_id: history,
            write_json=lambda *args: writes.append(args), filename="qa_history.json",
            sanitize_citations=lambda values: values, new_id=lambda: "fixed-id", now=lambda: "2026-10-08T00:00:00+00:00",
        )
        self.assertEqual(item["id"], "fixed-id")
        self.assertEqual(item["question"], "核对 证据")
        self.assertEqual(item["citations"][0]["source_id"], task.id)
        self.assertEqual(writes, [(task.id, "qa_history.json", {"schema_version": 1, "items": items})])
        restored = qa_history.read_task_qa_history(task.id, read_json=lambda *args: writes[0][2], filename="qa_history.json", sanitize_citations=lambda values: values)
        self.assertEqual(restored, items)
        self.assertIn("## Q1. 核对 证据", qa_history.render_qa_history_markdown(task, read_history=lambda task_id: restored))

    def test_legacy_history_shape_and_rejected_evidence(self):
        old = [{"answer": "untrusted", "citations": [{"text": "toolbar"}]}, {"answer": "legacy", "citations": []}, "invalid"]
        for payload in (old, {"items": old}):
            restored = qa_history.read_task_qa_history("fixture", read_json=lambda *args: payload, filename="qa.json", sanitize_citations=lambda values: [])
            self.assertEqual(restored, [{"answer": "legacy", "citations": []}])

    def test_main_history_uses_current_storage_patch_points(self):
        from app import main
        with patch.object(main, "read_json", return_value={"items": [{"answer": "kept"}]}) as reader:
            self.assertEqual(main.read_task_qa_history("fixture"), [{"answer": "kept", "citations": []}])
            reader.assert_called_once_with("fixture", main.QA_HISTORY_FILE, {"items": []})
        with patch.object(main, "read_task_qa_history", return_value=[]) as reader:
            task = TaskRecord(id="fixture", title="snapshot", source_type="local", created_at="2026-10-08", updated_at="2026-10-08")
            self.assertIn("暂无问答记录", main.render_qa_history_markdown(task))
            reader.assert_called_once_with(task.id)


if __name__ == "__main__":
    unittest.main()
