"""Summarize verified observations without making a long-term success claim."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
catalog=json.loads((HERE/'episode-catalog.json').read_text())
lookup={ep['vid']:{'series':group,'index':ep['index']} for group,series in catalog.items() for ep in series['episodes']}
rows=[];phases={};sources=None;signers=None
for name,expected in [('07-cross-episode-multivid',20),('08-helios-field-isolation',7),
                      ('09-exact-helios-counterfactual',5),('10-persisted-repeat-window',9)]:
    data=json.loads((HERE/(name+'.json')).read_text())
    assert len(data['results'])==expected,(name,len(data['results']))
    if sources is None:sources=data['source_hashes'];signers=data['signer_material_hashes']
    assert sources==data['source_hashes'] and signers==data['signer_material_hashes']
    phases[name]={'requests':len(data['results']),'first':data['results'][0]['time'],'last':data['results'][-1]['time']}
    for row in data['results']:
        raw=HERE/'private'/(name+'-'+row['label']+'.json')
        assert raw.exists()
        record=json.loads(raw.read_text())
        body=record['request']['body'].encode()
        assert hashlib.md5(body).hexdigest().upper()==row['body_md5']
        assert row['http_status']==200
        rows.append({'phase':name,'capture_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),**row})
for path,digest in {**sources,**signers}.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
models=[r for r in rows if 'requested_count' in r]
batch=[r for r in models if '/multi_video_model/' in r['path']]
single=[r for r in models if '/player/video_model/' in r['path']]
vids=sorted({v for r in models for v in r['requested_vids']})
positive=lambda r:(r['phase']=='07-cross-episode-multivid' and r['signing'] in ('hybrid','python')) or (r['phase']=='08-helios-field-isolation' and r['label'].startswith('correct_hm_')) or (r['phase']=='09-exact-helios-counterfactual' and r['label'].startswith('original_valid')) or (r['phase']=='10-persisted-repeat-window' and r['signing'] in ('hybrid','python'))
controls=[r for r in batch if positive(r)]
assert all(r['all_usable'] for r in controls)
first=datetime.fromisoformat(models[0]['time']);last=datetime.fromisoformat(models[-1]['time'])
out={'phases':phases,'total_http_requests':len(rows),'detail_requests':len(rows)-len(models),
     'batch_requests':len(batch),'single_controls':len(single),
     'batch_all_usable':sum(r['all_usable'] for r in batch),
     'batch_failures':sum(not r['all_usable'] for r in batch),
     'unperturbed_candidate_checks':len(controls),
     'unperturbed_candidate_successes':sum(r['all_usable'] for r in controls),
     'unique_vid_count':len(vids),'episodes_tested':{group:sorted({lookup[v]['index'] for v in vids if lookup[v]['series']==group}) for group in catalog},
     'max_batch_size':max(r['requested_count'] for r in batch),
     'same_original_identity':len({(r['device_sha256'],r['iid_sha256']) for r in rows})==1,
     'observation_seconds':round((last-first).total_seconds(),1),
     'protected_files_unchanged':True,'rows':rows}
(HERE/'results-summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
lines=['# 本轮逐请求记录','','结果是模型及每个目标 VID 的 URL 完整性；未请求 CDN，不表示已下载或播放。','','| 阶段 | 请求 | VID 数 | 完整返回数 | 业务码 |','|---|---|---:|---:|---:|']
for r in rows:
    lines.append(f"| {r['phase'][:2]} | `{r['label']}` | {r.get('requested_count','详情')} | {r.get('usable_count','—')} | {r['code']} |")
(HERE/'CASES.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='rows'},ensure_ascii=False,indent=2))
