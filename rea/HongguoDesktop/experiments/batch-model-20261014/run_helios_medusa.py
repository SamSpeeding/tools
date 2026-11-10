"""Resume only the bounded signature-pair hypothesis after installer comparison."""
from lab import *

lab = Lab('05-helios-medusa-pair')
with LocalSigner(ROOT/'vendor') as signer:
    api = lab.api(signer)
    try:
        candidate = identity('pair_hm_A')
        for label, ids in [('jar_with_python_hm_A_first', candidate),
                           ('jar_with_python_hm_A_repeat', candidate),
                           ('jar_with_python_hm_B_first', identity('pair_hm_B'))]:
            lab.case(label, lambda ids=ids: lab.hybrid_send(
                lab.template('ours', ids, api), 'jar', ['x-helios','x-medusa'], api))
        original_ids = {'device_id': str(ORIGINAL['query']['device_id']),
                        'install_id': str(ORIGINAL['query']['iid'])}
        lab.case('python_original_stored_ids_revisit', lambda: lab.sign_and_send(
            lab.template('ours', original_ids, api), 'python', api))
        lab.case('jar_original_stored_ids_end_control', lambda: lab.sign_and_send(
            lab.template('ours', original_ids, api), 'jar', api))
        lab.case('python_fresh_end_control', lambda: lab.sign_and_send(
            lab.template('ours', identity('pair_fresh_control'), api), 'python', api))
    finally:
        api.close()
    signer.mark_success()
lab.save()
