"""HTTP acceptance client; not a PHP runtime dependency. No persistent MP4."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

HERE=Path(__file__).resolve().parent
BASE='http://127.0.0.1:8080'
rows=[]
class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=[];self.inputs=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('input','select','textarea'):self.inputs+=1
        if tag=='a' and attrs.get('href','').startswith('api.php?'):self.urls.append(attrs['href'])

def get(url,method='GET',headers=None):
    req=urllib.request.Request(urllib.parse.urljoin(BASE+'/',url),method=method,headers=headers or {})
    try:r=urllib.request.urlopen(req,timeout=90)
    except urllib.error.HTTPError as e:r=e
    with r:return r.status,dict(r.headers),r.read()

def save(row):
    rows.append(row);(HERE/'http-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps(row,ensure_ascii=False),flush=True)

def verify_json(url,label=None):
    time.sleep(1.5)
    status,headers,body=get(url)
    data=json.loads(body)
    assert status==200 and data.get('code')==0,(url,status,data)
    assert headers['Content-Type'].startswith('application/json')
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query);action=q.get('action',['video'])[0]
    info=data['data'];row={'case':label or action,'action':action,'status':status,'bytes':len(body)}
    if action in ('search','rank','category','latest'):
        assert info['items'] and all(isinstance(i['series_id'],str) and i['title'] for i in info['items'])
        assert len({i['series_id'] for i in info['items']})==len(info['items'])
        assert all(urllib.parse.parse_qs(urllib.parse.urlsplit(i['detail_url']).query)['action']==['detail'] for i in info['items'])
        assert (info['next_url'] is not None)==info['has_more']
        row['items']=len(info['items']);row['has_more']=info['has_more']
    elif action=='filters':assert info['rows'];row['rows']=len(info['rows'])
    elif action in ('detail','episodes'):
        assert info['complete'] and not info['issues']
        expected=info.get('meta',info)['episode_cnt']
        assert len(info['episodes'])==expected
        for ep in info['episodes']:
            assert isinstance(ep['vid'],str)
            for field,mode in [('model_url','video'),('play_url','play'),('download_url','download')]:
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(ep[field]).query)
                assert query['action']==[mode] and query['vid']==[ep['vid']]
        row['episodes']=expected
    elif action=='video':assert info['video_model']['video_list'];row['tracks']=len(info['video_model']['video_list'])
    save(row);return info

def main():
    status,_,html=get('/')
    assert status==200
    links=Links();links.feed(html.decode());assert links.inputs==0
    assert len(links.urls)==len(set(links.urls))
    save({'case':'index','status':status,'default_links':len(links.urls),'input_fields':links.inputs})
    pages={}
    for url in links.urls:
        q=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query);action=q['action'][0]
        if action in ('play','download'):continue
        info=verify_json(url)
        if action in ('search','rank','category','latest') and action not in pages and info.get('next_url'):
            pages[action]=info
    for action,first in pages.items():
        second=verify_json(first['next_url'],action+'-next-url')
        assert set(i['series_id'] for i in second['items'])-set(i['series_id'] for i in first['items']),action
    verify_json('/video.php?vid=7689903116275174462','legacy-video')
    invalid=[('/api.php',400),('/api.php?action=nope',400),('/api.php?action=search&q[]=x',400),
        ('/api.php?action=search',400),('/api.php?action=rank&category=nope',400),
        ('/api.php?action=category&cursor=%5B%5D',400),('/api.php?action=category&offset=-1',400),
        ('/api.php?action=category&selections=%7B%22sort%22%3A%22x%22%7D',400),
        ('/api.php?action=detail&series_id=abc',400),('/api.php?action=video&vid=abc',400),
        ('/api.php?action=play&vid=7689903116275174462&quality=nope',400),('/common.php',404)]
    for url,expected in invalid:
        status,_,body=get(url);assert status==expected,(url,status,body[:150])
        if status!=404:assert json.loads(body).get('error')
        save({'case':'invalid-input','path':url.split('?')[0],'status':status})
    for action in ('search','play','download','video'):
        status,h,_=get('/api.php?action='+action,method='POST');assert status==405 and 'GET' in h['Allow']
        save({'case':'method-'+action,'status':status})
    vid='7689903116275174462';play=f'/api.php?action=play&vid={vid}&quality=1080p';download=play.replace('action=play','action=download')
    time.sleep(1.5);status,h,full=get(download)
    assert status==200 and h['Content-Type']=='video/mp4' and 'attachment' in h['Content-Disposition'],(status,full[:100])
    total=int(h['Content-Length']);assert len(full)==total
    assert int(h['X-Upstream-Bytes-Before-Body'])<total
    digest=hashlib.sha256(full).hexdigest()
    assert digest=='d41be261a5b7c3e7c2c06c4046e354c0bbc8a7f7b1ead1348f2af4d617b5bc96',digest
    capture=HERE/'private/client-download.mp4';capture.write_bytes(full)
    try:
        result=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(capture),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    finally:capture.unlink(missing_ok=True)
    save({'case':'unified-download','status':status,'bytes':total,'sha256':digest,'full_video_audio_decode':True,'before_body_bytes':int(h['X-Upstream-Bytes-Before-Body'])})
    for value,start,end in [('bytes=0-1',0,1),('bytes=262137-524300',262137,524300)]:
        time.sleep(1.5);status,h,data=get(play,headers={'Range':value})
        assert status==206 and h['Content-Range']==f'bytes {start}-{end}/{total}'
        assert data==full[start:end+1] and 'inline' in h['Content-Disposition']
        save({'case':'unified-play-range','range':value,'status':status,'byte_exact':True})
    for action in ('play','download'):
        time.sleep(1.5);status,h,body=get(f'/api.php?action={action}&vid={vid}&quality=720p',method='HEAD')
        assert status==200 and not body and int(h['Content-Length'])>0
        assert ('attachment' if action=='download' else 'inline') in h['Content-Disposition']
        save({'case':action+'-head-720p','status':status})
    time.sleep(1.5);status,h,_=get(play,headers={'Range':'bytes=0-1,10-20'});assert status==416
    save({'case':'invalid-range','status':status})
    time.sleep(1.5);status,h,data=get(f'/play.php?vid={vid}',headers={'Range':'bytes=12345-12360'})
    assert status==206 and data==full[12345:12361]
    save({'case':'legacy-play-range','status':status,'byte_exact':True})
    print(json.dumps({'passed':True,'checks':len(rows)}),flush=True)

if __name__=='__main__':main()
