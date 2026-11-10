import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/probe-runtime')
from app_api import AppAPI
from hongguo_signer import LocalSigner

def main():
    results = {}
    with LocalSigner(ROOT / 'vendor') as signer:
        device = json.loads((ROOT / 'config/devices.json').read_text(encoding='utf-8-sig'))[0]
        api = AppAPI(ROOT/'config/config.json', signer.url, signer.token, device=device, timeout=35)
        try:
            for name, operation in [
                ('rank', lambda: api.rank_page()),
                ('filters', lambda: api.category(panel=True)),
                ('category', lambda: api.category()),
                ('latest', lambda: api.category(latest=True)),
            ]:
                try:
                    r = operation()
                    results[name] = r
                    print(name, json.dumps(r if name == 'filters' else
                          {'count': len(r['items']), 'more': r['has_more'], 'cursor': r['next_cursor'],
                           'first': r['items'][:2]}, ensure_ascii=False), flush=True)
                    if r.get('has_more'):
                        nxt = api.rank_page(cursor=r['next_cursor']) if name == 'rank' else api.category(
                            cursor=r['next_cursor'], latest=name == 'latest')
                        results[name+'_next'] = nxt
                        print(name+'_next', len(nxt['items']), nxt['next_cursor'], flush=True)
                except Exception as e:
                    results[name] = {'error': str(e)}
                    raw = getattr(e, 'response', None)
                    if isinstance(raw, dict):
                        results[name]['response'] = raw
                    print(name, 'ERROR', str(e), flush=True)
            (ROOT/'docs/evidence/app-discovery-probe.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
            signer.mark_success()
        finally:
            api.close()

if __name__ == '__main__':
    main()
