from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.bilibili_subtitles import BilibiliSubtitleError, fetch_bilibili_subtitle
from app.bilibili_subtitles import BilibiliSubtitleResult
from app.downloader import MediaDownloader
from app.models import ActiveVideoInfo, BrowserCookie, BrowserSubtitleCue, CurrentPageTaskRequest, TaskOptions, TranscriptResult, TranscriptSegment
from app.processor import process_current_page_task, process_saved_transcript_task
from app.storage import create_task, get_task, task_dir, update_task, write_json
from app.summary_outcome import summary_failure_message


class SubtitlesFirstTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch("app.storage.TASK_DIR", root / "tasks"), patch("app.observability.TASK_DIR", root / "tasks"), patch("app.storage.ensure_dirs", lambda: None)]
        for p in self.patches:
            p.start()
        self.cues = [BrowserSubtitleCue(start=i * 10, end=i * 10 + 9, text=f"第{i}个内容说明") for i in range(12)]

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def request(self, **kwargs):
        return CurrentPageTaskRequest(page_url="https://example.com/video", title="课程", options=TaskOptions(visual_understanding=False, note_style="study", summary_depth="detailed"), **kwargs)

    def test_browser_captions_skip_all_media_and_keep_note_preferences(self):
        request = self.request(browser_subtitles=self.cues, active_video=ActiveVideoInfo(duration=120))
        task = create_task("current_page", request.title, request.page_url)
        with patch("app.processor.MediaDownloader") as cls, patch("app.processor.summarize_with_diagnostics", return_value=("# 模型改写的课程标题\n\n## 要点\n\n这里是内容的综合总结。", "text-llm", "", [])) as summarize:
            cls.return_value.attempts = []
            cls.return_value.resolved_title = ""
            process_current_page_task(task.id, request)
            cls.return_value.download.assert_not_called()
            cls.return_value.download_subtitle.assert_not_called()
            opts = summarize.call_args.args[3]
            self.assertEqual(opts.note_style, "study")
            self.assertEqual(opts.summary_depth, "detailed")
        record = get_task(task.id)
        self.assertEqual(record.status, "success")
        self.assertEqual(record.summary_source, "text-llm")
        self.assertIn("这里是内容的综合总结", Path(record.note_path).read_text(encoding="utf-8"))
        self.assertEqual(record.mode, "subtitle_only")
        self.assertFalse(record.media_path)
        metrics = json.loads((task_dir(task.id) / "pipeline_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["stages"]["download"]["status"], "skipped")

    def test_platform_subtitles_probed_before_media_and_skip_download(self):
        request = self.request()
        task = create_task("current_page", request.title, request.page_url)
        subtitle = task_dir(task.id) / "test.srt"
        subtitle.write_text("\n\n".join(f"{i+1}\n00:{i//6:02d}:{i%6*10:02d},000 --> 00:{i//6:02d}:{i%6*10+9:02d},000\n第{i}个要点" for i in range(12)), encoding="utf-8")
        with patch("app.processor.MediaDownloader") as cls, patch("app.processor.summarize_with_diagnostics", return_value=("# 课程\n\n## 要点\n\n内容总结。", "text-llm", "", [])):
            cls.return_value.attempts = []
            cls.return_value.resolved_title = "课程"
            cls.return_value.resolved_duration = 120
            cls.return_value.download_subtitle.return_value = subtitle
            process_current_page_task(task.id, request)
            cls.return_value.download.assert_not_called()
        self.assertEqual(get_task(task.id).status, "success")
        transcript = json.loads(Path(get_task(task.id).transcript_path).read_text(encoding="utf-8"))
        self.assertEqual(transcript["source"], "page-subtitle")

    def test_missing_subtitle_continues_media_only_after_probe(self):
        request = self.request()
        task = create_task("current_page", request.title, request.page_url)
        calls = []
        media = task_dir(task.id) / "video.mp4"
        media.write_bytes(b"test media")
        with patch("app.processor.MediaDownloader") as cls, patch("app.processor._process_video_file"):
            downloader = cls.return_value
            downloader.attempts = []
            downloader.resolved_title = "课程"
            downloader.resolved_duration = 0
            downloader.download_subtitle.side_effect = lambda *a: calls.append("subtitle")
            downloader.download.side_effect = lambda *a: (calls.append("media") or media, None)
            process_current_page_task(task.id, request)
        self.assertEqual(calls, ["subtitle", "media"])

    def test_provider_failure_is_not_complete_and_retry_reuses_asr(self):
        task = create_task("local", "课程")
        transcript = TranscriptResult(source="faster-whisper", full_text="真实字幕", segments=[TranscriptSegment(start=0, end=10, text="真实字幕")])
        path = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
        update_task(task.id, transcript_path=str(path))
        events = [{"stage":"text_summary", "code":"api_error", "message":"insufficient balance org-private000 ak-private000"}]
        with patch("app.processor.summarize_with_diagnostics", return_value=("# 课程\n字幕摘录", "local-template", "insufficient balance", events)), patch("app.processor.MediaDownloader") as download, patch("app.processor.transcribe_audio") as asr:
            process_saved_transcript_task(task.id, TaskOptions())
            download.assert_not_called()
            asr.assert_not_called()
        record = get_task(task.id)
        self.assertEqual(record.error_code, "summary_unavailable")
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.checkpoint, "transcript_ready")
        self.assertIn("额度不足", record.message)
        self.assertNotIn("private000", Path(record.summary_diagnostics_path).read_text(encoding="utf-8"))
        with patch("app.processor.summarize_with_diagnostics", return_value=("# 课程\n\n## 核心结论\n\n重新总结后的内容。", "text-llm", "", [])):
            process_saved_transcript_task(task.id, TaskOptions())
        record = get_task(task.id)
        self.assertEqual(record.status, "success")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["source"], "faster-whisper")
        self.assertIn("已保存的音频转写", Path(record.note_path).read_text(encoding="utf-8"))

    def test_bili_selects_requested_part_and_manual_chinese(self):
        output = Path(self.temp.name) / "track.srt"
        replies = [{"code":0,"data":{"title":"多集课程","pages":[{"cid":11,"duration":20},{"cid":22,"duration":50}]}},
            {"code":0,"data":{"subtitle":{"subtitles":[{"lan":"en","subtitle_url":"https://aisubtitle.hdslb.com/en"},{"lan":"ai-zh","ai_type":1,"subtitle_url":"https://aisubtitle.hdslb.com/ai"},{"lan":"zh-CN","ai_type":0,"subtitle_url":"https://aisubtitle.hdslb.com/manual"}]}}},
            {"body":[{"from":0,"to":49,"content":"这是真实字幕"}]}]
        with patch("app.bilibili_subtitles._get_json", side_effect=replies) as get:
            result = fetch_bilibili_subtitle("https://www.bilibili.com/video/BV123ABC?p=2", output, lambda u:{})
        self.assertEqual(get.call_args_list[1].kwargs["params"]["cid"], 22)
        self.assertEqual(get.call_args_list[2].args[0], "https://aisubtitle.hdslb.com/manual")
        self.assertEqual(result.duration, 50)
        self.assertIn("这是真实字幕", output.read_text(encoding="utf-8"))

    def test_bili_rejects_wrong_part_and_reports_login(self):
        output = Path(self.temp.name) / "track.srt"
        view = {"code":0,"data":{"pages":[{"cid":1}]}}
        with patch("app.bilibili_subtitles._get_json", return_value=view):
            with self.assertRaises(BilibiliSubtitleError) as caught:
                fetch_bilibili_subtitle("https://www.bilibili.com/video/BV123ABC?p=4", output, lambda u:{})
        self.assertEqual(caught.exception.code, "source_changed")
        with patch("app.bilibili_subtitles._get_json", side_effect=[view,{"code":0,"data":{"need_login_subtitle":True}}]):
            with self.assertRaises(BilibiliSubtitleError) as caught:
                fetch_bilibili_subtitle("https://www.bilibili.com/video/BV123ABC", output, lambda u:{})
        self.assertEqual(caught.exception.code, "auth_required")

    def test_bili_rejects_untrusted_caption_host(self):
        replies = [{"code":0,"data":{"cid":1}},{"code":0,"data":{"subtitle":{"subtitles":[{"lan":"zh-CN","subtitle_url":"https://other.example/track"}]}}}]
        with patch("app.bilibili_subtitles._get_json", side_effect=replies) as get:
            with self.assertRaises(BilibiliSubtitleError):
                fetch_bilibili_subtitle("https://www.bilibili.com/video/BV123ABC", Path(self.temp.name)/"track.srt", lambda u:{})
        self.assertEqual(get.call_count, 2)

    def test_downloader_scopes_browser_cookies_to_bilibili_api(self):
        output = Path(self.temp.name) / "captions.srt"
        output.write_text("1\n00:00:00,000 --> 00:00:10,000\n字幕", encoding="utf-8")
        checked = {}
        def direct(url, path, headers_for):
            checked["api"] = headers_for("https://api.bilibili.com/x/player/wbi/v2")
            checked["cdn"] = headers_for("https://aisubtitle.hdslb.com/track")
            return BilibiliSubtitleResult(path=output, title="课程", duration=10)
        downloader = MediaDownloader(Path(self.temp.name))
        with patch("app.bilibili_subtitles.fetch_bilibili_subtitle", side_effect=direct), patch.object(downloader, "_download_subtitle_with_ytdlp") as ytdlp:
            path = downloader.download_subtitle([], [BrowserCookie(name="SESSDATA", value="private-session", domain=".bilibili.com")], "https://www.bilibili.com/video/BV123ABC", "课程")
            ytdlp.assert_not_called()
        self.assertEqual(path, output)
        self.assertEqual(checked["api"]["Cookie"], "SESSDATA=private-session")
        self.assertNotIn("Cookie", checked["cdn"])
        self.assertFalse((Path(self.temp.name) / "subtitle_cookies.txt").exists())

    def test_failed_retry_keeps_previous_note_file(self):
        task = create_task("local", "课程")
        transcript = TranscriptResult(source="faster-whisper", full_text="字幕", segments=[TranscriptSegment(start=0, end=1, text="字幕")])
        path = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
        note = task_dir(task.id) / "note.md"
        note.write_text("# 已有笔记\n\n用户已有内容。", encoding="utf-8")
        update_task(task.id, transcript_path=str(path), note_path=str(note))
        with patch("app.processor.summarize_with_diagnostics", return_value=("# 无效回退", "local-template", "missing_api_key", [])):
            process_saved_transcript_task(task.id, TaskOptions())
        self.assertEqual(get_task(task.id).note_path, str(note))
        self.assertIn("用户已有内容", note.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
