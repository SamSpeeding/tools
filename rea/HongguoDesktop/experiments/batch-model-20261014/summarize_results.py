"""Normalize derived summaries from the immutable private HTTP captures."""
import base64
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {'x-gorgon','x-argus','x-ladon','x-khronos','x-helios','x-medusa','x-neptune','x-soter'}
rows=[]
all_hashes=[]
for path in sorted(HERE.glob('[0-9][0-9]-*.json')):
    phase=json.loads(path.read_text())
    all_hashes.append(phase['source_hashes'])
    for row in phase['results']:
        raw_path=HERE/'private'/(phase['phase']+'-'+row['label']+'.json')
        if raw_path.exists():
            raw=raw_path.read_bytes()
            record=json.loads(raw)
            headers={k.lower():v for k,v in record['request']['headers'].items()}
            row['sign_headers']={k:len(v) for k,v in headers.items() if k in NAMES}
            row['request_header_names']=sorted(headers)
            row['capture_sha256']=hashlib.sha256(raw).hexdigest()
            data=record['response'].get('data') or {}
            entry=data.get(phase['vid'],data) if isinstance(data,dict) else {}
            model=entry.get('video_model') if isinstance(entry,dict) else None
            if isinstance(model,str):
                model=json.loads(model)
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
            assert row['usable']==bool(definitions)
            row['definitions']=definitions
        rows.append({'phase':phase['phase'],**row})
    phase['summary_normalization']='2026-10-14: derived header inventories include all eight recognized fields; quality labels read nested video_meta. Immutable raw captures and original stdout logs preserved; no success result changed.'
    path.write_text(json.dumps(phase,ensure_ascii=False,indent=2)+'\n')
assert all(x==all_hashes[0] for x in all_hashes)
for file,digest in all_hashes[0].items():
    assert hashlib.sha256(Path(file).read_bytes()).hexdigest()==digest,file
summary={'requests':len(rows),'usable':sum(r.get('usable',False) for r in rows),
         'by_phase':{},'source_hashes_equal_across_phases_and_current':True,'rows':rows}
for r in rows:
    stat=summary['by_phase'].setdefault(r['phase'],{'requests':0,'usable':0})
    stat['requests']+=1;stat['usable']+=bool(r.get('usable'))
(HERE/'results-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
lines=['# 实验逐请求索引','','仅成功取得目标 VID 的视频轨道和 HTTP 下载地址才记作成功；没有下载媒体。','','| 阶段 | 请求 | 设备摘要 | 结果 |','|---|---|---|---|']
for r in rows:
    result='成功（5 档）' if r.get('usable') else str(r.get('code',r.get('error')))
    lines.append(f"| {r['phase']} | `{r['label']}` | `{r.get('device_sha256','')[:10]}` | {result} |")
(HERE/'CASES.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False,indent=2))
