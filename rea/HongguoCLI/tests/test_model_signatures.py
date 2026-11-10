"""The actual API seam: same request/identity, replace only the two model headers."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend' if (ROOT/'backend').exists() else ROOT),
                str(ROOT/'.runtime/site-packages')]
from hongguo_api import HongguoAPI, APIError

BATCH = '/novel/player/multi_video_model/v1/'
SINGLE = '/novel/player/video_model/v1/'
JAR = {f'x-{key}': f'jar-{key}' for key in ['helios','medusa','gorgon','argus','ladon','neptune','soter']}
JAR['x-khronos'] = '1791944700'


class ModelSignatureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = Path(temp.name)/'config.json'
        config.write_text(json.dumps({'api_host':'api5-normal-sinfonlinec.fqnovel.com',
            'base_query':{'aid':'8662','device_id':'100000000000000001','iid':'100000000000000002',
                          'version_name':'7.2.9.32','device_type':'Test Phone','device_brand':'Test', 'os_version':'12'},
            'session_headers':{'user-agent':'test','x-app-extra':'unchanged'}}))
        self.api = HongguoAPI(config, 'http://127.0.0.1:1', 'local-token')
        self.addCleanup(self.api.close)
        self.calls=[]

    def send(self, path, signed=None, body=None):
        def fake(stage, method, url, headers, data, request_body=None):
            self.calls.append(dict(stage=stage,method=method,url=url,headers=dict(headers),data=data,body=request_body))
            return dict(JAR if signed is None else signed) if stage == 'signer' else {'code':0}
        with patch.object(self.api, '_json_request', side_effect=fake):
            return self.api._api_once('POST', path, body=body or {'mixed_video_id_map': {'1':['vid']}, 'note':'剧 名'})

    def test_models_replace_only_hm_with_exact_url_bytes_and_timestamp(self):
        for path in [BATCH,SINGLE]:
            with self.subTest(path=path):
                self.calls.clear()
                self.send(path)
                signing, outgoing = self.calls
                self.assertNotEqual(outgoing['headers']['x-helios'], JAR['x-helios'])
                self.assertNotEqual(outgoing['headers']['x-medusa'], JAR['x-medusa'])
                for key in JAR.keys()-{'x-helios','x-medusa'}:
                    self.assertEqual(outgoing['headers'][key],JAR[key])
                self.assertEqual(signing['body']['url'],outgoing['url'])
                self.assertEqual(outgoing['headers']['x-ss-stub'],hashlib.md5(outgoing['data']).hexdigest().upper())
                self.assertEqual(outgoing['headers']['x-app-extra'],'unchanged')
                self.assertEqual(outgoing['data'], '{"mixed_video_id_map":{"1":["vid"]},"note":"剧 名"}'.encode())
                self.assertNotIn('X-Sign-Token',outgoing['headers'])
                self.assertEqual(self.api.config['base_query']['device_id'],'100000000000000001')

    def test_discovery_keeps_original_jar_signatures(self):
        for path in ['/reading/bookapi/search/tab/v','/novel/player/multi_video_detail/v1/',
                     '/reading/bookapi/bookmall/cell/change/v','/reading/distribution/category/landpage/v']:
            self.send(path)
            self.assertTrue(all(self.calls[-1]['headers'][k] == v for k,v in JAR.items()))

    def test_missing_or_invalid_timestamp_stops_before_platform_request(self):
        # Even a stale config value must not hide a missing JAR timestamp.
        self.api.config['session_headers']['x-khronos'] = JAR['x-khronos']
        for ts in [None,'not-a-number','-1','4294967296']:
            self.calls.clear()
            signed=dict(JAR)
            if ts is None:
                del signed['x-khronos']
            else:
                signed['x-khronos']=ts
            with self.assertRaises(APIError) as caught:
                self.send(BATCH,signed)
            self.assertEqual(caught.exception.stage,'signer')
            self.assertEqual(len(self.calls),1)

    def test_body_stub_mismatch_stops_before_platform_request(self):
        with self.assertRaises(APIError) as caught:
            self.send(BATCH,{**JAR,'x-ss-stub':'0'*32})
        self.assertEqual(caught.exception.stage,'signer')
        self.assertEqual(len(self.calls),1)

    def test_case_insensitive_jar_headers(self):
        self.send(BATCH,{k.upper():v for k,v in JAR.items()})
        self.assertEqual(self.calls[-1]['headers']['x-khronos'],JAR['x-khronos'])
        self.assertNotEqual(self.calls[-1]['headers']['x-medusa'],JAR['x-medusa'])

    def test_unsupported_profile_is_explicit_not_a_silent_jar_fallback(self):
        self.api.config['base_query']['aid']='9999'
        with self.assertRaises(APIError) as caught:
            self.send(BATCH)
        self.assertEqual(caught.exception.stage,'signer')
        self.assertEqual(len(self.calls),1)

if __name__ == '__main__':
    unittest.main()
