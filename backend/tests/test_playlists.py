import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app.playlists import preview_playlist


class PlaylistTests(unittest.TestCase):
    def test_bilibili_anthology_discovery_does_not_invent_part_selection(self):
        base = 'https://www.bilibili.com/video/BV1xx411c7mD'

        def extract(url, *, download):
            self.assertFalse(download)
            # yt-dlp BiliBiliIE expands pagelist entries only without p.
            self.assertNotIn('p', parse_qs(urlsplit(url).query))
            return {'_type': 'playlist', 'id': 'BV1xx411c7mD', 'title': 'Synthetic anthology',
                    'entries': [{'_type': 'url', 'url': f'{base}?p={part}',
                                 'ie_key': 'BiliBili', 'title': f'Synthetic part {part}'}
                                for part in (1, 2, 3)]}

        for value in (base, 'BV1xx411c7mD', base + '?fixture=public'):
            with self.subTest(value=value), patch('yt_dlp.YoutubeDL') as factory:
                extractor = factory.return_value.__enter__.return_value
                extractor.extract_info.side_effect = extract
                result = preview_playlist(value)
                self.assertEqual([item['url'] for item in result['sources']],
                                 [f'{base}?p={part}' for part in (1, 2, 3)])
                self.assertTrue(result['requires_confirmation'])
                self.assertFalse(result['download_started'])
                self.assertEqual(factory.call_args.args[0]['playlistend'], 24)
                self.assertTrue(factory.call_args.args[0]['skip_download'])
                if 'fixture=' in value:
                    self.assertIn('fixture=public', extractor.extract_info.call_args.args[0])

    def test_explicit_bilibili_part_remains_one_selected_episode(self):
        base = 'https://www.bilibili.com/video/BV1xx411c7mD'
        for part in (1, 2):
            url = f'{base}?p={part}'
            with self.subTest(part=part), patch('yt_dlp.YoutubeDL') as factory:
                extractor = factory.return_value.__enter__.return_value
                extractor.extract_info.return_value = {
                    'id': f'fixture-part-{part}', 'title': f'Synthetic part {part}',
                    'webpage_url': base}
                result = preview_playlist(url)
                extractor.extract_info.assert_called_once_with(url, download=False)
                self.assertEqual(result['sources'], [
                    {'kind': 'url', 'url': url, 'title': f'Synthetic part {part}'}])

    def test_empty_bilibili_playlist_does_not_fabricate_an_episode(self):
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = {
                '_type': 'playlist', 'id': 'empty-fixture', 'entries': []}
            with self.assertRaisesRegex(ValueError, 'playlist_has_no_accessible_entries'):
                preview_playlist('BV1xx411c7mD')

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
