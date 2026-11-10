"""Check export coverage and read only 128 bytes from three returned CDN URLs."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit
import requests

root = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else root/'outputs/逆袭111集.json'
j = json.loads(path.read_text())
episodes = j['episodes']
assert j['status'] == 'complete'
assert len(episodes) == j['series']['episode_cnt'] == j['resolved_count']
assert [e['index'] for e in episodes] == list(range(1, len(episodes) + 1))
assert len({e['vid'] for e in episodes}) == len(episodes)
assert len({e['download_url'] for e in episodes}) == len(episodes)
assert all(urlsplit(e['download_url']).scheme in ('http','https') for e in episodes)
summary = {'checked_at':datetime.now(timezone.utc).isoformat(), 'export_file':str(path),
           'status':j['status'], 'episodes':len(episodes), 'unique_vids':len(episodes),
           'unique_primary_urls':len(episodes),
           'tracks':sum(len(e['tracks']) for e in episodes), 'samples':[]}
for index in (0, len(episodes)//2, len(episodes)-1):
    ep = episodes[index]
    with requests.get(ep['download_url'], headers={'Range':'bytes=0-127'},
                      stream=True, timeout=30) as response:
        sample = next(response.iter_content(128), b'')
        result = {'episode_index':ep['index'], 'http_status':response.status_code,
                  'content_type':response.headers.get('Content-Type'),
                  'content_range':response.headers.get('Content-Range'),
                  'bytes_read':len(sample), 'prefix_hex':sample[:16].hex()}
        summary['samples'].append(result)
        print(result, flush=True)
        assert response.status_code in (200,206) and len(sample)==128
(root/'analysis/evidence/live-verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print('PASS',len(episodes),'episodes,',summary['tracks'],'tracks; 3 CDN samples readable')
