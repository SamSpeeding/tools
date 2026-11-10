"""One-time OFFLINE oracle capture. Production/tests never import this reference.

Only definitions/constants in the signing section are compiled; no plugin/network
initializers run. Synthetic IDs and fixed entropy make these public test vectors.
"""
import ast
import base64
import hashlib
import json
import lzma
from pathlib import Path
import random
import struct
import time
from typing import Any, Mapping
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit, urlencode

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path('/Users/tt/Downloads/红果短剧.py')
source = SOURCE.read_text()
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == 'bea893bea56a24cee9eadc4c004bf9637b6c2129d08b22c9500c012431edd6f1'
tree = ast.parse(source)
nodes = [n for n in tree.body if 1261 <= n.lineno < 3298]
scope = dict(globals(), hashes=None)
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<offline-signature-oracle>', 'exec'), scope)
body = json.dumps({'mixed_video_id_map': {'1': ['1000000000000000001', '1000000000000000002']},
                   'note': '测试 空格'}, ensure_ascii=False, separators=(',', ':')).encode()
entropy = [0x12345678, 0xFEDCBA98, 111, 10987, 0x76543210, 0x89ABCDEF]
cases=[]
# Cover all 4 timestamp selectors × all 16 f13 IV selectors.
for mode in range(4):
    ts = 1791944700 + mode
    for iv_selector in range(16):
        branch = iv_selector % 3
        for nonce in range(1000):
            url = ('https://api5-normal-sinfonlinec.fqnovel.com/novel/player/multi_video_model/v1/'
                   '?aid=8662&device_id=100000000000000001&iid=100000000000000002&version_name=7.2.9.32'
                   '&device_type=Test%20Phone&device_brand=TestBrand&os_version=12'
                   f'&query=%E5%89%A7%20a%2Bb%2A&_rticket={ts*1000+nonce}')
            query = dict(parse_qsl(urlsplit(url).query))
            qhash = scope['SM3'](urlsplit(url).query).digest()
            iv=scope['get_iv'](scope['get_iv'](scope['get_iv'](0x20230928,qhash),hashlib.md5(body).digest()),ts.to_bytes(4,'little'))
            if iv & 15 == iv_selector:
                break
        devices={'device_id':query['device_id'], 'version_name':query['version_name'],
                 'device_model':query['device_type'], 'device_brand':query['device_brand'],
                 'device_manufacturer':query['device_brand'], 'os_version':query['os_version']}
        with patch.object(random, 'randint', side_effect=entropy), patch.object(time, 'time', return_value=ts):
            h=scope['_encrypt_helios'](ts)
            m=scope['_gen_medusa'](url, query, devices, body, ts, 'application/json; charset=UTF-8')
        cases.append(dict(mode=mode,branch=branch,iv_selector=iv_selector,url=url,body=body.decode(),khronos=ts,
                          entropy=entropy,headers={'x-helios':h,'x-medusa':m}))
report={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'scope':'synthetic identities; offline; fixed entropy; no live signatures', 'cases':cases}
for folder in [ROOT/'tests/fixtures', ROOT.parent/'HongguoCLI/tests/fixtures']:
    folder.mkdir(exist_ok=True)
    (folder/'hm-v3-vectors.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Golden vectors:',len(cases))
