"""Offline protocol vectors use synthetic identities, never the reference file."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend' if (ROOT/'backend').exists() else ROOT))
import hongguo_hm as hm
from hongguo_hm._primitives import SM3, _branch_one_bytes

VECTORS = json.loads((Path(__file__).parent/'fixtures/hm-v3-vectors.json').read_text())['cases']


class HeaderVectors(unittest.TestCase):
    def test_exact_vectors_all_four_timestamp_modes_and_sixteen_digest_selectors(self):
        self.assertEqual({(v['mode'], v['branch']) for v in VECTORS},
                         {(m, b) for m in range(4) for b in range(3)})
        self.assertEqual({(v['mode'], v['iv_selector']) for v in VECTORS},
                         {(m, i) for m in range(4) for i in range(16)})
        for case in VECTORS:
            with self.subTest(mode=case['mode'], selector=case['iv_selector']), \
                 patch.object(hm, '_new_entropy', return_value=hm._Entropy(*case['entropy'])):
                result = hm.generate_headers(case['url'], case['body'].encode(), case['khronos'])
                self.assertEqual(result, case['headers'])
                envelope = base64.b64decode(result['x-medusa'])
                self.assertEqual(int.from_bytes(envelope[:4], 'little') ^ case['khronos'], 3)

    def test_standard_sm3_known_vectors(self):
        self.assertEqual(SM3(b'abc').digest().hex(),
                         '66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0')
        self.assertEqual(SM3(b'abcd'*16).digest().hex(),
                         'debe9ff92275b8a138604889c18e5a4d6fdb70e5387e5765293dcba39c0c5732')

    def test_body_and_encoded_url_are_not_reserialized(self):
        v = VECTORS[0]
        body = v['body'].encode()
        with patch.object(hm, '_new_entropy', return_value=hm._Entropy(*v['entropy'])):
            original = hm.generate_headers(v['url'], body, v['khronos'])
            for url, data in [(v['url'].replace('%20','+'), body), (v['url'], body+b' '),
                              (v['url'].replace('100000000000000001','100000000000000099'),body),
                              (v['url'].replace('100000000000000002','100000000000000098'),body)]:
                result = hm.generate_headers(url, data, v['khronos'])
                self.assertEqual(result['x-helios'], original['x-helios'])
                self.assertNotEqual(result['x-medusa'], original['x-medusa'])

    def test_normal_calls_have_fresh_entropy_and_are_thread_safe(self):
        v = VECTORS[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: hm.generate_headers(v['url'],v['body'].encode(),v['khronos']),range(12)))
        self.assertEqual(len({r['x-helios'] for r in results}),12)
        self.assertEqual(len({r['x-medusa'] for r in results}),12)

    def test_only_final_bytes_and_known_profile_are_accepted(self):
        v = VECTORS[0]
        for body in ['{}', {}]:
            with self.assertRaises(TypeError):
                hm.generate_headers(v['url'],body,v['khronos'])
        for url in [v['url']+'&aid=8662',v['url'].replace('aid=8662','aid=1'),
                    v['url'].replace('device_id=','other='),v['url'].replace('version_name=','other='),
                    v['url']+'#fragment']:
            with self.assertRaises(ValueError):
                hm.generate_headers(url,b'{}',v['khronos'])

    def test_table_is_verified_even_when_first_loaded_on_demand(self):
        _branch_one_bytes.cache_clear()
        with patch.object(Path, 'read_bytes', return_value=b'corrupt'):
            with self.assertRaises(ValueError):
                _branch_one_bytes()
        self.assertEqual(len(_branch_one_bytes()),81936)

    def test_actual_api_uses_the_pair_for_jar_timestamp_not_wall_clock(self):
        # Uses the API-seam test harness but compares real emitted values to an
        # independent golden vector, including high-bit nonce/protobuf encoding.
        from test_model_signatures import ModelSignatureTests, JAR, BATCH
        harness = ModelSignatureTests()
        harness.setUp()
        try:
            v = VECTORS[0]
            with patch.object(hm, '_new_entropy', return_value=hm._Entropy(*v['entropy'])), \
                 patch.object(harness.api,'build_url',return_value=v['url']):
                harness.send(BATCH, {**JAR,'x-khronos':str(v['khronos'])},json.loads(v['body']))
            emitted = harness.calls[-1]
            self.assertEqual(emitted['data'],v['body'].encode())
            self.assertEqual({k:emitted['headers'][k] for k in v['headers']},v['headers'])
        finally:
            harness.doCleanups()


if __name__ == '__main__':
    unittest.main()
