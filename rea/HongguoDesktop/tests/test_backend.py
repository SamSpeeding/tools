import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'.runtime/site-packages')]
from app_api import AppAPI, APIError
from jobs import JobQueue, Cancelled, publish_file
from hongguo_download import completed_file, digest_file, atomic_json, command


def eventually(test, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if test():
            return
        time.sleep(.01)
    raise AssertionError('condition timed out')


class BackendTests(unittest.TestCase):
    def test_publish_is_atomic_and_never_replaces_an_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            candidate, final = folder / 'candidate.mp4', folder / 'final.mp4'
            candidate.write_bytes(b'validated video')
            publish_file(candidate, final)
            self.assertFalse(candidate.exists())
            self.assertEqual(final.read_bytes(), b'validated video')
            candidate.write_bytes(b'another video')
            with self.assertRaises(FileExistsError):
                publish_file(candidate, final)
            self.assertEqual(final.read_bytes(), b'validated video')
            self.assertEqual(candidate.read_bytes(), b'another video')

    def test_single_model_contract_maps_each_response_to_its_requested_episode(self):
        api = object.__new__(AppAPI)
        calls = []
        def respond(method, path, **kwargs):
            calls.append((path, kwargs['body']))
            if path == '/novel/player/multi_video_model/v1/':
                raise APIError('batch unavailable', response={'Code': 110001})
            self.assertEqual(path, '/novel/player/video_model/v1/')
            vid = kwargs['body']['video_id']
            self.assertNotIn('mixed_video_id_map', kwargs['body'])
            if vid == 'failed':
                raise APIError('unavailable', response={'Code': 110001})
            return {'code': 0, 'data': {'expire_time': 123,
                'video_model': json.dumps({'video_id': 'internal-' + vid, 'video_list': [
                    {'main_url': 'https://example.invalid/' + vid, 'video_meta': {'definition': '1080p', 'size': 100},
                     'encrypt_info': {'encrypt': True, 'spade_a': 'fixture'}}]})}}
        api._api_once = respond
        result = api.models(['first', 'failed', 'third', 'first'])
        self.assertEqual([b['video_id'] for _, b in calls if 'video_id' in b], ['first', 'failed', 'third'])
        self.assertEqual(result['missing_vids'], ['failed'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['models']['first']['tracks'][0]['definition'], '1080p')
        self.assertEqual(result['models']['third']['tracks'][0]['main_url'], 'https://example.invalid/third')
        self.assertEqual(result['models']['first']['tracks'][0]['encrypt_info']['spade_a'], 'fixture')

    def test_capitalized_platform_error_is_not_treated_as_empty_success(self):
        api = object.__new__(AppAPI)
        api.signer_url, api.signer_token = 'http://127.0.0.1:1', ''
        api.build_url = lambda *args: 'https://example.invalid/model'
        api._req_headers = lambda data: {}
        responses = iter([{'x-gorgon': 'test'}, {'Code': 110001, 'Message': '未知异常'}])
        api._json_request = lambda *args: next(responses)
        with self.assertRaisesRegex(APIError, '110001'):
            api._api_once('POST', '/model', body={})

    def test_category_cursor_counts_raw_rows_not_unique_cards(self):
        api = object.__new__(AppAPI)
        calls = []
        def response(*args, **kw):
            calls.append(kw['body'])
            return {'data': {'video_data': [{'series_id': '7692043430955863102', 'title': 'A'}] * 2 + [{}], 'has_more': True}}
        api._api_once = response
        page = api.category(cursor={'offset': 17}, selections={'category_dim_role': ['cate_36']})
        self.assertEqual(page['next_cursor'], {'offset': 20})
        self.assertEqual(len(page['items']), 1)
        self.assertIsInstance(page['items'][0]['series_id'], str)
        self.assertEqual(calls[0]['select_items']['category_dim_role'], ['cate_36'])

    def test_rank_must_advance_cursor(self):
        api = object.__new__(AppAPI)
        api._api_once = lambda *a, **kw: {'data': {'cell_view': {'cell_data': [], 'has_more': True, 'next_offset': '10'}}}
        self.assertFalse(api.rank_page(cursor={'offset': 10})['has_more'])

    def test_completed_file_detects_modified_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'episode.mp4'
            path.write_bytes(b'original')
            atomic_json(path.with_suffix('.json'), {'vid': 'v', 'quality': '1080p', 'full_decode_validated': True, 'sha256': digest_file(path)})
            self.assertTrue(completed_file(path, 'v', '1080p'))
            path.write_bytes(b'changed')
            self.assertFalse(completed_file(path, 'v', '1080p'))

    def test_queue_serial_cancel_retry_dedup_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            running = threading.Event()
            sequence = []
            def runner(job, factory, vendor, update, check):
                sequence.append(job['index'])
                running.set()
                while True:
                    check()
                    time.sleep(.01)
            q = JobQueue(temp, None, None, lambda event: None, runner)
            detail = {'series_id': '7692043430955863102', 'complete': True, 'meta': {'title': 'Test'},
                      'episodes': [{'index': i, 'vid': f'v{i}'} for i in [1, 2]]}
            try:
                one = q.enqueue(detail, 1, '1080p', temp)
                self.assertTrue(running.wait(2))
                two = q.enqueue(detail, 2, '1080p', temp)
                self.assertEqual(q.enqueue(detail, 1, '1080p', temp)['id'], one['id'])
                self.assertEqual(sequence, [1])
                q.action(two['id'], 'cancel')
                self.assertEqual(q.snapshot()[1]['status'], 'cancelled')
                q.action(one['id'], 'cancel')
                eventually(lambda: q.snapshot()[0]['status'] == 'cancelled')
                q.action(two['id'], 'retry')
                eventually(lambda: sequence == [1, 2])
            finally:
                q.close()
            restarted = JobQueue(temp, None, None, lambda e: None, runner)
            try:
                self.assertEqual(restarted.snapshot()[1]['status'], 'interrupted')
                self.assertEqual(sequence, [1, 2])
            finally:
                restarted.close()

    def test_cancel_terminates_media_subprocess(self):
        start = time.monotonic()
        def check():
            if time.monotonic() - start > .4:
                raise Cancelled()
        with self.assertRaises(Cancelled):
            command([sys.executable, '-c', 'import time;time.sleep(30)'], check_cancel=check)
        self.assertLess(time.monotonic() - start, 2)


if __name__ == '__main__':
    unittest.main()
