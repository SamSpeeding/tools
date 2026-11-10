"""Bounded serial checks over time with a persisted identity and fresh signer."""
from deep_lab import *

lab=DeepLab('10-persisted-repeat-window')
catalog=json.loads((HERE/'episode-catalog.json').read_text())
a=catalog['A']['episodes'];b=catalog['B']['episodes']
five=[a[0]['vid'],a[1]['vid'],a[len(a)//2]['vid'],b[0]['vid'],b[-1]['vid']]
tail=[ep['vid'] for ep in a[-3:]]+[ep['vid'] for ep in b[-2:]]
with LocalSigner(ROOT/'vendor') as signer:
    api=lab.api(signer)
    try:
        for i in range(6):
            if i:time.sleep(20)
            chosen=five if i%2==0 else tail
            lab.model('repeat_round_'+str(i+1),chosen,api)
        lab.model('python_tail_five_curl',tail,api,'python','curl_chrome')
        lab.model('jar_tail_five_control',tail,api,'jar')
        lab.model('hybrid_tail_five_final',tail,api)
    finally:
        api.close()
    signer.mark_success()
lab.save()
