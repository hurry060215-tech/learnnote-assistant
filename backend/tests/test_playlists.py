import unittest
from unittest.mock import patch

from app.playlists import preview_playlist


class PlaylistTests(unittest.TestCase):
    def test_preview_is_bounded_and_never_downloads(self):
        info={"title":"公开课程","entries":[{"id":f"abcdefgh{i:03}","url":f"abcdefgh{i:03}","ie_key":"Youtube","title":str(i)} for i in range(80)]}
        with patch('yt_dlp.YoutubeDL') as factory:
            extractor=factory.return_value.__enter__.return_value
            extractor.extract_info.return_value=info
            result=preview_playlist('https://www.youtube.com/playlist?list=PLfixture')
            self.assertEqual(len(result['sources']),24)
            self.assertFalse(result['download_started'])
            self.assertFalse(extractor.extract_info.call_args.kwargs['download'])
            self.assertEqual(factory.call_args.args[0]['playlistend'],24)

    def test_arbitrary_or_private_hosts_are_not_crawled(self):
        for url in ('http://127.0.0.1/private','https://example.com/playlist'):
            with self.assertRaises(ValueError):
                preview_playlist(url)


if __name__=='__main__':
    unittest.main()
