"""Change only device_id in isolated clients; never persist experimental devices."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/batch-device-id-runtime')
from hongguo_api import HongguoAPI, APIError, MODEL_PATH
from hongguo_signer import LocalSigner


class ProbeAPI(HongguoAPI):
    def _trace(self, record):
        if record['stage'] == 'api':
            self.http_status = record.get('status')


def main():
    configs = [ROOT/'config/config.json', ROOT/'config/devices.json']
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in configs}
    original = json.loads(configs[1].read_text(encoding='utf-8-sig'))[0]
    original_id = str(original['query']['device_id'])
    digits = len(original_id)
    candidates = {'original': original_id}
    for label in ('new_B', 'new_C'):
        while True:
            value = str(10**(digits-1) + secrets.randbelow(9 * 10**(digits-1)))
            if value not in candidates.values():
                candidates[label] = value
                break
    vid = '7689903116275174462'
    body = {'biz_param': {
        'detail_page_version': 0, 'device_level': 3, 'disable_digg_stat': False,
        'disable_video_relate_book': False, 'need_all_video_definition': True,
        'need_mp4_align': False, 'use_os_player': False, 'use_server_dns': False,
        'video_platform': 1024,
    }, 'mixed_video_id_map': {'1': [vid]}}
    report = {'time': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
              'vid': vid, 'type_key': '1', 'device_index': 0,
              'changed_field': 'device.query.device_id',
              'controls': 'Original production config, same iid/install_id and other device fields, body, signer and client. Each request signed anew. No registration.',
              'config_hashes_before': before, 'results': []}
    output = ROOT/'docs/evidence/batch-device-id-comparison.json'
    with LocalSigner(ROOT/'vendor') as signer:
        api = ProbeAPI(configs[0], signer.url, signer.token, device=original, timeout=25)
        report['host'] = api.host
        report['version'] = str(original['query'].get('version_name', api.config['base_query'].get('version_name')))
        try:
            for label in ('original', 'new_B', 'new_B', 'original', 'new_C', 'new_C'):
                candidate = deepcopy(original)
                candidate['query']['device_id'] = candidates[label]
                changed = [key for key in set(original['query']) | set(candidate['query'])
                           if original['query'].get(key) != candidate['query'].get(key)]
                assert changed == ([] if label == 'original' else ['device_id'])
                api.device = candidate
                api.http_status = None
                started = time.monotonic()
                row = {'device_group': label, 'changed_query_keys': changed,
                       'device_id_sha256': hashlib.sha256(candidates[label].encode()).hexdigest()}
                try:
                    response = api._api_once('POST', MODEL_PATH, body=body)
                    model = api._parse_model(vid, (response.get('data') or {}).get(vid, {}))
                    row.update(outcome='usable_model', code=response.get('code', response.get('Code')),
                               definitions=[t.get('definition') for t in model['tracks']])
                except (APIError, ValueError, TypeError) as exc:
                    response = exc.response if isinstance(exc, APIError) and isinstance(exc.response, dict) else {}
                    row.update(outcome='failed', code=response.get('code', response.get('Code')), error=str(exc))
                row.update(http_status=api.http_status, seconds=round(time.monotonic()-started, 3))
                report['results'].append(row)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
                print(json.dumps(row, ensure_ascii=False), flush=True)
                time.sleep(1.1)
            signer.mark_success()
        finally:
            api.close()
    report['config_hashes_after'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in configs}
    report['config_unchanged'] = report['config_hashes_after'] == before
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(str(output), flush=True)


if __name__ == '__main__':
    main()
