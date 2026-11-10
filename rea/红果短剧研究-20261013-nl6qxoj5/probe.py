"""Isolated study harness; imports an unchanged copy of the supplied plugin."""
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
report = {'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'cases': [], 'network': []}


def save():
    (ROOT/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


class Deadline(BaseException):
    pass


def deadline(*_):
    raise Deadline('case exceeded 70 seconds')


signal.signal(signal.SIGALRM, deadline)


def run(name, fn, summary=lambda x: x):
    print('START '+name, flush=True)
    start = time.monotonic()
    signal.alarm(70)
    try:
        value = fn()
        row = {'case': name, 'outcome': 'returned', 'result': summary(value)}
    except (Exception, Deadline) as exc:
        value = None
        row = {'case': name, 'outcome': 'error', 'error_type': type(exc).__name__, 'error': str(exc)[:1200]}
    finally:
        signal.alarm(0)
    row['seconds'] = round(time.monotonic()-start, 3)
    report['cases'].append(row)
    save()
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return value


direct = run('direct_execution', lambda: subprocess.run(
    [sys.executable, '-I', '-B', str(ROOT/'source.py')], cwd=ROOT,
    capture_output=True, text=True, timeout=30),
    lambda p: {'exit_code':p.returncode, 'stdout':p.stdout[:500], 'stderr':p.stderr[:1000]})
spec = importlib.util.spec_from_file_location('studied_hongguo', ROOT/'source.py')
m = importlib.util.module_from_spec(spec)
run('import', lambda: spec.loader.exec_module(m), lambda _: {'AES_BACKEND':m.AES_BACKEND})
(ROOT/'cache').mkdir(exist_ok=True)
m._HG_CACHE_DIR = str(ROOT/'cache')  # Only isolate storage, keep network/crypto code intact.
original_request = m.requests.sessions.Session.request


def observed_request(self, method, url, **kwargs):
    parts = urlsplit(url)
    row = {'method':method, 'host':parts.hostname, 'path':parts.path}
    data = kwargs.get('data')
    if data and parts.path.endswith('multi_video_model/v1/'):
        body = json.loads(data)
        row['mixed_video_id_map_keys'] = list(body.get('mixed_video_id_map', {}))
        row['body_sha256'] = hashlib.sha256(data).hexdigest()
    start = time.monotonic()
    try:
        r = original_request(self, method, url, **kwargs)
        row.update(status=r.status_code, bytes=len(r.content), seconds=round(time.monotonic()-start, 3))
        if parts.path.endswith('multi_video_model/v1/'):
            try:
                result = r.json()
                row['response_keys'] = list(result)
                for k in ('code','Code','message','Message','BaseResp'):
                    if k in result:
                        row[k] = result[k]
            except ValueError:
                row['json'] = False
        return r
    except Exception as exc:
        row['error_type'] = type(exc).__name__
        raise
    finally:
        report['network'].append(row)
        save()


m.requests.sessions.Session.request = observed_request
s = m.Spider()
run('init', s.init)
run('AES_known_vector', lambda: {
    'encrypt_matches':m._PureAES128(bytes.fromhex('000102030405060708090a0b0c0d0e0f')).encrypt_block(
        bytes.fromhex('00112233445566778899aabbccddeeff')).hex() == '69c4e0d86a7b0430d8cdb78070b4c55a',
    'decrypt_matches':m._PureAES128(bytes.fromhex('000102030405060708090a0b0c0d0e0f')).decrypt_block(
        bytes.fromhex('69c4e0d86a7b0430d8cdb78070b4c55a')).hex() == '00112233445566778899aabbccddeeff'})


def listing(x):
    return {'count':len(x.get('list', [])), 'page':x.get('page'), 'pagecount':x.get('pagecount'),
            'total':x.get('total'), 'items':[{'id':i.get('vod_id'), 'title':i.get('vod_name')} for i in x.get('list', [])]}


home = run('homeContent', lambda:s.homeContent(True), lambda x: {
    **listing(x), 'classes':x.get('class'),
    'filters':[{ 'key':g['key'], 'name':g['name'], 'options':len(g['value'])} for g in x.get('filters',{}).get('all',[])]})
run('homeVideoContent', s.homeVideoContent, listing)
category1 = run('category_all_page1', lambda:s.categoryContent('all','1',True,{}), listing)
category2 = run('category_all_page2', lambda:s.categoryContent('all','2',True,{}), listing)
for tid in ('latest','hot','male','female'):
    run('category_'+tid, lambda tid=tid:s.categoryContent(tid,'1',True,{}), listing)
run('category_filtered', lambda:s.categoryContent('all','1',True,{'setting':'cate_36','time':'1'}), listing)
search1 = run('search_重生_page1', lambda:s.searchContent('重生',pg='1'), listing)
search2 = run('search_重生_page2', lambda:s.searchContent('重生',pg='2'), listing)
ai1 = run('AI漫剧_page1', lambda:s.categoryContent('ai_comic','1',True,{}), listing)
ai2 = run('AI漫剧_page2', lambda:s.categoryContent('ai_comic','2',True,{}), listing)
report['pagination_comparison'] = {
    'category_pages_identical':bool(category1 and category2) and category1.get('list') == category2.get('list'),
    'ordinary_search_pages_identical':bool(search1 and search2) and search1.get('list') == search2.get('list'),
}
candidates = (search1 or {}).get('list') or (category1 or {}).get('list') or []
sid = candidates[0]['vod_id'] if candidates else '7689863296106646590'
detail = run('detail', lambda:s.detailContent([sid]), lambda x:{
    'count':len(x.get('list',[])), 'title':x['list'][0]['vod_name'],
    'play_lines':x['list'][0]['vod_play_from'].split('$$$'),
    'episodes_per_line':[len(line.split('#')) if line else 0 for line in x['list'][0]['vod_play_url'].split('$$$')],
    'has_intro':bool(x['list'][0]['vod_content']), 'actors':x['list'][0]['vod_actor']})
token = 'hg-episode-v1:1080:7689903116275174462'
if detail and detail['list'][0]['vod_play_url'].split('$$$')[0]:
    token = detail['list'][0]['vod_play_url'].split('$$$')[0].split('#')[0].split('$',1)[1]
quality, vid = m._split_episode_token(token)
report['sample'] = {'series_id':sid,'vid':vid,'quality':quality}
cfg = {'device_id':s.device_id,'install_id':s.install_id}
model = run('video_model_original', lambda:m._video_model(vid,cfg), lambda x:{
    'keys':list(x), 'track_count':len(m._video_list_from_model(x) or []),
    'quality':m._select_quality(m._video_list_from_model(x),'1080')[0]})
if model:
    private = ROOT/'model.private.json'
    private.write_text(json.dumps(model,ensure_ascii=False,indent=2))
    private.chmod(0o600)
player = run('playerContent_local_range', lambda:s.playerContent('红果超清',token),
             lambda x:{'parse':x.get('parse'),'url_host':urlsplit(x.get('url','')).hostname,
                       'url_path':urlsplit(x.get('url','')).path})
if player and player.get('parse') == 0:
    run('local_range_HEAD', lambda:m.requests.head(player['url'],timeout=40),
        lambda r:{'status':r.status_code,'content_length':r.headers.get('Content-Length'),
                  'accept_ranges':r.headers.get('Accept-Ranges')})
    run('local_range_GET', lambda:m.requests.get(player['url'],headers={'Range':'bytes=0-65535'},timeout=40),
        lambda r:{'status':r.status_code,'bytes':len(r.content),'content_range':r.headers.get('Content-Range'),
                  'ftyp':b'ftyp' in r.content[:64],'error':r.text[:200] if r.status_code>=400 else None})
proxy = run('localProxy_full_episode', lambda:s.localProxy({'vid':vid,'q':'1080'}),
            lambda x:{'status':x[0],'content_type':x[1],'bytes':len(x[2]),
                      'error':x[2].decode(errors='replace')[:1500] if x[0]!=200 else None})
if proxy and proxy[0] == 200:
    (ROOT/'sample.mp4').write_bytes(proxy[2])
    run('ffprobe_full_episode', lambda:subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(ROOT/'sample.mp4')],capture_output=True,text=True,timeout=30),
        lambda p:{'exit_code':p.returncode,'probe':json.loads(p.stdout) if p.stdout else {},'stderr':p.stderr[:1000]})
    run('ffmpeg_full_decode', lambda:subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(ROOT/'sample.mp4'),'-map','0:v?','-map','0:a?','-f','null','-'],capture_output=True,text=True,timeout=60),
        lambda p:{'exit_code':p.returncode,'stderr':p.stderr[:2000]})
server = m._STREAM_STATE.get('server')
if server:
    server.shutdown()
    server.server_close()
run('destroy', s.destroy)
report['source_unchanged'] = hashlib.sha256((ROOT/'source.py').read_bytes()).hexdigest() == hashlib.sha256(Path('/Users/tt/Downloads/红果短剧.py').read_bytes()).hexdigest()
save()
print('DONE '+str(ROOT/'results.json'),flush=True)
