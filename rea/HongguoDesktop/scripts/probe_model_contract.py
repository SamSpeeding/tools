"""Small, same-App model-contract comparison using PHP reference shapes."""
from pathlib import Path
import argparse
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/model-contract-runtime')
from app_api import AppAPI
from hongguo_api import APIError
from hongguo_signer import LocalSigner

parser = argparse.ArgumentParser()
parser.add_argument('--configured-device', type=int)
args = parser.parse_args()
suffix = ''
if args.configured_device is not None:
    device = json.loads((ROOT / 'config/devices.json').read_text(encoding='utf-8-sig'))[args.configured_device]
    suffix = f'-device-{args.configured_device}'
else:
    private = json.loads((ROOT / 'docs/evidence/registration-runtime/target_app_metadata_candidate.json').read_text())
    registration = private['response']
    config = json.loads((ROOT / 'config/config.json').read_text(encoding='utf-8-sig'))
    device = {'query': {'device_id': registration['device_id_str'], 'iid': registration['install_id_str'],
                       'cdid': private['request']['header']['cdid']},
              'user_agent': config['session_headers']['user-agent']}
VID = '7689903116275174462'
# Keep this diagnostic anchored to the original failing contract after fixes.
MODEL_PATH = '/novel/player/multi_video_model/v1/'
biz = {'detail_page_version': 0, 'device_level': 3, 'disable_digg_stat': False,
       'disable_video_relate_book': False, 'need_all_video_definition': True,
       'need_mp4_align': False, 'use_os_player': False, 'use_server_dns': False,
       'video_platform': 1024}
variants = [
    ('original_batch', MODEL_PATH, {'biz_param': biz, 'mixed_video_id_map': {'1': [VID]}}),
    ('same_path_video_id', MODEL_PATH, {'biz_param': biz, 'video_id': VID}),
    ('single_path_video_id', '/novel/player/video_model/v1/', {'biz_param': biz, 'video_id': VID}),
    ('single_path_platform_3', '/novel/player/video_model/v1/', {'biz_param': {**biz, 'video_platform': 3}, 'video_id': VID}),
]
report = {'aid': '8662', 'configured_device': args.configured_device,
          'scope': 'reference shapes, one change per adjacent request', 'runs': []}


def models_summary(response):
    found = []
    def visit(value):
        if isinstance(value, dict):
            raw = value.get('video_model')
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except ValueError: raw = None
            if isinstance(raw, dict):
                tracks = raw.get('video_list')
                iterable = tracks.values() if isinstance(tracks, dict) else tracks or []
                found.append({'track_shape': type(tracks).__name__, 'tracks': len(tracks or []),
                              'with_addresses': sum(isinstance(t, dict) and bool(t.get('main_url') or t.get('backup_url')) for t in iterable)})
            for key, child in value.items():
                if key != 'video_model': visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(response)
    return found


with LocalSigner(ROOT / 'vendor') as signer:
    api = AppAPI(ROOT / 'config/config.json', signer.url, signer.token, device=device, timeout=25)
    try:
        for label, path, body in variants:
            started = time.monotonic()
            item = {'name': label, 'path': path}
            try:
                result = api._api_once('POST', path, body=body)
                item['response_keys'] = sorted(result)
                item['models'] = models_summary(result)
                if not item['models']:
                    item['response'] = result
                else:
                    runtime = ROOT / 'docs/evidence/model-contract-runtime'
                    runtime.mkdir(exist_ok=True)
                    fd = os.open(runtime / (label + suffix + '.json'), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'w') as f: json.dump(result, f, ensure_ascii=False)
            except APIError as exc:
                item.update(error=str(exc), response=exc.response)
            item['seconds'] = round(time.monotonic() - started, 2)
            report['runs'].append(item)
            (ROOT / f'docs/evidence/model-contract-probe{suffix}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(item, ensure_ascii=False), flush=True)
    finally:
        api.close()
    signer.mark_success()
