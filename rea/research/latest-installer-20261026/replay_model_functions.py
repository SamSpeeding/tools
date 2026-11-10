"""Offline replay of the shipped model functions. Never execute module top-level.

No real network, signer, user credentials, file cache, or target imports are
available to these functions. api() is a recorder with synthetic responses.
"""
import builtins
import hashlib
import importlib.util
import json
import marshal
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'latest-installer-20261016/extracted/app/hongguo.pyc'
NEW = HERE / 'extracted/app/hongguo.pyc'
TAB = '/reading/bookapi/video_tab/multi_video_model/v1/'
BATCH = '/novel/player/multi_video_model/v1/'
ONE = '/novel/player/video_model/v1/'
NOW = 1000000
VIDS = [str(100 + i) for i in range(6)]
BIZ = dict(detail_page_version=0, device_level=3, disable_digg_stat=False,
           disable_video_relate_book=False, need_all_video_definition=True,
           need_mp4_align=False, use_os_player=False, use_server_dns=False,
           video_platform=1024)


class VmDead(ValueError): pass
class ContentUnavailableError(Exception): pass
class RiskControlError(Exception): pass
class CertError(Exception): pass


class Cache:
    def __init__(self): self.data, self.ttls = {}, []
    def cache_key(self, *parts): return tuple(parts)
    def cache_get(self, key): return self.data.get(key)
    def cache_set(self, key, value, ttl):
        self.data[key] = value
        self.ttls.append(ttl)


def load(path, scenario):
    raw = path.read_bytes()
    assert raw[:4] == importlib.util.MAGIC_NUMBER
    root = marshal.loads(raw[16:])
    codes = {c.co_name:c for c in root.co_consts if isinstance(c, types.CodeType)}
    calls, messages, strikes = [], [], []
    allowed = ['str','set','max','min','int','float','range','len','dict','list',
               'RuntimeError','isinstance','type','Exception','ValueError','TypeError','AttributeError']
    namespace = {
        '__builtins__': {key:getattr(builtins,key) for key in allowed},
        'json':types.SimpleNamespace(loads=json.loads),
        'time':types.SimpleNamespace(time=lambda:NOW), 'SG':Cache(),
        '_VM_TAB':TAB, '_VM_BATCH':BATCH, '_VM_ONE':ONE,
        '_VM_BATCH_N':5, '_VM_TTL':18000, '_VM_EXPIRE_MARGIN':600,
        '_VM_BIZ':BIZ, '_VmDead':VmDead,
        'RiskControlError':RiskControlError, 'ContentUnavailableError':ContentUnavailableError,
        'is_cert_error':lambda e:isinstance(e,CertError),
        '_risk_reply':lambda e:True, '_conn_failure':lambda e:False,
        'scrub_urls':str, 'print':lambda *args:messages.append(' '.join(map(str,args))),
        '_source_strike':lambda *args:strikes.append(args),
    }
    defaults={'_vm_body':(None,None),'_vm_lookup':(5,),
              'get_video_tracks':(False,5),'get_video_urls':(False,)}
    selected={'get_video_tracks','get_video_urls','_vm_alive','_vm_dead','_vm_tab_query',
              '_vm_body','_vm_entry','_vm_ttl','_vm_kind','_vm_tab_pass','_vm_lookup'}
    for name in selected & codes.keys():
        namespace[name] = types.FunctionType(codes[name],namespace,name,defaults.get(name))

    def entry(vid, *, malformed=False, empty=False):
        model = {'video_list': [] if empty else [{
            'main_url':'https://fixture.invalid/'+vid,
            'backup_url':'https://fixture.invalid/backup/'+vid,
            'video_meta':{'size':12345,'definition':'1080p'}}]}
        return {'video_model':'{malformed' if malformed else json.dumps(model),
                'expire_time':NOW + (100 if scenario=='expired' else 3600)}

    def api(method,path,**kwargs):
        record={'method':method,'path':path,**kwargs};calls.append(record)
        if scenario=='signer_unavailable' and kwargs.get('signed',True):raise RuntimeError('synthetic signer unavailable')
        if path==TAB:
            ids=kwargs['extra_query']['video_id'].split(',')
            if scenario=='cert_error':raise CertError('synthetic certificate failure')
            if scenario in ('tab_fail','both_batch_fail','all_fail'):
                raise VmDead('synthetic tab failure')
            returned=ids[1:] if scenario=='tab_partial' else ids
            response={'code':0,'data':{'video_model_data':{
                v:entry(v,malformed=scenario=='tab_bad_json',empty=scenario=='tab_empty_tracks')
                for v in returned}}}
        elif path==BATCH:
            ids=kwargs['body']['mixed_video_id_map']['1']
            if scenario in ('both_batch_fail','all_fail'):
                raise VmDead('synthetic old batch failure')
            response={'code':0,'data':{v:entry(v) for v in ids}}
        else:
            assert path==ONE
            if scenario=='all_fail':raise VmDead('synthetic single failure')
            response={'code':0,'data':entry(kwargs['body']['video_id'])}
        # Model-level validation is the same shipped helper called by _api_once.
        if '_vm_dead' in namespace:
            reason=namespace['_vm_dead'](path,response)
            if reason:raise VmDead(reason)
        return response
    namespace['api']=api
    return namespace,calls,messages,strikes,hashlib.sha256(raw).hexdigest()


def run(path,scenario,function='get_video_tracks',repeat=False):
    ns,calls,messages,strikes,sha=load(path,scenario)
    result={};error=None;repeat_calls=None
    try:
        result=ns[function](VIDS)
        count=len(calls)
        if repeat:
            assert ns[function](VIDS)==result
            repeat_calls=len(calls)-count
    except Exception as exc:
        count=len(calls);error={'type':type(exc).__name__,'message':str(exc)}
    return {'scenario':scenario,'function':function,'source_sha256':sha,
            'first_call_count':count,'repeat_call_count':repeat_calls,
            'calls':calls,'result_vids':list(result),'cache_ttls':ns['SG'].ttls,
            'messages':messages,'source_strikes':strikes,'error':error}


def main():
    results=[]
    expected={
        'success':(2,[TAB,TAB],6),
        'tab_fail':(4,[TAB,TAB,BATCH,BATCH],6),
        'both_batch_fail':(9,[TAB,TAB,BATCH]+[ONE]*6,6),
        'tab_partial':(3,[TAB,TAB,BATCH],6),
        'tab_bad_json':(4,[TAB,TAB,BATCH,BATCH],6),
        'tab_empty_tracks':(2,[TAB,TAB],0),
        'all_fail':(4,[TAB,TAB,BATCH,ONE],0),
        'cert_error':(1,[TAB],0),
        'expired':(2,[TAB,TAB],6),
    }
    for path,version in ((OLD,'1.0.0.76'),(NEW,'1.0.0.77')):
        for scenario,(count,paths,returned) in expected.items():
            r=run(path,scenario,repeat=scenario=='success');r['version']=version
            assert r['first_call_count']==count,(scenario,r)
            assert [c['path'] for c in r['calls'][:count]]==paths,(scenario,r)
            assert len(r['result_vids'])==returned,(scenario,r)
            for c in r['calls']:
                assert c.get('signed',True)==(not(version=='1.0.0.77' and c['path']==TAB)),c
            if scenario=='success':assert r['repeat_call_count']==0 and r['cache_ttls']==[3000]*6
            if scenario=='expired':assert r['cache_ttls']==[]
            results.append(r)
        for function in ('get_video_tracks','get_video_urls'):
            r=run(path,'signer_unavailable',function);r['version']=version
            assert len(r['result_vids'])==(6 if version=='1.0.0.77' else 0),r
            assert r['first_call_count']==(2 if version=='1.0.0.77' else 4),r
            results.append(r)
        ns,calls,messages,strikes,sha=load(path,'success')
        ns['_vm_alive']({'video_id':VIDS[0]},None)
        assert len(calls)==1 and calls[0]['path']==TAB
        assert calls[0].get('signed',True)==(version=='1.0.0.76')
        results.append({'version':version,'scenario':'health_probe','calls':calls})
    doc={'authority':'controlled-replay','network_requests':0,'passed':True,'scenarios':len(results),
         'scope':'Actual selected shipped function bytecode, synthetic api/cache/clock. Does not execute module top-level or platform requests; retries and platform behavior not tested.',
         'results':results}
    (HERE/'evidence/model-functions-offline-replay.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2))
    for r in results:print(r['version'],r['scenario'],r.get('function'),len(r['calls']),'calls',len(r.get('result_vids',[])),'vids')
    print('PASS',len(results))

if __name__=='__main__':main()
