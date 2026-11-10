"""Revalidate the already saved live responses, without making any requests.

The original capture harness incorrectly treated already-plain URLs as base64.
Keep that raw run and its error intact; this separate verification accepts both
plain HTTP(S) and base64 URL forms and calls the shipped _vm_entry parser again.
"""
import base64
import builtins
import hashlib
import importlib.util
import json
import marshal
import types
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

HERE=Path(__file__).resolve().parent

def main():
    captured=json.loads((HERE/'live-results.json').read_text())
    raw=(HERE/'extracted/app/hongguo.pyc').read_bytes()
    assert raw[:4]==importlib.util.MAGIC_NUMBER
    codes={c.co_name:c for c in marshal.loads(raw[16:]).co_consts if isinstance(c,types.CodeType)}
    ns={'__builtins__':builtins.__dict__, 'json':json, '_VmDead':ValueError}
    entry=types.FunctionType(codes['_vm_entry'],ns)
    resolve=types.FunctionType(codes['resolve_down'],ns)
    observations=[]
    for down,reason,expected in ((False,'signer',False),(True,'signer',False),(True,'risk',True),(True,'empty',True),(True,'network',True)):
        ns['_src']={'down':down,'reason':reason}
        assert resolve() is expected
        observations.append({'source_down':down,'reason':reason,'resolve_down':resolve()})
    forbidden={'x-helios','x-medusa','x-gorgon','x-argus','x-ladon','x-khronos','x-neptune','x-soter','x-ss-stub','cookie','x-tt-token'}
    rows=[]
    devices=set()
    for original in captured['results']:
        path=HERE/'private'/(original['id']+'.json')
        record=json.loads(path.read_text());response=record['response']
        assert original['http_status']==200 and original['code']==0 and response['code']==0
        assert original['signed'] is False
        assert not forbidden.intersection(k.lower() for k in record['headers'])
        assert record['method']=='GET'
        parts=urlsplit(record['url']);query=dict(parse_qsl(parts.query))
        assert parts.hostname=='api5-normal-sinfonlinec.fqnovel.com'
        assert parts.path=='/reading/bookapi/video_tab/multi_video_model/v1/'
        assert query['video_id'].split(',')==original['vids']
        devices.add((query['device_id'],query['iid'],query['cdid']))
        vmd=response['data']['video_model_data']
        assert set(original['vids'])<=set(vmd)
        models={}
        for vid in original['vids']:
            tracks,expire_time=entry(vmd[vid]);assert tracks
            formats=[]
            for t in tracks:
                urls=[t.get(k) for k in ('main_url','backup_url') if t.get(k)]
                assert urls
                for u in urls:
                    plain=u.startswith(('http://','https://'))
                    decoded=u if plain else base64.b64decode(u,validate=True).decode()
                    assert urlsplit(decoded).scheme in ('http','https') and urlsplit(decoded).hostname
                    formats.append('plain' if plain else 'base64')
            models[vid]={'tracks':len(tracks),'definitions':sorted({t['video_meta']['definition'] for t in tracks}),
                         'url_formats':sorted(set(formats)),'expire_time':expire_time}
        rows.append({'id':original['id'],'success':True,'http_status':200,'code':0,
                     'requested_vids':original['vids'],'returned_vids':list(vmd),'models':models,
                     'seconds':original['seconds'],'raw_capture_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    assert len(devices)==1 and len(rows)==8 and not captured['signer_calls']
    assert captured['preservation']['changed']==[]
    report={'authority':'external-service + offline validation of captured responses',
            'capture_window':{'started':captured['started'],'finished':captured['finished']},
            'note':'Raw live-results.json preserves the original post-response URL-normalizer error. Responses were already successful; this separate validation fixes plain/base64 URL handling without repeating network requests.',
            'additional_network_requests':0,'requests':len(rows),'successes':len(rows),
            'valid_models':sum(len(r['models']) for r in rows),
            'distinct_vids':len({v for r in rows for v in r['requested_vids']}),
            'device_profiles':len(devices),'signer_calls':0,'media_requests':0,
            'resolve_down_replay':observations,'preservation':captured['preservation'],'results':rows}
    (HERE/'live-verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
