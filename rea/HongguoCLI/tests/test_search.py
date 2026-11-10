import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hongguo
from hongguo_api import HongguoAPI


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.first = json.loads((Path(__file__).parent / 'fixtures/rebirth-search.json').read_text())
        self.next = {'search_tabs': [{'data': [
            self.first['search_tabs'][0]['data'][0],
            {'book_id': 'next-series', 'video_data': [{'title': '下一页的剧', 'episode_cnt': 10}]}
        ], 'has_more': False}]}
        self.api = HongguoAPI(hongguo.ROOT / 'config/config.json', 'http://127.0.0.1:1', '')
        self.addCleanup(self.api.close)

    def test_recorded_page_includes_rankings_and_linked_series(self):
        with patch.object(self.api, '_api_once', return_value=self.first):
            found = self.api.search('重生')
        self.assertEqual(len(found['items']), 17)
        linked = next(x for x in found['items'] if x['title'] == '重生之舟起清雪')
        self.assertEqual(linked['series_id'], '7689759713147227160')
        self.assertEqual(linked['episode_cnt'], 83)
        self.assertNotIn('7690505057585875992', [x['series_id'] for x in found['items']])
        self.assertEqual(found['raw_pages'], [self.first])

    def test_resume_sends_server_cursor_without_refetching_first_page(self):
        with patch.object(self.api, '_api_once', side_effect=[self.first, self.next]) as request:
            first = self.api.search('重生')
            second = self.api.search('重生', cursor=first['next_cursor'])
        self.assertEqual(request.call_count, 2)
        query = request.call_args.kwargs['extra_query']
        self.assertEqual((query['offset'], query['passback'], query['search_id']),
                         ('6', 'recorded-page-cursor', 'recorded-search-id'))
        self.assertIsNone(second['next_cursor'])

    def test_interactive_more_keeps_numbers_and_deduplicates(self):
        output = io.StringIO()
        with patch('hongguo_api.HongguoAPI', return_value=self.api), \
             patch.object(self.api, '_api_once', side_effect=[self.first, self.next]) as request, \
             patch('builtins.input', side_effect=['n', '18']), \
             patch('hongguo.export_series', return_value=0) as export, \
             contextlib.redirect_stdout(output):
            code = hongguo.main(['重生', '--signer-url', 'http://127.0.0.1:1', '--export-only'])
        self.assertEqual(code, 0)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(export.call_args.args[1], 'next-series')
        self.assertIn('下一页', output.getvalue())

    def test_list_only_reports_more_results(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             patch('hongguo_api.HongguoAPI', return_value=self.api), \
             patch.object(self.api, '_api_once', return_value=self.first), \
             contextlib.redirect_stdout(output):
            code = hongguo.main(['重生', '--signer-url', 'http://127.0.0.1:1', '--list-only',
                                '--output', str(Path(directory) / 'search.json')])
        self.assertEqual(code, 0)
        self.assertIn('更多', output.getvalue())

    def test_stalled_cursor_is_not_offered_as_next_page(self):
        for cells in ([], [{'book_id': 'x', 'video_data': [{'episode_cnt': 1}]}]):
            with self.subTest(cells=cells):
                page = {'search_tabs': [{'data': cells, 'has_more': True, 'next_offset': 0}]}
                with patch.object(self.api, '_api_once', return_value=page) as request:
                    result = self.api.search('重生', 3)
                self.assertEqual(request.call_count, 1)
                self.assertTrue(result['warnings'])
                self.assertIsNone(result['next_cursor'])


if __name__ == '__main__':
    unittest.main()
