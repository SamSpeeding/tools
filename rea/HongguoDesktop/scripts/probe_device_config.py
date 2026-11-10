"""Bounded device-config comparison; does not change the app's configuration.

Uses only existing records. Keeps identities out of the diagnostic report.
This checks request consistency, not whether the platform accepts an identity.
"""
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/device-probe-runtime')
from app_api import AppAPI
from hongguo_api import MODEL_PATH
from hongguo_signer import LocalSigner

SID = '7689863296106646590'
VID = '7689903116275174462'
devices = json.loads((ROOT / 'config/devices.json').read_text(encoding='utf-8-sig'))
config = json.loads((ROOT / 'config/config.json').read_text(encoding='utf-8-sig'))
report = {
    'device_count': len(devices),
    'query_key_sets': sorted({','.join(sorted(d['query'])) for d in devices}),
    'all_user_agents_match_base': all(d.get('user_agent') == config['session_headers'].get('user-agent') for d in devices),
    'config_matches_old_CLI': all((ROOT / 'config' / n).read_bytes() == (ROOT.parent / 'HongguoCLI/config' / n).read_bytes() for n in ['config.json', 'devices.json']),
    'sequence': [],
}
output = ROOT / 'docs/evidence/device-config-check.json'
with LocalSigner(ROOT / 'vendor') as signer:
    # Default, two additional existing records, then default again as control.
    for index in [0, 34, 68, 0]:
        api = AppAPI(ROOT / 'config/config.json', signer.url, signer.token,
                     device=devices[index], timeout=25)
        started = time.monotonic()
        item = {'device_index': index}
        try:
            query = parse_qs(urlsplit(api.build_url(MODEL_PATH)).query)
            item['identity_fields_match_selected_record'] = all(query[k] == [str(v)] for k, v in devices[index]['query'].items())
            headers = api._req_headers(b'{}')
            item['UA_matches_selected_record'] = headers['user-agent'] == devices[index]['user_agent']
            item['cookie_or_token_header_present'] = any(k in headers for k in ['cookie', 'x-tt-token'])
            detail = api.detail(SID)
            item['detail'] = {'complete': detail['complete'], 'episodes': len(detail['episodes'])}
            item['episode_vid_matches'] = any(e.get('vid') == VID for e in detail['episodes'])
            result = api.models([VID])
            item['models'] = {'complete': result['complete'], 'count': len(result['models']), 'errors': result['errors']}
        except Exception as exc:
            item['exception'] = str(exc)
        finally:
            api.close()
        item['seconds'] = round(time.monotonic() - started, 2)
        report['sequence'].append(item)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(item, ensure_ascii=False), flush=True)
    signer.mark_success()
