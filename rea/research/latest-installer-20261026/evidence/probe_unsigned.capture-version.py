"""Bounded live test of v77's shipped unsigned GET functions, without module init.

Only selected, inspected code objects are bound. No installer startup, signer,
device rotation, retry, fallback, or CDN/media request. Persist raw responses
privately and summarize without signed URLs, device identifiers or key material.
"""
import base64
import builtins
import hashlib
import importlib.util
import json
import marshal
import os
import sys
import time
import types
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, parse_qsl
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'HongguoDesktop/.runtime/site-packages'))
from curl_cffi import requests

TAB = '/reading/bookapi/video_tab/multi_video_model/v1/'
PRIVATE = HERE/'private'
GROUPS = [
    ('a_single', ['7689903030619081790']),
    ('a_five', ['7689903030619081790','7689903116275174462','7689903075380694078','7689903137095699518','7689903130258983998']),
    ('cross_five', ['7689903116275174462','7689903082863348798','7689903130258983998','7694949024280874009','7694949018303990809']),
    ('b_single', ['7694949018303990809']),
]

def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')

def write(path, data, private=False):
    with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600 if private else 0o644), 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def protected_hashes():
    omitted = {'.runtime','.venv','__pycache__','node_modules','target','release','outputs','output','downloads','dist','experiments','.git'}
    result = {}
    for name in ('HongguoDesktop','HongguoCLI','HongguoPHP','analysis'):
        for parent, dirs, files in os.walk(ROOT/name):
            dirs[:] = [d for d in dirs if d not in omitted]
            for name2 in files:
                p = Path(parent)/name2
                if not p.is_symlink() and name2 != '.DS_Store':
                    result[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result

class VmDead(ValueError): pass

def main():
    if (HERE/'live-results.json').exists():
        raise RuntimeError('Use a new output directory for another run')
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    before = protected_hashes()
    write(HERE/'before-live-hashes.json', before)
    cfg = json.loads((HERE/'extracted/app/config.json').read_text(encoding='utf-8-sig'))
    device = json.loads((ROOT/'HongguoDesktop/config/devices.json').read_text(encoding='utf-8-sig'))[0]
    payload = (HERE/'extracted/app/hongguo.pyc').read_bytes()
    assert payload[:4] == importlib.util.MAGIC_NUMBER
    root = marshal.loads(payload[16:])
    codes = {c.co_name:c for c in root.co_consts if isinstance(c, types.CodeType)}
    report = {'started':now(), 'source_version':'1.0.0.77',
              'source_pyc_sha256':hashlib.sha256(payload).hexdigest(),
              'policy':'v77 signed=False; no signer code or signature headers; fixed existing device[0]',
              'transport':'curl_cffi chrome; TLS verified; redirects disabled',
              'scope':'8 requests / 2 rounds / 8 distinct VIDs from 2 series. No retry, fallback or media fetch.',
              'results':[], 'signer_calls':[], 'media_requests':0}
    def forbidden_signer(*args, **kwargs):
        report['signer_calls'].append('forbidden')
        raise AssertionError('Unsigned request must never call signer')
    def check(j):
        if not isinstance(j,dict) or j.get('code') != 0:
            raise VmDead('nonzero code or nonobject response')
    ns = {'__builtins__':{k:getattr(builtins,k) for k in ('dict','str','int','float','range','len','isinstance','getattr','Exception','RuntimeError','ValueError','TypeError','AttributeError')},
          'CFG':cfg, 'HOST':cfg['api_host'], '_pool':types.SimpleNamespace(current=lambda:device),
          'requests':types.SimpleNamespace(utils=types.SimpleNamespace(quote=quote)),
          'time':time, 'json':json, 'hashlib':hashlib,
          '_tls':types.SimpleNamespace(prio=False), '_src':{'down':True,'reason':'signer'},
          'SG':types.SimpleNamespace(throttle=types.SimpleNamespace(wait=lambda:None),check_response=check),
          '_VM_TAB':TAB, '_VM_ONE':'/novel/player/video_model/v1/', '_VM_PATHS':{TAB}, '_VmDead':VmDead,
          '_signer_warm':forbidden_signer, 'signer_reachable':forbidden_signer, 'sign':forbidden_signer,
          'is_cert_error':lambda e:False}
    for name in ('build_url','_req_headers','_api_once','_vm_tab_query','_vm_tab_pass','_vm_entry','_vm_dead','resolve_down'):
        ns[name] = types.FunctionType(codes[name], ns, name)
    assert ns['resolve_down']() is False
    active = None
    session = requests.Session(impersonate='chrome')
    def http_request(method,url,**kwargs):
        assert active is not None
        parts = urlsplit(url)
        assert method=='GET' and parts.scheme=='https' and parts.hostname==cfg['api_host'] and parts.path==TAB
        headers = kwargs['headers']
        forbidden = {'x-helios','x-medusa','x-gorgon','x-argus','x-ladon','x-khronos','x-neptune','x-soter','x-ss-stub','cookie','x-tt-token'}
        assert not forbidden.intersection(k.lower() for k in headers)
        assert kwargs['data'] is None
        q = dict(parse_qsl(parts.query))
        assert q['device_id']==device['query']['device_id'] and q['iid']==device['query']['iid']
        started = time.monotonic()
        response = session.request(method,url,**kwargs,allow_redirects=False,verify=True)
        try: result = response.json()
        except ValueError: result = None
        active.update(http_status=response.status_code,seconds=round(time.monotonic()-started,3),
                      header_names=sorted(headers),code=result.get('code') if isinstance(result,dict) else None,
                      response_bytes=len(response.content))
        write(PRIVATE/(active['id']+'.json'),{'url':url,'method':method,'headers':headers,
              'response_headers':dict(response.headers),'response':result if result is not None else response.text},private=True)
        assert response.status_code != 429, 'Stop on rate limit'
        return response
    ns['http_request'] = http_request
    def api(method,path,body=None,extra_query=None,signed=True,max_retries=2,timeout=25):
        assert path==TAB and signed is False
        active['signed']=signed
        active['declared_max_retries']=max_retries
        return ns['_api_once'](method,path,body,extra_query,signed,timeout,15,None)
    ns['api']=api
    try:
        for rnd in range(2):
            if rnd:
                print('Round gap: 20 seconds', flush=True)
                time.sleep(20)
            for name,original in GROUPS:
                time.sleep(2.5)
                vids = list(reversed(original)) if rnd else original
                active = {'id':f'{len(report["results"])+1:02d}-r{rnd+1}-{name}', 'vids':vids,
                          'started':now(), 'success':False}
                try:
                    out = {}
                    pending = ns['_vm_tab_pass'](vids,out,5)
                    summaries = {}
                    for vid in vids:
                        tracks,ttl = out[vid]
                        assert tracks
                        definitions = []
                        for track in tracks:
                            meta=track.get('video_meta') or {}
                            definitions.append(meta.get('definition'))
                            urls=[track.get(k) for k in ('main_url','backup_url') if track.get(k)]
                            assert urls and any(urlsplit(base64.b64decode(u).decode()).scheme in ('http','https') for u in urls)
                        summaries[vid]={'tracks':len(tracks),'definitions':sorted(set(definitions)), 'expire_time':ttl}
                    active.update(success=active.get('http_status')==200 and not pending and len(summaries)==len(vids),
                                  returned_vids=list(out),pending=pending,models=summaries)
                except Exception as exc:
                    active['error']=type(exc).__name__+': '+str(exc)[:180]
                active['finished']=now()
                report['results'].append(active)
                write(HERE/'live-results.json',report)
                print(json.dumps(active,ensure_ascii=False),flush=True)
                if active.get('http_status')==429:
                    raise RuntimeError('Stop on rate limit')
    finally:
        session.close()
        after = protected_hashes()
        report['preservation']={'checked_files':len(before),'changed':[k for k in before.keys()|after.keys() if before.get(k)!=after.get(k)]}
        report['finished']=now()
        report['successes']=sum(r['success'] for r in report['results'])
        report['valid_models']=sum(len(r.get('models',{})) for r in report['results'] if r['success'])
        write(HERE/'live-results.json',report)
        print('SUMMARY',json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
