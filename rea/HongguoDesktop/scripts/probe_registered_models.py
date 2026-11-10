"""Compare the configured profile with one newly issued aid=8662 pair.

Reads the private registration experiment; does not register or install profiles.
"""
from pathlib import Path
import hashlib
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/registered-model-runtime')
from app_api import AppAPI
from hongguo_api import APIError
from hongguo_signer import LocalSigner

private = json.loads((ROOT / 'docs/evidence/registration-runtime/target_app_metadata_candidate.json').read_text())
header, response = private['request']['header'], private['response']
device_id = str(response.get('device_id_str') or response.get('device_id') or '0')
iid = str(response.get('install_id_str') or response.get('install_id') or '0')
assert device_id.isdigit() and int(device_id) > 0
assert iid.isdigit() and int(iid) > 0
config = json.loads((ROOT / 'config/config.json').read_text(encoding='utf-8-sig'))
old = json.loads((ROOT / 'config/devices.json').read_text(encoding='utf-8-sig'))[0]
fresh = {'query': {'device_id': device_id, 'iid': iid, 'cdid': header['cdid']},
         'user_agent': config['session_headers']['user-agent']}
report = {'scope': 'same aid=8662, endpoint, signer and model body; replace only identity tuple', 'runs': []}
# Freeze the failing original contract; production models() now uses a different endpoint.
model_path = '/novel/player/multi_video_model/v1/'
model_body = {'biz_param': {'detail_page_version': 0, 'device_level': 3,
    'disable_digg_stat': False, 'disable_video_relate_book': False,
    'need_all_video_definition': True, 'need_mp4_align': False,
    'use_os_player': False, 'use_server_dns': False, 'video_platform': 1024},
    'mixed_video_id_map': {'1': ['7689903116275174462']}}
with LocalSigner(ROOT / 'vendor') as signer:
    for label, device in [('configured_device_0', old), ('fresh_registered_pair', fresh), ('configured_device_0_control', old)]:
        api = AppAPI(ROOT / 'config/config.json', signer.url, signer.token, device=device, timeout=25)
        before = time.monotonic()
        result = {'profile': label,
                  'identity_digest': hashlib.sha256(json.dumps(device['query'], sort_keys=True).encode()).hexdigest()}
        try:
            detail = api.detail('7689863296106646590')
            result['detail'] = {'complete': detail['complete'], 'episodes': len(detail['episodes'])}
            try:
                model = api._api_once('POST', model_path, body=model_body)
                data = model.get('data') or {}
                result['models'] = {'response_keys': sorted(model), 'data_keys': sorted(data) if isinstance(data, dict) else [],
                                    'note': 'Request accepted; inspect response before declaring usable media.'}
            except APIError as exc:
                result['models'] = {'complete': False, 'count': 0,
                    'errors': [{'error': str(exc), 'stage': exc.stage, 'raw_response': exc.response}]}
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            api.close()
        result['seconds'] = round(time.monotonic() - before, 2)
        report['runs'].append(result)
        (ROOT / 'docs/evidence/registered-model-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False), flush=True)
    signer.mark_success()
