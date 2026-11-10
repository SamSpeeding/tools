import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'.runtime/site-packages')]
from app_api import AppAPI, APIError
from jobs import Cancelled

BATCH = '/novel/player/multi_video_model/v1/'
SINGLE = '/novel/player/video_model/v1/'


def entry(vid):
    return {'video_model': json.dumps({'video_list': [
        {'main_url': 'https://example.invalid/' + vid,
         'video_meta': {'definition': '1080p', 'size': 123},
         'encrypt_info': {'encrypt': True, 'spade_a': 'fixture'}}]})}


class ModelFallbackTests(unittest.TestCase):
    def client(self, respond):
        api = object.__new__(AppAPI)
        calls = []
        def request(method, path, *, body):
            calls.append((path, body))
            self.assertEqual(method, 'POST')
            return respond(path, body)
        api._api_once = request
        return api, calls

    def test_batch_success_never_requests_single(self):
        api, calls = self.client(lambda path, body: {'data': {'episode': entry('episode')}})
        events = []
        result = api.models(['episode', 'episode'], on_source=events.append)
        self.assertEqual([p for p, _ in calls], [BATCH])
        self.assertEqual(calls[0][1]['mixed_video_id_map'], {'1': ['episode']})
        self.assertTrue(result['complete'])
        self.assertEqual(result['models']['episode']['model_api'], 'multi_video_model')
        self.assertEqual([e['model_api_state'] for e in events], ['requesting', 'selected'])
        self.assertFalse(events[-1]['model_fallback'])

    def test_batch_failures_fall_back_without_marking_download_failed(self):
        for failure in ('api_error', 'transport', 'missing', 'invalid_json', 'no_url'):
            with self.subTest(failure=failure):
                def respond(path, body):
                    if path == SINGLE:
                        self.assertEqual(body['video_id'], 'episode')
                        self.assertNotIn('mixed_video_id_map', body)
                        return {'data': entry('episode')}
                    if failure == 'api_error':
                        raise APIError('Code=110001', response={'Code': 110001})
                    if failure == 'transport':
                        raise APIError('timed out')
                    if failure == 'missing':
                        return {'data': {}}
                    if failure == 'invalid_json':
                        return {'data': {'episode': {'video_model': '{broken'}}}
                    return {'data': {'episode': {'video_model': {'video_list': [{'video_meta': {}}]}}}}
                api, calls = self.client(respond)
                events = []
                result = api.models(['episode'], on_source=events.append)
                self.assertEqual([p for p, _ in calls], [BATCH, SINGLE])
                self.assertTrue(result['complete'])
                self.assertEqual(result['errors'], [])
                self.assertEqual(result['models']['episode']['model_api'], 'video_model')
                self.assertEqual(result['models']['episode']['tracks'][0]['encrypt_info']['spade_a'], 'fixture')
                self.assertTrue(events[-1]['model_fallback'])
                self.assertTrue(events[-1]['model_fallback_reason'])
                self.assertEqual([a['outcome'] for a in result['attempts']], ['failed', 'selected'])

    def test_both_failures_keep_both_attempts_and_no_usable_model(self):
        def respond(path, body):
            raise APIError('unavailable ' + path, response={'Code': 110001})
        api, calls = self.client(respond)
        result = api.models(['episode'])
        self.assertEqual(len(calls), 2)
        self.assertFalse(result['complete'])
        self.assertEqual(result['models'], {})
        self.assertEqual(result['missing_vids'], ['episode'])
        self.assertEqual(len(result['attempts']), 2)
        self.assertIn('video_model', result['errors'][0]['error'])

    def test_signer_failure_does_not_repeat_the_same_broken_signer(self):
        def respond(path, body):
            raise APIError('signer unavailable', stage='signer')
        api, calls = self.client(respond)
        result = api.models(['episode', 'another'])
        self.assertEqual([p for p, _ in calls], [BATCH])
        self.assertEqual(result['missing_vids'], ['episode', 'another'])

    def test_cancel_between_endpoints_prevents_fallback_request(self):
        def respond(path, body):
            raise APIError('Code=110001', response={'Code': 110001})
        api, calls = self.client(respond)
        def progress(event):
            if event['model_api'] == 'video_model':
                raise Cancelled()
        with self.assertRaises(Cancelled):
            api.models(['episode'], on_source=progress)
        self.assertEqual([p for p, _ in calls], [BATCH])


if __name__ == '__main__':
    unittest.main()
