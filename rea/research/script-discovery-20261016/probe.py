"""Finite desktop discovery experiment: same requests, pure local signatures.

Only the production _json_request signer boundary is replaced; query/body
construction, endpoint methods, parsing and pagination are the real AppAPI.
No Java/signing service, retries, fallback, device rotation or media download.
"""
from copy import deepcopy
from datetime import datetime
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT = ROOT/'HongguoDesktop'
PRIVATE = HERE/'private'
PRIVATE.mkdir(exist_ok=True, mode=0o700)
sys.dont_write_bytecode = True
sys.path[:0] = [str(PROJECT/'backend'), str(PROJECT/'.runtime/site-packages')]

def audit(event, args):
    if event in ('subprocess.Popen','os.system','os.posix_spawn','os.exec','os.spawn'):
        raise RuntimeError('This pure-script experiment forbids external processes')
    if event == 'ctypes.dlopen' and any(s in str(args) for s in ('metasec','HongguoDesktop/vendor','HongguoCLI/vendor')):
        raise RuntimeError('Original native signer libraries are forbidden')
sys.addaudithook(audit)

from app_api import AppAPI, RANK_PATH, CATEGORY_PATH, RANKS, GENRES
from hongguo_api import SEARCH_PATH, DETAIL_PATH, MODEL_PATH, SINGLE_MODEL_PATH, APIError
from script_signer import sign, gorgon

ALLOWED = {SEARCH_PATH,RANK_PATH,CATEGORY_PATH,DETAIL_PATH,SINGLE_MODEL_PATH}

def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def write(path, value, private=False):
    with os.fdopen(os.open(path, os.O_CREAT|os.O_TRUNC|os.O_WRONLY, 0o600 if private else 0o644),'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)

def safe_error(exc):
    return re.sub(r'https?://\S+', '[url]', str(exc))[:300]

def protected_hashes():
    excluded={'.runtime','.venv','__pycache__','node_modules','target','release',
              'outputs','output','downloads','dist','experiments','.git'}
    result={}
    for name in ('HongguoDesktop','HongguoCLI','HongguoPHP','analysis'):
        for parent,dirs,files in os.walk(ROOT/name):
            dirs[:]=[d for d in dirs if d not in excluded]
            for name2 in files:
                path=Path(parent)/name2
                if path.is_symlink() or name2=='.DS_Store': continue
                result[str(path.relative_to(ROOT))]=sha(path.read_bytes())
    return result


class Probe(AppAPI):
    active = None
    def _json_request(self, stage, method, url, headers, data, request_body=None):
        assert self.active is not None
        if stage == 'signer':
            final_body = self.body_to_sign
            self.signed_url = request_body['url']
            self.signed_body = final_body
            self.script_headers = sign(self.signed_url, final_body)
            self.active['signature_calls'] += 1
            return self.script_headers
        assert stage == 'api'
        parts = urlsplit(url)
        assert parts.scheme == 'https' and parts.hostname == self.host and parts.path in ALLOWED
        assert url == self.signed_url and data == self.signed_body
        q = dict(parse_qsl(parts.query))
        assert all(q[k] == self.device['query'][k] for k in ('device_id','iid','cdid'))
        assert 'x-neptune' not in headers and 'x-soter' not in headers
        assert 'cookie' not in headers and 'x-tt-token' not in headers
        if data is None:
            assert method == 'GET' and 'x-ss-stub' not in headers
        else:
            assert method == 'POST' and headers['x-ss-stub'] == hashlib.md5(data).hexdigest().upper()
        # The inherited single-model method locally regenerates H/M. Both calls
        # use the same pure module; neither can request a JAR or remote signer.
        unchanged = set(self.script_headers) - ({'x-helios','x-medusa'} if parts.path == SINGLE_MODEL_PATH else set())
        assert all(headers[k] == self.script_headers[k] for k in unchanged)
        record = {'request': {'method':method,'url':url,'headers':dict(headers),
                              'body':data.decode() if data else None},
                  'script_headers':self.script_headers}
        row = self.active
        row['remote_calls'] += 1
        row.update(started=now(),method=method,path=parts.path,host=parts.hostname,
                   device_sha256=sha(q['device_id'].encode()),iid_sha256=sha(q['iid'].encode()),
                   cdid_sha256=sha(q['cdid'].encode()),app_version=q['version_name'],
                   body_sha256=sha(data or b''),request_bytes=len(data or b''),
                   header_names=sorted(headers),signature_lengths={k:len(v) for k,v in self.script_headers.items()},
                   http_status=None,codes={},business_ok=False)
        start=time.monotonic()
        try:
            response = self.api_session.request(method,url,headers=headers,data=data,timeout=25,allow_redirects=False)
            row.update(http_status=response.status_code,seconds=round(time.monotonic()-start,3),response_bytes=len(response.content))
            try: result=response.json()
            except ValueError: result=None
            record.update(response_headers=dict(response.headers),response=result if result is not None else response.text)
            write(PRIVATE/(row['id']+'.json'),record,private=True)
            if not isinstance(result,dict):
                raise APIError('Non-object/empty JSON response')
            row['codes']={k:result[k] for k in ('code','Code','status_code','err_no','error_code') if k in result}
            row['base_resp']=result.get('BaseResp')
            row['message']=safe_error(result.get('message') or result.get('Message') or result.get('msg') or '')
            top_ok=all(v in (0,'0',None) for v in row['codes'].values())
            base=row['base_resp'] or {}
            row['business_ok']=response.status_code==200 and top_ok and (not isinstance(base,dict) or base.get('StatusCode') in (0,'0',None)) and not result.get('error')
            if response.status_code != 200: raise APIError(f'HTTP {response.status_code}',response=result)
            return result
        finally:
            row['finished']=now()

    def _req_headers(self, data=None):
        self.body_to_sign = data
        return super()._req_headers(data)


def validate(result, kind):
    if kind == 'filters':
        rows=result.get('rows')
        assert isinstance(rows,list) and rows
        assert all(isinstance(r,dict) for r in rows)
        return {'selector_rows':len(rows),'selector_types':[r.get('type') for r in rows],
                'selector_items':sum(len(r.get('items') or []) for r in rows)}
    if kind == 'detail':
        assert result.get('complete') and len(result.get('episodes',[])) > 0
        assert len({e['vid'] for e in result['episodes']}) == len(result['episodes'])
        return {'series_id':result['series_id'],'episodes':len(result['episodes']),
                'expected_episodes':result['meta']['episode_cnt'],'complete':result['complete'],
                'title':result['meta']['title']}
    if kind == 'model':
        parsed=AppAPI._parse_model('7689903030619081790',result['data'])
        assert parsed['tracks']
        return {'tracks':len(parsed['tracks']),'definitions':[t.get('definition') for t in parsed['tracks']]}
    items=result.get('items')
    assert isinstance(items,list)
    assert all(re.fullmatch(r'\d{10,24}',str(i['series_id'])) and i.get('title') for i in items)
    assert len({i['series_id'] for i in items}) == len(items)
    # A valid but empty response is distinguished from proven discovery data.
    return {'items':len(items),'series_ids':[i['series_id'] for i in items],
            'has_more':result.get('has_more'),'next_cursor_present':bool(result.get('next_cursor')),
            'warnings':result.get('warnings',[]),'nonempty':bool(items)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=('smoke','coverage','repeat'))
    args=parser.parse_args()
    path=HERE/(args.phase+'.json')
    assert not path.exists(), 'Do not overwrite evidence'
    before=protected_hashes()
    write(HERE/(args.phase+'-before-hashes.json'),before)
    vectors=json.loads((ROOT/'research/php-single-model-20261014/gorgon-vectors.json').read_text())
    for v in vectors['cases']:
        assert gorgon(v['query'],v['body'].encode(),v['ts'],v['nonce']) == v['expected']
    report={'started':now(),'phase':args.phase,'signing':'pure Python H/M v3 + Gorgon + reference timestamp Argus/Ladon',
            'offline_gorgon_vectors':len(vectors['cases']),'jar_java_original_so_used':False,
            'no_fallback_rotation_retry_media':True,'minimum_gap_seconds':2.5,
            'transport':'unchanged production curl_cffi Chrome','results':[]}
    write(path,report)
    device=json.loads((PROJECT/'config/devices.json').read_text(encoding='utf-8-sig'))[0]
    # This syntactically valid placeholder is never contacted: signer stage is
    # intercepted above and evaluated locally. No signer process is constructed.
    api=Probe(PROJECT/'config/config.json','http://127.0.0.1:1','',device=deepcopy(device),timeout=25)
    cache={}
    def run(label,kind,call):
        time.sleep(2.5)
        row={'id':args.phase+'-'+label,'kind':kind,'signature_calls':0,'remote_calls':0,'success':False}
        api.active=row
        try:
            result=call()
            row['parsed']=validate(result,kind)
            row['success']=row['business_ok'] and row['remote_calls']==1 and row['signature_calls']==1
            cache[label]=result
        except Exception as exc:
            row['error']=safe_error(exc)
        finally:
            api.active=None
            report['results'].append(row)
            write(path,report)
            print(json.dumps({k:row.get(k) for k in ('id','success','http_status','codes','message','parsed','error')},ensure_ascii=False),flush=True)
        if row.get('http_status')==429: raise RuntimeError('Rate limit: stop experiment')
        return cache.get(label)
    def page2(label,kind,result,fn):
        if result and result.get('has_more') and result.get('next_cursor'):
            second=run(label,kind,lambda:fn(result['next_cursor']))
            if second:
                row=report['results'][-1]
                prior={x['series_id'] for x in result['items']}
                row['pagination']={'prior_count':len(prior),
                    'new_series_ids':len({x['series_id'] for x in second['items']}-prior),
                    'cursor_advanced':second.get('next_cursor')!=result.get('next_cursor')}
                write(path,report)
    try:
        if args.phase in ('smoke','repeat'):
            run('search','search',lambda:api.search_page('重生'))
            run('rank','rank',lambda:api.rank_page('all','hot'))
            run('filters','filters',lambda:api.category(panel=True))
            run('category','category',lambda:api.category())
            run('latest','latest',lambda:api.category(latest=True))
            run('detail','detail',lambda:api.detail('7689863296106646590'))
            run('single-control','model',lambda:api._api_once('POST',SINGLE_MODEL_PATH,body={
                'biz_param':{'detail_page_version':0,'device_level':3,'disable_digg_stat':False,
                    'disable_video_relate_book':False,'need_all_video_definition':True,'need_mp4_align':False,
                    'use_os_player':False,'use_server_dns':False,'video_platform':1024},
                'video_id':'7689903030619081790'}))
        else:
            for word in ('重生','总裁'):
                first=run('search-'+word,'search',lambda:api.search_page(word))
                page2('search-'+word+'-p2','search',first,lambda c:api.search_page(word,c))
            for category in RANKS:
                for board in ('recommend','hot','new'):
                    label='rank-'+category+'-'+board
                    first=run(label,'rank',lambda:api.rank_page(category,board))
                    if category=='all' and board=='hot':
                        page2(label+'-p2','rank',first,lambda c:api.rank_page(category,board,c))
            for genre in GENRES:
                panel=run('filters-'+genre,'filters',lambda:api.category(genre,panel=True))
                first=run('category-'+genre,'category',lambda:api.category(genre))
                page2('category-'+genre+'-p2','category',first,lambda c:api.category(genre,cursor=c))
                first=run('latest-'+genre,'latest',lambda:api.category(genre,latest=True))
                if genre=='short_play':
                    page2('latest-'+genre+'-p2','latest',first,lambda c:api.category(genre,cursor=c,latest=True))
                if panel:
                    options=[(r['type'],i['selector_item_id']) for r in panel['rows']
                             if r.get('type') in ('category_dim_theme','category_dim_role')
                             for i in r.get('items',[]) if i.get('selector_item_id') and i.get('show_name') not in ('全部','不限')]
                    if options:
                        typ,ident=options[0]
                        run('selected-'+genre,'category-filtered',lambda:api.category(genre,{typ:[ident]}))
            run('detail-b','detail',lambda:api.detail('7694947161145871384'))
    finally:
        api.close()
        report['finished']=now()
        after=protected_hashes()
        changed=[k for k in sorted(before.keys()|after.keys()) if before.get(k)!=after.get(k)]
        report['preservation']={'checked_files':len(before),'changed':changed,'unchanged':not changed}
        write(path,report)
        print(json.dumps({'event':'finished','phase':args.phase,'requests':sum(r['remote_calls'] for r in report['results']),
                          'passed':sum(r['success'] for r in report['results']),'preservation':report['preservation']},ensure_ascii=False),flush=True)
        assert not changed


if __name__=='__main__': main()
