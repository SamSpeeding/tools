"""Summarize recorded responses only; no new network requests."""
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
import json

HERE=Path(__file__).resolve().parent
data=json.loads((HERE/'results.json').read_text())
assert data.get('finished'),'The finite run must finish before summarizing'
rows=data['results']
summary={
    'started':data['started'],'finished':data['finished'],
    'elapsed_seconds':(datetime.fromisoformat(data['finished'])-datetime.fromisoformat(data['started'])).total_seconds(),
    'network_model_requests':len(rows),'media_requests':0,
    'unique_vids':sorted({vid for row in rows for vid in row['vids']}),
    'device_identity_count':len({r.get('device_sha256') for r in rows}),
    'install_identity_count':len({r.get('iid_sha256') for r in rows}),
    'hosts':sorted({r.get('host','not-sent') for r in rows}),
    'preservation':data['preservation'],'groups':[],
}
for policy in ('current','jar_only'):
    for endpoint in ('new_get','old_post'):
        items=[r for r in rows if r['policy']==policy and r['endpoint']==endpoint]
        latencies=[r['seconds'] for r in items if 'seconds' in r]
        codes=Counter(str(r.get('codes',{})) for r in items)
        definitions=Counter(','.join(v.get('definitions',[])) for r in items for v in r.get('models',{}).values() if v.get('usable_urls'))
        summary['groups'].append({
            'policy':policy,'endpoint':endpoint,'success':sum(r.get('success',False) for r in items),'total':len(items),
            'requested_models':sum(len(r['vids']) for r in items),
            'valid_models':sum(sum(v.get('usable_urls',False) for v in r.get('models',{}).values()) for r in items),
            'rounds':sorted({r['round'] for r in items}),'codes':dict(codes),'definitions':dict(definitions),
            'latency_seconds':{'min':min(latencies),'median':round(median(latencies),3),'max':max(latencies)} if latencies else {},
            'failed_ids':[r['id'] for r in items if not r.get('success')],
        })
assert summary['device_identity_count']==1 and summary['install_identity_count']==1
assert summary['preservation']['unchanged']
# Compare media metadata without fetching URLs or publishing keys/signatures.
comparisons=[]
def fingerprints(row):
    raw=json.loads((HERE/'private'/(row['id']+'.json')).read_text())['response']['data']
    if row['endpoint']=='new_get':raw=raw['video_model_data']
    result={}
    for vid in row['vids']:
        model=raw[vid]['video_model']
        if isinstance(model,str):model=json.loads(model)
        tracks=[]
        for track in model['video_list']:
            meta=track.get('video_meta') or {}
            tracks.append((meta.get('definition'),meta.get('file_hash'),meta.get('size'),meta.get('codec_type')))
        result[vid]={'duration':model.get('video_duration'),'tracks':sorted(tracks)}
    return result
for round_no in (1,2,3):
    for group in ('a_single','a_five','cross_five','b_single'):
        pair=[r for r in rows if r['round']==round_no and r['group']==group and r['policy']=='current']
        if len(pair)==2 and all(r.get('success') for r in pair):
            left,right=map(fingerprints,pair)
            comparisons.append({'round':round_no,'group':group,'vid_count':len(left),
                                'same_duration_and_track_metadata':left==right})
summary['cross_endpoint_metadata_comparisons']=comparisons
(HERE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
