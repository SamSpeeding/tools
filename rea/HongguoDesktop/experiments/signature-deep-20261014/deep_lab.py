"""Research-only extension: validate every requested VID, never fall back."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'batch-model-20261014'))
import lab as base
from lab import *
from hongguo_api import DETAIL_PATH

HERE = Path(__file__).resolve().parent
PRIVATE = HERE/'private'
PRIVATE.mkdir(mode=0o700, exist_ok=True)
base.HERE, base.PRIVATE = HERE, PRIVATE
os.environ['HG_DATA_DIR'] = str(PRIVATE)
plugin._HG_CACHE_DIR = str(PRIVATE/'unused-media-cache')
ORIGINAL_IDS = {'device_id':str(ORIGINAL['query']['device_id']),
                'install_id':str(ORIGINAL['query']['iid'])}


def inspect_models(raw, vids, single=False):
    data=raw.get('data') or {}
    result={}
    for vid in vids:
        entry=data if single else data.get(vid,{})
        model=entry.get('video_model') if isinstance(entry,dict) else None
        if isinstance(model,str):
            try:model=json.loads(model)
            except (ValueError,TypeError):model=None
        tracks=model.get('video_list',{}) if isinstance(model,dict) else {}
        tracks=list(tracks.values()) if isinstance(tracks,dict) else tracks
        definitions=[]
        for t in tracks or []:
            if not isinstance(t,dict): continue
            url=t.get('main_url') or ''
            if not url.startswith(('http://','https://')):
                try:url=base64.b64decode(url).decode()
                except Exception:url=''
            if url.startswith(('http://','https://')):
                definitions.append(t.get('definition') or (t.get('video_meta') or {}).get('definition'))
        result[vid]={'usable':bool(definitions),'definitions':definitions}
    return {'models':result,'usable_count':sum(x['usable'] for x in result.values()),
            'all_usable':bool(vids) and all(x['usable'] for x in result.values()),
            'returned_data_keys':list(data) if isinstance(data,dict) else []}


class DeepLab(base.Lab):
    def __init__(self,phase):
        super().__init__(phase)
        self.signing=''
        self.material_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [ROOT/'vendor/sign/unidbg-sign.jar', *sorted((ROOT/'vendor/capture/fq_oversea').glob('*'))] if p.is_file()}
        self.started_at=now()

    def save(self):
        assert self.before==protected_hashes(), 'Protected application/source changed'
        for path,digest in self.material_hashes.items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
        self.path.write_text(json.dumps({'phase':self.phase,'started_at':self.started_at,'updated_at':now(),
            'scope':'Isolated official detail/model requests only; no fallback, media download, registration or production writes',
            'original_identity_sha256':hashlib.sha256(ORIGINAL_IDS['device_id'].encode()).hexdigest(),
            'source_hashes':self.before,'signer_material_hashes':self.material_hashes,
            'protected_files_unchanged':True,'results':self.results},ensure_ascii=False,indent=2)+'\n')

    def send(self,method,url,headers,data,transport='requests',session=None,**unused):
        parts=urlsplit(url)
        assert method.upper()=='POST' and parts.scheme=='https' and parts.hostname in HOSTS
        assert parts.path in {MODEL_PATH,SINGLE_MODEL_PATH,DETAIL_PATH}
        assert self.label and self.count<60
        self.count+=1
        data=data if isinstance(data,bytes) else data.encode()
        body=json.loads(data)
        query=dict(parse_qsl(parts.query))
        headers={k.lower():str(v) for k,v in headers.items()}
        stub=hashlib.md5(data).hexdigest().upper()
        assert headers.get('x-ss-stub','').upper()==stub
        assert query['device_id']==ORIGINAL_IDS['device_id'] and query['iid']==ORIGINAL_IDS['install_id']
        start=time.monotonic()
        response=(session or requests).request(method,url,headers=headers,data=data,timeout=25,allow_redirects=False)
        raw=response.json()
        record={'request':{'method':method,'url':url,'headers':headers,'body':data.decode(),
                 'wire_headers':dict(response.request.headers) if getattr(response,'request',None) else headers},
                'response_headers':dict(response.headers),'response':raw}
        write_private(self.phase+'-'+self.label+'.json',record)
        row={'label':self.label,'time':now(),'path':parts.path,'host':parts.hostname,
             'signing':self.signing,'transport':transport,'http_status':response.status_code,
             'code':raw.get('code',raw.get('Code')),'message':raw.get('message',raw.get('Message',raw.get('msg'))),
             'seconds':round(time.monotonic()-start,3),'body_md5':stub,
             'device_sha256':hashlib.sha256(query['device_id'].encode()).hexdigest(),
             'iid_sha256':hashlib.sha256(query['iid'].encode()).hexdigest(),
             'signature_lengths':{k:len(v) for k,v in headers.items() if k in
                 {'x-helios','x-medusa','x-khronos','x-gorgon','x-argus','x-ladon','x-neptune','x-soter'}}}
        if parts.path==DETAIL_PATH:
            entry=(raw.get('data') or {}).get(body['series_id'],{}).get('video_data',{})
            row.update(series_id=body['series_id'],episode_count=len(entry.get('video_list') or []))
        else:
            vids=([str(body['video_id'])] if parts.path==SINGLE_MODEL_PATH else
                  [str(v) for vs in body['mixed_video_id_map'].values() for v in vs])
            row.update(requested_vids=vids,requested_count=len(vids),**inspect_models(raw,vids,parts.path==SINGLE_MODEL_PATH))
        self.results.append(row)
        self.save()
        print(json.dumps(row,ensure_ascii=False),flush=True)
        return response

    def model_template(self,vids,api):
        template=self.template('ours',ORIGINAL_IDS,api)
        template['body']=json.dumps({'biz_param':BIZ,'mixed_video_id_map':{'1':list(vids)}},
                                    ensure_ascii=False,separators=(',',':')).encode()
        return template

    def model(self,label,vids,api,family='hybrid',transport='requests'):
        self.signing=family
        def run():
            template=self.model_template(vids,api)
            if family=='hybrid':
                return self.hybrid_send(template,'jar',['x-helios','x-medusa'],api)
            return self.sign_and_send(template,family,api,transport)
        self.case(label,run)

    def detail(self,label,sid,api):
        self.signing='jar'
        box={}
        self.case(label,lambda:box.update(api.detail(sid)))
        assert box.get('complete') and len(box.get('episodes',[]))>=5
        result={'series_id':sid,'title':box['meta']['title'],
                'episodes':[{'index':ep['index'],'vid':ep['vid']} for ep in box['episodes']]}
        return result
