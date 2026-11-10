from deep_lab import *

lab=DeepLab('07-cross-episode-multivid')
with LocalSigner(ROOT/'vendor') as signer:
    api=lab.api(signer)
    try:
        a=lab.detail('detail_series_A','7689863296106646590',api)
        b=lab.detail('detail_series_B','7694947161145871384',api)
        (HERE/'episode-catalog.json').write_text(json.dumps({'A':a,'B':b},ensure_ascii=False,indent=2))
        ea=a['episodes'];eb=b['episodes']
        a_by_index={ep['index']:ep['vid'] for ep in ea}
        anchor=a_by_index[2]
        lab.model('jar_original_baseline',[anchor],api,'jar')
        lab.model('hybrid_original_baseline',[anchor],api)
        for idx in sorted(set([1,3,5,ea[len(ea)//2]['index'],ea[-1]['index']])):
            lab.model('hybrid_A_episode_'+str(idx),[a_by_index[idx]],api)
        pair=[ep['vid'] for ep in ea[:2]]
        five=[ep['vid'] for ep in ea[:5]]
        mixed=[ep['vid'] for ep in ea[:3]]+[eb[0]['vid'],eb[-1]['vid']]
        for label,vids in [('hybrid_A_two',pair),('hybrid_A_two_repeat',pair),
                           ('hybrid_A_five',five),('hybrid_A_five_repeat',five),
                           ('hybrid_cross_series_five',mixed),('hybrid_cross_series_five_repeat',mixed),
                           ('hybrid_A_five_reverse',list(reversed(five)))]:
            lab.model(label,vids,api)
        lab.model('python_cross_series_five',mixed,api,'python')
        lab.model('jar_cross_series_five_control',mixed,api,'jar')
        lab.model('hybrid_cross_series_five_after_jar',mixed,api)
        api.device=deepcopy(ORIGINAL)
        lab.signing='jar'
        lab.case('jar_single_final_control',lambda:api._api_once('POST',SINGLE_MODEL_PATH,
            body={'biz_param':BIZ,'video_id':anchor}))
    finally:
        api.close()
    signer.mark_success()
lab.save()
