"""Repeatability and media-only replay, kept outside all existing projects."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('studied_hongguo',ROOT/'source.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
(ROOT/'cache-media').mkdir(exist_ok=True)
m._HG_CACHE_DIR=str(ROOT/'cache-media')
r={'cases':[],'network':[],'scope':'Original live calls plus explicitly labelled saved-model replay; no source edits'}
sample=json.loads((ROOT/'results.json').read_text())['sample']
vid=sample['vid']
saved=json.loads((ROOT/'model.private.json').read_text())
s=m.Spider()
cfg={'device_id':s.device_id,'install_id':s.install_id}
original=m.requests.sessions.Session.request
original_model=m._video_model


def save():
    (ROOT/'media-results.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))


def req(self,method,url,**kw):
    parts=urlsplit(url)
    row={'host':parts.hostname,'path':parts.path,'method':method,'range':(kw.get('headers') or {}).get('Range')}
    try:
        response=original(self,method,url,**kw)
        row.update(status=response.status_code,bytes=len(response.content))
        if parts.path.endswith('multi_video_model/v1/'):
            data=response.json()
            row.update(code=data.get('code',data.get('Code')),message=data.get('message',data.get('Message')))
        return response
    finally:
        r['network'].append(row)
        save()


m.requests.sessions.Session.request=req


def case(name,fn,summary=lambda x:x):
    print('START '+name,flush=True)
    start=time.monotonic()
    try:
        value=fn()
        row={'case':name,'outcome':'returned','result':summary(value)}
    except Exception as e:
        value=None
        row={'case':name,'outcome':'error','error':str(e)[:1500]}
    row['seconds']=round(time.monotonic()-start,3)
    r['cases'].append(row)
    save()
    print(json.dumps(row,ensure_ascii=False),flush=True)
    return value


for i in range(6):
    case('original_model_repeat_'+str(i+1),lambda:m._video_model(vid,cfg),
         lambda v:{'tracks':len(m._video_list_from_model(v))})
    time.sleep(1.1)


def proxy_summary(v):
    return {'status':v[0],'bytes':len(v[2]),'error':v[2].decode(errors='replace')[:800] if v[0]!=200 else None}


proxy=case('original_localProxy',lambda:s.localProxy({'vid':vid,'q':'1080'}),proxy_summary)
if not proxy or proxy[0]!=200:
    # A replay at the model boundary tests media code, not live model reliability.
    m._video_model=lambda *_:saved
    proxy=case('saved_model_replay_localProxy',lambda:s.localProxy({'vid':vid,'q':'1080'}),proxy_summary)
    m._video_model=original_model
if proxy and proxy[0]==200:
    plain=proxy[2]
    output=ROOT/'sample.mp4'
    output.write_bytes(plain)
    r['sample_sha256']=hashlib.sha256(plain).hexdigest()
    case('ffprobe',lambda:subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)],capture_output=True,text=True,timeout=30),
         lambda p:{'exit_code':p.returncode,'data':json.loads(p.stdout) if p.stdout else {},'stderr':p.stderr[:1000]})
    case('ffmpeg_full_decode',lambda:subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-map','0:v?','-map','0:a?','-f','null','-'],capture_output=True,text=True,timeout=60),
         lambda p:{'exit_code':p.returncode,'stderr':p.stderr[:2000]})
    case('cache_hit',lambda:s.localProxy({'vid':vid,'q':'1080'}),
         lambda v:{**proxy_summary(v),'matches_full_file':v[2]==plain})
else:
    plain=None

# Always label this stream session as replay: isolate Range/crypto from model instability.
m._video_model=lambda *_:saved
player=case('saved_model_replay_playerContent',lambda:s.playerContent('红果超清','hg-episode-v1:1080:'+vid),
            lambda v:{'parse':v['parse'],'host':urlsplit(v['url']).hostname})
if player and player.get('parse')==0:
    url=player['url']
    head=case('saved_model_replay_HEAD',lambda:m.requests.head(url,timeout=40),
              lambda v:{'status':v.status_code,'length':v.headers.get('Content-Length'),'ranges':v.headers.get('Accept-Ranges')})
    if head is not None and head.status_code==200:
        for first,last in ((0,65535),(1048593,1114101)):
            case('saved_model_replay_Range_'+str(first),
                 lambda first=first,last=last:m.requests.get(url,headers={'Range':f'bytes={first}-{last}'},timeout=40),
                 lambda v,first=first,last=last:{'status':v.status_code,'bytes':len(v.content),'content_range':v.headers.get('Content-Range'),
                                               'matches_decrypted_file':v.content==plain[first:last+1] if plain else None})
        case('saved_model_replay_invalid_Range',lambda:m.requests.get(url,headers={'Range':'bytes=999999999-'},timeout=40),
             lambda v:{'status':v.status_code,'content_range':v.headers.get('Content-Range')})
server=m._STREAM_STATE.get('server')
if server:
    server.shutdown()
    server.server_close()
save()
print('DONE',flush=True)
