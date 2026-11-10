"""Offline summary of completed pure-script discovery phases."""
from collections import defaultdict
from datetime import datetime
import json

import probe as p

runs = [json.loads((p.HERE/(name+'.json')).read_text()) for name in ('smoke','coverage','repeat')]
rows = [row for run in runs for row in run['results']]
by_kind = defaultdict(lambda: {'calls':0,'success':0,'empty_list_cases':[]})
by_path = defaultdict(lambda: {'calls':0,'success':0})
for row in rows:
    by_kind[row['kind']]['calls'] += 1
    by_kind[row['kind']]['success'] += bool(row['success'])
    if 'nonempty' in row.get('parsed',{}) and not row['parsed']['nonempty']:
        by_kind[row['kind']]['empty_list_cases'].append(row['id'])
    if 'path' in row:
        by_path[row['path']]['calls'] += 1
        by_path[row['path']]['success'] += bool(row['success'])
before = json.loads((p.HERE/'smoke-before-hashes.json').read_text())
after = p.protected_hashes()
changed = [k for k in sorted(before.keys()|after.keys()) if before.get(k)!=after.get(k)]
summary = {
    'started':runs[0]['started'],'finished':runs[-1]['finished'],
    'wall_seconds':int((datetime.fromisoformat(runs[-1]['finished'])-
                       datetime.fromisoformat(runs[0]['started'])).total_seconds()),
    'cases':len(rows),'remote_requests':sum(r['remote_calls'] for r in rows),
    'local_signature_stage_calls':sum(r['signature_calls'] for r in rows),
    'success':sum(r['success'] for r in rows),
    'failed_cases':[{'id':r['id'],'code':r.get('codes'),'error':r.get('error')} for r in rows if not r['success']],
    'by_kind':dict(by_kind),'by_path':dict(by_path),
    'pagination':[{'id':r['id'],**r['pagination']} for r in rows if 'pagination' in r],
    'same_fixed_identity':len({(r['device_sha256'],r['iid_sha256'],r['cdid_sha256']) for r in rows if 'device_sha256' in r})==1,
    'hosts':sorted({r['host'] for r in rows if 'host' in r}),
    'protected_files':len(before),'changed_protected_files':changed,
    'private_directory_mode':oct(p.PRIVATE.stat().st_mode & 0o777),
    'raw_file_count':len(list(p.PRIVATE.glob('*.json'))),
    'raw_file_modes':sorted({oct(f.stat().st_mode & 0o777) for f in p.PRIVATE.glob('*.json')}),
}
assert not changed
p.write(p.HERE/'results.json',{'runs':runs})
p.write(p.HERE/'summary.json',summary)
print(json.dumps(summary,ensure_ascii=False,indent=2))
