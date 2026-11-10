from lab import *

lab = Lab('01-baseline')
with LocalSigner(ROOT/'vendor') as signer:
    api = lab.api(signer)
    try:
        lab.case('our_original_batch', lambda: api._api_once('POST', MODEL_PATH, body={
            'biz_param': BIZ, 'mixed_video_id_map': {'1': [VID]}}))
        ids = identity('baseline_A')
        lab.case('script_A_first', lambda: lab.plugin_native(ids))
        lab.case('script_A_repeat', lambda: lab.plugin_native(ids))
        lab.case('script_B_first', lambda: lab.plugin_native(identity('baseline_B')))
        lab.case('our_original_single_control', lambda: api._api_once('POST', SINGLE_MODEL_PATH,
            body={'biz_param': BIZ, 'video_id': VID}))
    finally:
        api.close()
    signer.mark_success()
lab.save()
