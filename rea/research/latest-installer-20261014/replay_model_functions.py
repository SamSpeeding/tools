"""Offline controlled replay of selected shipped functions, with fake APIs.

The module top level is never executed. No network or filesystem capability is
provided to the selected functions. This proves request construction only.
"""
import hashlib
import importlib.util
import json
import marshal
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGETS = {'1.0.0.72': Path('/Users/tt/Desktop/rea/analysis/extracted/app/hongguo.pyc'),
           '1.0.0.73': HERE/'extracted/app/hongguo.pyc'}


class Cache:
    def __init__(self): self.data = {}
    def cache_key(self, *parts): return tuple(parts)
    def cache_get(self, key): return self.data.get(key)
    def cache_set(self, key, value, ttl): self.data[key] = value


def replay(path, function, count, repeat=False):
    raw=path.read_bytes()
    assert raw[:4] == importlib.util.MAGIC_NUMBER
    root=marshal.loads(raw[16:])
    code=next(c for c in root.co_consts if isinstance(c, types.CodeType) and c.co_name==function)
    calls=[]
    def fake_api(method, url, **kwargs):
        body=kwargs['body']
        calls.append({'method':method,'path':url,'body':body})
        def model(vid):
            return {'video_model':json.dumps({'video_list':[{'main_url':'https://fixture.invalid/'+vid,
                'backup_url':'https://fixture.invalid/backup/'+vid,
                'video_meta':{'size':12345,'definition':'1080p'}}]})}
        if 'mixed_video_id_map' in body:
            return {'data':{str(v):model(str(v)) for v in body['mixed_video_id_map']['1']}}
        return {'data':model(body['video_id'])}
    globals_={'__builtins__':{'str':str,'set':set,'max':max,'min':min,'int':int,'range':range,'len':len},
              'SG':Cache(),'api':fake_api,'json':json}
    fn=types.FunctionType(code,globals_)
    vids=[str(100+i) for i in range(count)]
    kwargs={'force':False}
    if function=='get_video_tracks': kwargs['batch_size']=5
    result=fn(vids,**kwargs)
    first=len(calls)
    if repeat:
        assert fn(vids,**kwargs)==result
    assert set(result)==set(vids)
    return {'function':function,'vid_count':count,'first_call_requests':first,
            'repeat_additional_requests':len(calls)-first if repeat else None,
            'calls':calls,'result_keys':list(result),'source_sha256':hashlib.sha256(raw).hexdigest()}


results=[]
for version,path in TARGETS.items():
    for function in ('get_video_tracks','get_video_urls'):
        results.append({'version':version,**replay(path,function,6,True)})
out={'authority':'controlled-replay','network_requests':0,
     'scope':'Selected shipped function bytecode, in-memory cache and synthetic responses; no module top-level or Windows GUI execution.',
     'results':results}
(HERE/'evidence/model-functions-offline-replay.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
for r in results:
    print(r['version'],r['function'],'6 vids requests=',r['first_call_requests'],
          'cache repeat requests=',r['repeat_additional_requests'])
