"""Compare the original primary/backup model hosts without changing app config."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/model-host-runtime')

from hongguo_api import HongguoAPI, APIError, MODEL_PATH, SINGLE_MODEL_PATH
from hongguo_signer import LocalSigner

VID = '7689903116275174462'
PRIMARY = 'api5-normal-sinfonlinec.fqnovel.com'
BACKUP = 'api5-normal-sinfonlineb.fqnovel.com'
BIZ = {
    'detail_page_version': 0, 'device_level': 3, 'disable_digg_stat': False,
    'disable_video_relate_book': False, 'need_all_video_definition': True,
    'need_mp4_align': False, 'use_os_player': False, 'use_server_dns': False,
    'video_platform': 1024,
}
OUTPUT = ROOT / 'docs/evidence/model-host-comparison.json'
CONFIG_FILES = [ROOT / 'config/config.json', ROOT / 'config/devices.json']


def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in CONFIG_FILES}


class ProbeAPI(HongguoAPI):
    """Retain only public response metadata, never signed URLs or device IDs."""

    def _trace(self, record):
        if record['stage'] != 'api':
            return
        response = record.get('response')
        self.observation = {'http_status': record.get('status')}
        if isinstance(response, dict):
            self.observation['response_keys'] = list(response)
            for key in ('code', 'Code', 'message', 'Message', 'msg', 'status_code'):
                if key in response:
                    self.observation[key] = response[key]
            base = response.get('BaseResp')
            if isinstance(base, dict):
                self.observation['BaseResp'] = {
                    k: base[k] for k in ('StatusCode', 'StatusMessage') if k in base
                }


def main():
    before = hashes()
    device = json.loads(CONFIG_FILES[1].read_text(encoding='utf-8-sig'))[0]
    report = {
        'started_at': datetime.now(timezone.utc).isoformat(),
        'purpose': 'Original primary vs API_HOST_B; direct endpoint calls, no model fallback',
        'original_backup_evidence': 'analysis/evidence/hongguo.dis.txt:1366,6244-6267',
        'device_index': 0, 'vid': VID, 'config_hashes_before': before,
        'request_controls': 'Same device, client session, signer, business body; each host URL signed anew',
        'results': [],
    }
    with LocalSigner(ROOT / 'vendor') as signer:
        api = ProbeAPI(CONFIG_FILES[0], signer.url, signer.token, device=device, timeout=25)
        report['configured_host'] = api.host
        report['aid'] = str(api.config['base_query'].get('aid'))
        try:
            for host, path in (
                (PRIMARY, MODEL_PATH), (BACKUP, MODEL_PATH),
                (PRIMARY, SINGLE_MODEL_PATH), (BACKUP, SINGLE_MODEL_PATH),
                (PRIMARY, MODEL_PATH),
            ):
                api.host = host  # Isolated in-memory override; no config writes.
                api.observation = {}
                single = path == SINGLE_MODEL_PATH
                body = {'biz_param': BIZ, **({'video_id': VID} if single else
                        {'mixed_video_id_map': {'1': [VID]}})}
                encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
                row = {'host': host, 'path': path, 'method': 'POST',
                       'body_sha256': hashlib.sha256(encoded).hexdigest(),
                       'started_at': datetime.now(timezone.utc).isoformat()}
                started = time.monotonic()
                try:
                    result = api._api_once('POST', path, body=body)
                    data = result.get('data') or {}
                    item = data if single else data.get(VID, {})
                    parsed = api._parse_model(VID, item)
                    row.update(outcome='usable_model', track_count=len(parsed['tracks']),
                               definitions=[t.get('definition') for t in parsed['tracks']],
                               tracks_with_urls=sum(
                                   any(isinstance(t.get(k), str) and t[k].startswith(('http://', 'https://'))
                                       for k in ('main_url', 'backup_url'))
                                   for t in parsed['tracks']))
                except (APIError, ValueError, TypeError, AttributeError) as exc:
                    row.update(outcome='failed', error=str(exc),
                               stage=exc.stage if isinstance(exc, APIError) else 'model')
                row.update(api.observation)
                row['seconds'] = round(time.monotonic() - started, 3)
                report['results'].append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                report['config_hashes_after'] = hashes()
                report['config_unchanged'] = before == report['config_hashes_after']
                OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            signer.mark_success()
        finally:
            api.close()
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Report: {OUTPUT}', flush=True)


if __name__ == '__main__':
    main()
