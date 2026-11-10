"""Fresh plugin instances, original media paths, no injected model or signatures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('studied_hongguo',ROOT/'source.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
(ROOT/'cache-native').mkdir(exist_ok=True)
m._HG_CACHE_DIR=str(ROOT/'cache-native')
vid=json.loads((ROOT/'results.json').read_text())['sample']['vid']
expected=(ROOT/'sample.mp4').read_bytes()
report={'cases':[],'model_requests':[],'scope':'Fresh original Spider per playback path, no model injection'}
original=m.requests.sessions.Session.request


def save():
    (ROOT/'native-path-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


def request(self,method,url,**kw):
    r=original(self,method,url,**kw)
    if urlsplit(url).path.endswith('multi_video_model/v1/'):
        data=r.json()
        report['model_requests'].append({'status':r.status_code,'code':data.get('code',data.get('Code'))})
        save()
    return r


m.requests.sessions.Session.request=request


def case(name,fn,summary):
    print('START '+name,flush=True)
    start=time.monotonic()
    try:
        value=fn()
        row={'case':name,'result':summary(value)}
    except Exception as exc:
        value=None
        row={'case':name,'error':str(exc)[:1200]}
    row['seconds']=round(time.monotonic()-start,3)
    report['cases'].append(row)
    save()
    print(json.dumps(row,ensure_ascii=False),flush=True)
    return value


s=m.Spider()
case('fresh_original_localProxy',lambda:s.localProxy({'vid':vid,'q':'1080'}),
     lambda x:{'status':x[0],'bytes':len(x[2]),'matches_decoded_sample':x[2]==expected,
               'error':x[2].decode(errors='replace')[:600] if x[0]!=200 else None})
s2=m.Spider()
player=s2.playerContent('红果超清','hg-episode-v1:1080:'+vid)
head=case('fresh_original_stream_HEAD',lambda:m.requests.head(player['url'],timeout=45),
          lambda x:{'status':x.status_code,'length':x.headers.get('Content-Length'),'ranges':x.headers.get('Accept-Ranges')})
if head is not None and head.status_code==200:
    case('original_stream_mid_Range',lambda:m.requests.get(player['url'],headers={'Range':'bytes=1048593-1114101'},timeout=45),
         lambda x:{'status':x.status_code,'bytes':len(x.content),'matches_decoded_sample':x.content==expected[1048593:1114102]})
    case('original_stream_full_GET',lambda:m.requests.get(player['url'],timeout=60),
         lambda x:{'status':x.status_code,'bytes':len(x.content),'sha256':hashlib.sha256(x.content).hexdigest(),
                   'matches_decoded_sample':x.content==expected})
server=m._STREAM_STATE.get('server')
if server:
    server.shutdown()
    server.server_close()
save()
print('DONE',flush=True)
