"""Bounded live verification of the delivered API path, without model caching.

Run with --client desktop or cli. Only summaries are saved: no device values,
signatures, playback URLs or keys. This does not import any research/reference
implementation and deliberately asserts batch success instead of hiding fallback.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--client', choices=['desktop', 'cli'], default='desktop')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
project = ROOT if args.client == 'desktop' else ROOT.parent/'HongguoCLI'
sys.path[:0] = [str(project/'backend' if args.client == 'desktop' else project),
                str(ROOT/'.runtime/site-packages')]
args.output.parent.mkdir(parents=True, exist_ok=True)
os.environ['HG_DATA_DIR'] = str(args.output.parent/'runtime')
from hongguo_api import HongguoAPI, MODEL_PATH
from hongguo_signer import LocalSigner

VIDS = ['7689903030619081790', '7689903116275174462', '7689903130258983998',
        '7694949024280874009', '7694949018303990809']
report = {'client': args.client, 'started': time.strftime('%Y-%m-%d %H:%M:%S %z'),
          'signature_policy': 'jar + local Helios/Medusa v3', 'calls': [], 'checks': []}


class ObservedAPI(HongguoAPI):
    def _json_request(self, stage, method, url, headers, data, request_body=None):
        if stage == 'api' and urlsplit(url).path in {MODEL_PATH, '/novel/player/video_model/v1/'}:
            assert url == self.signed_url
            jar = self.jar
            assert all(headers[k] == v for k, v in jar.items() if k not in {'x-helios','x-medusa'})
            assert all(headers[k] != jar[k] for k in ['x-helios','x-medusa'])
            assert headers['x-ss-stub'] == hashlib.md5(data).hexdigest().upper()
            encoded = base64.b64decode(headers['x-medusa'])
            assert int.from_bytes(encoded[:4], 'little') ^ int(headers['x-khronos']) == 3
            report['calls'].append({'path': urlsplit(url).path,
                                    'only_hm_replaced': True, 'medusa_version': 3,
                                    'exact_url_body_timestamp': True})
        result = super()._json_request(stage, method, url, headers, data, request_body)
        if stage == 'signer':
            self.signed_url = request_body['url']
            self.jar = {k.lower():str(v) for k,v in result.items()}
        return result


try:
    with LocalSigner(project/'vendor') as signer:
        api = ObservedAPI(project/'config/config.json', signer.url, signer.token, timeout=30,
            device=json.loads((project/'config/devices.json').read_text(encoding='utf-8-sig'))[0])
        try:
            # Desktop intentionally resolves one episode per call; CLI retains
            # its groups of five. Both use their actual production models().
            for indices in ([0, 3], [3, 0]) if args.client == 'desktop' else (range(5), range(5)):
                vids = [VIDS[i] for i in indices]
                result = api.models(vids)
                assert result['complete'], result['errors']
                models = result['models']
                assert all(models[v]['complete'] and models[v]['tracks'] for v in vids)
                assert all(m.get('model_api', 'multi_video_model') == 'multi_video_model' for m in models.values())
                report['checks'].append({'vid_count':len(vids), 'track_counts':[len(models[v]['tracks']) for v in vids],
                                          'complete':True, 'api':'multi_video_model'})
            if args.client == 'desktop':
                body = {'video_id':VIDS[1], 'biz_param':{
                    'detail_page_version':0, 'device_level':3, 'disable_digg_stat':False,
                    'disable_video_relate_book':False, 'need_all_video_definition':True,
                    'need_mp4_align':False, 'use_os_player':False, 'use_server_dns':False, 'video_platform':1024}}
                result = api._api_once('POST','/novel/player/video_model/v1/',body)
                model = api._parse_model(VIDS[1],result['data'])
                assert model['complete']
                report['checks'].append({'vid_count':1,'complete':True,'api':'video_model'})
            signer.mark_success()
            report['passed'] = True
        finally:
            api.close()
except Exception as exc:
    report.update(passed=False,error=str(exc))
    raise
finally:
    report['finished'] = time.strftime('%Y-%m-%d %H:%M:%S %z')
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
