"""Client-side verification only. No Python is part of HongguoPHP runtime.

MP4 files below are client download captures, never PHP server output files.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:18083'
VID='7689903116275174462'
rows=[]

def get(path, *, headers=None, method='GET'):
    request=urllib.request.Request(BASE+path,headers=headers or {},method=method)
    try:
        response=urllib.request.urlopen(request,timeout=90)
    except urllib.error.HTTPError as error:
        response=error
    with response:
        return response.status,dict(response.headers),response.read()

def main():
    for vid in [VID,'7689903030619081790','7689903075380694078','7694949024280874009',VID]:
        start=time.monotonic();status,h,body=get('/video.php?vid='+vid)
        result=json.loads(body)
        assert status==200,(status,result)
        model=result['data']['video_model']
        assert len(model['video_list'])>0
        rows.append({'kind':'model','vid':vid,'status':status,'tracks':len(model['video_list']),'seconds':round(time.monotonic()-start,3)})
    path='/play.php?vid='+VID
    start=time.monotonic();status,h,full=get(path+'&download=1')
    assert status==200,(status,full[:300])
    assert h['Content-Type']=='video/mp4' and 'attachment' in h['Content-Disposition']
    total=int(h['Content-Length']);assert len(full)==total
    assert int(h['X-Upstream-Bytes-Before-Body'])<total
    sha=hashlib.sha256(full).hexdigest()
    assert sha=='d41be261a5b7c3e7c2c06c4046e354c0bbc8a7f7b1ead1348f2af4d617b5bc96',sha
    output=ROOT/'client-download-ep2.mp4';output.write_bytes(full)
    decode=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,text=True)
    assert decode.returncode==0,decode.stderr
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_name,codec_type','-of','json',str(output)]))
    rows.append({'kind':'full_download','bytes':total,'upstream_bytes_before_body':int(h['X-Upstream-Bytes-Before-Body']),'sha256':sha,'seconds':round(time.monotonic()-start,3),'decode':'all_video_audio_passed','probe':probe})
    output.unlink()  # Client capture served only to verify FFmpeg; keep no MP4 artifact.
    for value,first,last in [('bytes=0-1',0,1),('bytes=12345-42345',12345,42345),('bytes=262137-524300',262137,524300),('bytes=-4096',total-4096,total-1),('bytes=4000000-',4000000,total-1)]:
        status,h,data=get(path,headers={'Range':value})
        assert status==206,(status,data[:300])
        assert h['Content-Range']==f'bytes {first}-{last}/{total}'
        assert data==full[first:last+1],value
        assert 'inline' in h['Content-Disposition']
        rows.append({'kind':'range','range':value,'bytes':len(data),'matches_full':True})
    status,h,body=get(path,method='HEAD');assert status==200 and len(body)==0 and int(h['Content-Length'])==total
    rows.append({'kind':'head','status':status,'content_length':total})
    for value in ['bytes=0-1,10-20',f'bytes={total}-','bytes=-0']:
        status,h,body=get(path,headers={'Range':value});assert status==416 and h['Content-Range']==f'bytes */{total}'
        rows.append({'kind':'invalid_range','range':value,'status':status})
    for bad in ['/video.php','/video.php?vid[]=123','/play.php?vid=abc','/play.php?vid='+VID+'&quality=nope']:
        status,h,body=get(bad);assert status==400,(status,body);rows.append({'kind':'invalid_input','status':status})
    status,h,body=get(path,method='POST');assert status==405;rows.append({'kind':'method','status':status})

if __name__=='__main__':
    try:
        main()
    finally:
        (ROOT/'http-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps({'passed':True,'checks':len(rows),'evidence':str(ROOT/'http-results.json')}))
