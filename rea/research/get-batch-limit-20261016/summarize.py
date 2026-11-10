"""Offline aggregation; no HTTP requests and no media files."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import os

import probe_support as p

LABELS = ('ladder','boundary','narrow','upper','cross','tail','cross-tail')
runs = [json.loads((p.HERE/(name+'.json')).read_text()) for name in LABELS]
rows = [row for run in runs for row in run['results']]
by_count = defaultdict(lambda: {'requests':0, 'success':0, 'codes':[]})
all_successful_vids = set()
for row in rows:
    assert len(row['vids']) == len(set(row['vids'])) == row['requested_count']
    group = by_count[row['requested_count']]
    group['requests'] += 1
    group['success'] += bool(row['success'])
    group['codes'].append(row.get('codes'))
    if row['success']:
        assert set(row['vids']) == set(row['returned_vids'])
        assert row['valid_models'] == row['requested_count']
        all_successful_vids.update(row['vids'])
fail_vids = {vid for row in rows if not row['success'] for vid in row['vids']}
before = json.loads((p.HERE/'ladder-before-hashes.json').read_text())
after = p.protected_hashes()
changed = [k for k in sorted(before.keys()|after.keys()) if before.get(k) != after.get(k)]
alive = []
for run in runs:
    try:
        os.kill(run['signer_pid'], 0)
    except ProcessLookupError:
        continue
    alive.append(run['signer_pid'])
summary = {
    'started':runs[0]['started'], 'finished':runs[-1]['finished'],
    'wall_seconds':int((datetime.fromisoformat(runs[-1]['finished'])-
                        datetime.fromisoformat(runs[0]['started'])).total_seconds()),
    'requests':len(rows), 'success':sum(bool(row['success']) for row in rows),
    'unique_vids_requested':len({vid for row in rows for vid in row['vids']}),
    'unique_vids_returned_valid':len(all_successful_vids),
    'by_batch_size':dict(sorted(by_count.items())),
    'largest_fully_successful_batch':max(row['requested_count'] for row in rows if row['success']),
    'smallest_failed_batch':min(row['requested_count'] for row in rows if not row['success']),
    'failure_vids_not_validated_in_smaller_batches':sorted(fail_vids-all_successful_vids),
    'all_runs_same_device':len({(row['device_sha256'],row['iid_sha256']) for row in rows})==1,
    'hosts':sorted({row['host'] for row in rows}),
    'medusa_versions':sorted({row['medusa_version'] for row in rows}),
    'protected_files':len(before), 'changed_protected_files':changed,
    'signer_pids_still_alive':alive,
    'temporary_runtime_removed':not (p.HERE/'runtime').exists(),
    'private_directory_mode':oct(p.PRIVATE.stat().st_mode & 0o777),
    'raw_response_count':len(list(p.PRIVATE.glob('*.json'))),
    'raw_response_modes':sorted({oct(f.stat().st_mode & 0o777) for f in p.PRIVATE.glob('*.json')}),
}
assert not changed and not alive
assert not summary['failure_vids_not_validated_in_smaller_batches']
p.write(p.HERE/'results.json', {'runs':runs})
p.write(p.HERE/'summary.json', summary)
print(json.dumps(summary,ensure_ascii=False,indent=2))
