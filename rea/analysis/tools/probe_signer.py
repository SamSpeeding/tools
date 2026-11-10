"""Bounded smoke probe, retaining responses without printing signature values."""
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hongguo_signer import LocalSigner

cfg = json.loads((ROOT/'analysis/extracted/app/config.json').read_text())
if '--device' in sys.argv:
    device = json.loads((ROOT/'analysis/extracted/app/devices.json').read_text())[0]
    cfg['base_query'].update(device['query'])
    cfg['session_headers']['user-agent'] = device['user_agent']
query = dict(cfg['base_query'], query='逆袭', tab_name='feed', search_source='1',
             offset='0', count='0', use_correct='true', _rticket=str(int(time.time()*1000)))
url = 'https://' + cfg['api_host'] + '/reading/bookapi/search/tab/v?' + '&'.join(
    f'{key}={urllib.parse.quote(str(value), safe="")}' for key, value in query.items())
headers = dict(cfg['session_headers'], **{'content-type':'application/json; charset=utf-8'})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with LocalSigner(ROOT/'analysis/extracted/app') as signer:
    req = urllib.request.Request(signer.url+'/sign', data=json.dumps({'url':url,'headers':headers}).encode(),
                                 headers={'Content-Type':'application/json','X-Sign-Token':signer.token})
    with opener.open(req,timeout=90) as r:
        signed = json.load(r)
    print('signature keys:', list(signed), flush=True)
    if not signed:
        raise RuntimeError('Signer returned no signature')
    if '--search' in sys.argv:
        from curl_cffi import requests
        r = requests.get(url, headers={**headers, **signed}, timeout=60, impersonate='chrome')
        print('search status:', r.status_code, 'bytes:', len(r.content), flush=True)
        (ROOT/'analysis/evidence/signed-search-probe.json').write_bytes(r.content)
        if r.content:
            j = r.json()
            print('response keys:', list(j), 'code:', j.get('code'))
        else:
            print('empty response; headers:', dict(r.headers))
