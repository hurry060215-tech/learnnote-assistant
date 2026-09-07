import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from yt_dlp import YoutubeDL
from yt_dlp.extractor.common import InfoExtractor
from app.downloader import MediaDownloader,DownloadError,choose_ytdlp_subtitle_language

class BiliSubtitleProbeTests(unittest.TestCase):
 def test_probe_enables_real_extractor_subtitle_gate(self):
  with tempfile.TemporaryDirectory() as tmp:
   downloader=MediaDownloader(Path(tmp));calls=[]
   def extract(ydl,url,download=False):
    calls.append(download)
    extractor=InfoExtractor(ydl)
    with patch.object(extractor,'_get_subtitles',return_value={'ai-zh':[{'ext':'srt','data':'subtitle'}]}):
     subtitles=extractor.extract_subtitles()
    if download:
     self.assertEqual(ydl.params['subtitleslangs'],['ai-zh'])
     (downloader.download_dir/'example.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\n真实字幕\n',encoding='utf-8')
    return {'subtitles':subtitles}
   with patch.object(YoutubeDL,'extract_info',autospec=True,side_effect=extract):
    result=downloader._download_subtitle_with_ytdlp('https://www.bilibili.com/video/BV1ioh56JEFf',[],'example',[])
   self.assertIsNotNone(result);self.assertEqual(calls,[False,True])
 def test_login_warning_is_not_reported_as_no_subtitles(self):
  with tempfile.TemporaryDirectory() as tmp:
   def extract(ydl,*args,**kwargs):
    ydl.params['logger'].warning('Subtitles are only available when logged in.')
    return {'subtitles':{'danmaku':[{'ext':'xml'}]}}
   with patch.object(YoutubeDL,'extract_info',autospec=True,side_effect=extract):
    with self.assertRaises(DownloadError) as raised:MediaDownloader(Path(tmp))._download_subtitle_with_ytdlp('https://www.bilibili.com/video/BV1ioh56JEFf',[],'example',[])
   self.assertEqual(raised.exception.code,'auth_required')
 def test_danmaku_is_not_subtitle_and_chinese_ai_precedes_english(self):
  self.assertEqual(choose_ytdlp_subtitle_language({'subtitles':{'danmaku':[{}]}}),('',False))
  self.assertEqual(choose_ytdlp_subtitle_language({'subtitles':{'en':[{}],'ai-zh':[{}],'danmaku':[{}]}}),('ai-zh',False))

if __name__=='__main__':unittest.main()
