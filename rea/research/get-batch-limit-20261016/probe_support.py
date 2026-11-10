"""Finite live comparison, isolated from production code/config/output.

Same fixed production device, App profile, transport, base URL and actual signer.
No automatic retries/fallback, device rotation/registration or media downloads.
New GET uses the recovered v1.0.0.76 query; old POST uses production type key 1.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PROJECT=ROOT/'HongguoDesktop'
PRIVATE=HERE/'private'
PRIVATE.mkdir(mode=0o700,exist_ok=True)
os.environ['HG_DATA_DIR']=str(PRIVATE)
sys.dont_write_bytecode=True
sys.path[:0]=[str(PROJECT/'backend'),str(PROJECT/'.runtime/site-packages')]
from hongguo_api import HongguoAPI
from hongguo_signer import LocalSigner
from hongguo_hm import model_headers

TAB='/reading/bookapi/video_tab/multi_video_model/v1/'
OLD='/novel/player/multi_video_model/v1/'
BIZ={'detail_page_version':0,'device_level':3,'disable_digg_stat':False,
     'disable_video_relate_book':False,'need_all_video_definition':True,
     'need_mp4_align':False,'use_os_player':False,'use_server_dns':False,'video_platform':1024}
GROUPS=[
 ('a_single',['7689903030619081790']),
 ('a_five',['7689903030619081790','7689903116275174462','7689903075380694078','7689903137095699518','7689903130258983998']),
 ('cross_five',['7689903116275174462','7689903082863348798','7689903130258983998','7694949024280874009','7694949018303990809']),
 ('b_single',['7694949018303990809']),
]


def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def sha(data):return hashlib.sha256(data).hexdigest()
def write(path,value,private=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600 if private else 0o644),'w') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)
def safe_error(exc):return re.sub(r'https?://\S+','[url]',str(exc))[:300]


def protected_hashes():
    excluded={'.runtime','.venv','__pycache__','node_modules','target','release',
              'outputs','output','downloads','dist','experiments','.git'}
    result={}
    for name in ('HongguoDesktop','HongguoCLI','HongguoPHP','analysis'):
        for parent,dirs,files in os.walk(ROOT/name):
            dirs[:]=[d for d in dirs if d not in excluded]
            for name2 in files:
                path=Path(parent)/name2
                if path.is_symlink() or name2=='.DS_Store':continue
                result[str(path.relative_to(ROOT))]=sha(path.read_bytes())
    return result


class Probe(HongguoAPI):
    def _json_request(self,stage,method,url,headers,data,request_body=None):
        if stage=='signer':
            result=super()._json_request(stage,method,url,headers,data,request_body)
            self.jar={k.lower():str(v) for k,v in result.items()}
            self.signed_url=request_body['url']
            return result
        assert stage=='api' and self.active
        parts=urlsplit(url)
        assert parts.scheme=='https' and parts.hostname==self.host and parts.path in (TAB,OLD)
        assert url==self.signed_url
        query=dict(parse_qsl(parts.query))
        assert query['device_id']==self.device['query']['device_id']
        assert query['iid']==self.device['query']['iid']
        headers=dict(headers)
        if self.active['policy']=='jar_only':
            # Undo the production old-endpoint H/M overlay in memory for this control.
            headers.update(self.jar)
        elif parts.path==TAB:
            # Production does not yet route this endpoint through model_headers.
            # Apply exactly the existing model signature policy inside this harness.
            headers.update(model_headers(url,data,headers))
        assert all(headers[k]==v for k,v in self.jar.items() if k not in ('x-helios','x-medusa'))
        if self.active['policy']=='current':assert all(headers[k]!=self.jar[k] for k in ('x-helios','x-medusa'))
        else:assert all(headers[k]==v for k,v in self.jar.items())
        if data is None:assert method=='GET' and 'x-ss-stub' not in headers
        else:assert method=='POST' and headers['x-ss-stub']==hashlib.md5(data).hexdigest().upper()
        envelope=base64.b64decode(headers['x-medusa'])
        version=int.from_bytes(envelope[:4],'little') ^ int(headers['x-khronos'])
        if self.active['policy']=='current':assert version==3
        row=self.active
        row.update(started=now(),host=parts.hostname,path=parts.path,method=method,
                   device_sha256=sha(query['device_id'].encode()),iid_sha256=sha(query['iid'].encode()),
                   app_version=query.get('version_name'),query_sha256=sha(parts.query.encode()),
                   body_md5=hashlib.md5(data).hexdigest() if data is not None else None,
                   medusa_version=version,only_hm_replaced=row['policy']=='current',
                   signed_url_and_body_checked=True,returned_vids=[],models={},success=False)
        started=time.monotonic()
        try:
            response=self.api_session.request(method,url,headers=headers,data=data,timeout=25,allow_redirects=False)
            row.update(http_status=response.status_code,seconds=round(time.monotonic()-started,3),response_bytes=len(response.content))
            try:result=response.json()
            except ValueError:result=None
            write(PRIVATE/(row['id']+'.json'),{
                'request':{'url':url,'method':method,'headers':headers,'body':data.decode() if data else None},
                'response_headers':dict(response.headers),'response':result if result is not None else response.text,
            },private=True)
            if not isinstance(result,dict):raise RuntimeError('Non-object/empty JSON response')
            row['codes']={k:result[k] for k in ('code','Code','status_code','error_code','err_no') if k in result}
            row['base_resp']=result.get('BaseResp')
            row['message']=safe_error(result.get('message') or result.get('Message') or result.get('msg') or '')
            container=result.get('data')
            if isinstance(container,dict) and parts.path==TAB:container=container.get('video_model_data')
            if not isinstance(container,dict):container={}
            row['returned_vids']=list(container)
            for vid in row['vids']:
                try:
                    item=container.get(vid)
                    if not isinstance(item,dict):raise ValueError('missing requested VID')
                    parsed=HongguoAPI._parse_model(vid,item)
                    definitions=sorted({t.get('definition') for t in parsed['tracks'] if t.get('definition')})
                    valid=all(any(isinstance(t.get(k),str) and urlsplit(t[k]).scheme in ('http','https') for k in ('main_url','backup_url')) for t in parsed['tracks'])
                    row['models'][vid]={'tracks':len(parsed['tracks']),'definitions':definitions,'usable_urls':valid,'status':parsed['model'].get('status'),'expire_time':item.get('expire_time')}
                except Exception as exc:row['models'][vid]={'error':safe_error(exc)}
            top_ok=all(v in (0,'0',None) for v in row['codes'].values())
            base=row['base_resp'] or {}
            top_ok=top_ok and (not isinstance(base,dict) or base.get('StatusCode') in (0,'0',None))
            row['success']=response.status_code==200 and top_ok and all(x.get('tracks',0)>0 and x.get('usable_urls') for x in row['models'].values())
            return result
        finally:row['finished']=now()


def main():
    if (HERE/'results.json').exists():raise RuntimeError('Do not overwrite a completed run')
    before=protected_hashes();write(HERE/'before-hashes.json',before)
    vendor=HERE/'runtime/vendor'
    for rel in ('sign/unidbg-sign.jar','capture/fq_oversea/libmetasec_ml.so','capture/fq_oversea/libc++_shared.so','capture/fq_oversea/ms_16777218.bin'):
        source=PROJECT/'vendor'/rel;dest=vendor/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest);assert sha(source.read_bytes())==sha(dest.read_bytes())
    report={'started':now(),'scope':'32 direct model requests, 3 rounds, 8 distinct existing episode IDs from 2 series',
            'signature_policy':'current = unchanged JAR other headers plus production local H/M; jar_only = unchanged original JAR',
            'transport':'production curl_cffi chrome; same default host; fixed devices.json[0]',
            'no_retries_or_fallback':True,'media_requests':0,'round_gap_seconds':45,'per_request_gap_seconds':2.5,'results':[]}
    write(HERE/'results.json',report)
    device=json.loads((PROJECT/'config/devices.json').read_text(encoding='utf-8-sig'))[0]
    try:
        with LocalSigner(vendor) as signer:
            api=Probe(PROJECT/'config/config.json',signer.url,signer.token,timeout=25,device=deepcopy(device))
            try:
                for round_no in range(3):
                    print(json.dumps({'event':'round_start','round':round_no+1,'time':now()}),flush=True)
                    jobs=[]
                    for index,(name,vids) in enumerate(GROUPS):
                        ends=(TAB,OLD) if (index+round_no)%2==0 else (OLD,TAB)
                        for endpoint in ends:jobs.append(('current',name,list(reversed(vids)) if round_no==1 else vids,endpoint))
                    if round_no in (0,2):
                        for name,vids in (GROUPS[0],GROUPS[2]):
                            for endpoint in ((OLD,TAB) if round_no==0 else (TAB,OLD)):
                                jobs.append(('jar_only',name,vids,endpoint))
                    for policy,name,vids,endpoint in jobs:
                        time.sleep(2.5)
                        ident=f'{len(report["results"])+1:02d}-r{round_no+1}-{policy}-{name}-'+('get' if endpoint==TAB else 'post')
                        row={'id':ident,'round':round_no+1,'policy':policy,'group':name,'vids':vids,'endpoint':'new_get' if endpoint==TAB else 'old_post'}
                        api.active=row
                        try:
                            if endpoint==TAB:
                                query={'video_id':','.join(vids),'video_platform':'1024','need_all_video_definition':'true','device_level':'3','detail_page_version':'0'}
                                api._api_once('GET',TAB,extra_query=query)
                            else:api._api_once('POST',OLD,{'biz_param':BIZ,'mixed_video_id_map':{'1':vids}})
                        except Exception as exc:row['error']=safe_error(exc);row.setdefault('success',False)
                        finally:api.active=None
                        report['results'].append(row);write(HERE/'results.json',report)
                        print(json.dumps({k:row.get(k) for k in ('id','success','http_status','codes','returned_vids','seconds','error')},ensure_ascii=False),flush=True)
                        if row.get('http_status')==429:raise RuntimeError('Rate limit observed; stop the finite test')
                    if round_no<2:
                        print(json.dumps({'event':'round_gap','seconds':45,'time':now()}),flush=True)
                        time.sleep(45)
                signer.mark_success()
            finally:api.close()
    finally:
        report['finished']=now();after=protected_hashes()
        changed=[k for k in sorted(before.keys()|after.keys()) if before.get(k)!=after.get(k)]
        report['preservation']={'checked_files':len(before),'changed':changed,'unchanged':not changed}
        report['summary']={}
        for policy in ('current','jar_only'):
            for endpoint in ('new_get','old_post'):
                rows=[r for r in report['results'] if r['policy']==policy and r['endpoint']==endpoint]
                report['summary'][policy+'/'+endpoint]={'total':len(rows),'success':sum(r.get('success',False) for r in rows),'requested_models':sum(len(r['vids']) for r in rows),'valid_models':sum(sum(bool(x.get('tracks',0)>0 and x.get('usable_urls')) for x in r.get('models',{}).values()) for r in rows)}
        write(HERE/'results.json',report)
        print(json.dumps({'event':'finished','summary':report['summary'],'preservation':report['preservation']},ensure_ascii=False),flush=True)
        assert not changed,changed


if __name__=='__main__':main()
