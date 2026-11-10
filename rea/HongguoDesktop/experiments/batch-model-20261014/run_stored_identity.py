"""Distinguish a persisted original identity from the random experiment IDs."""
from lab import *

lab = Lab('06-stored-identity-repeat')
original_ids = {'device_id': str(ORIGINAL['query']['device_id']),
                'install_id': str(ORIGINAL['query']['iid'])}
with LocalSigner(ROOT/'vendor') as signer:
    api = lab.api(signer)
    try:
        for label in ('python_stored_first', 'python_stored_repeat'):
            lab.case(label, lambda: lab.sign_and_send(
                lab.template('ours', original_ids, api), 'python', api))
        for label in ('jar_python_hm_stored_first','jar_python_hm_stored_repeat'):
            lab.case(label, lambda: lab.hybrid_send(
                lab.template('ours', original_ids, api), 'jar', ['x-helios','x-medusa'], api))
        lab.case('python_stored_curl', lambda: lab.sign_and_send(
            lab.template('ours', original_ids, api), 'python', api, transport='curl_chrome'))
        api.device = deepcopy(ORIGINAL)
        lab.case('jar_stored_single_final_control', lambda: api._api_once('POST', SINGLE_MODEL_PATH,
            body={'biz_param': BIZ, 'video_id': VID}))
    finally:
        api.close()
    signer.mark_success()
lab.save()
