from lab import *

lab = Lab('03-factors')
with LocalSigner(ROOT/'vendor') as signer:
    api = lab.api(signer)
    try:
        short = identity('factor_short_ids', 16)
        for suffix in ('first', 'repeat'):
            lab.case('ours_python_16_'+suffix, lambda: lab.sign_and_send(lab.template('ours', short, api), 'python', api))
        lab.case('ours_python_curl_18_first', lambda: lab.sign_and_send(
            lab.template('ours', identity('factor_curl'), api), 'python', api, 'curl_chrome'))
        medusa = identity('factor_jar_python_medusa')
        for suffix in ('first', 'repeat'):
            lab.case('ours_jar_python_medusa_'+suffix, lambda: lab.hybrid_send(
                lab.template('ours', medusa, api), 'jar', ['x-medusa'], api))
        lab.case('ours_python_jar_medusa_first', lambda: lab.hybrid_send(
            lab.template('ours', identity('factor_python_jar_medusa'), api), 'python', ['x-medusa'], api))
        lab.case('ours_jar_python_argus_ladon_first', lambda: lab.hybrid_send(
            lab.template('ours', identity('factor_argus_ladon'), api), 'jar', ['x-argus', 'x-ladon'], api))
        def four_headers():
            template = lab.template('ours', identity('factor_four_headers'), api)
            headers = lab.signed_headers(template, 'jar', api)
            headers.pop('x-medusa', None)
            headers.pop('x-helios', None)
            return lab.send('POST', template['url'], headers, template['body'])
        lab.case('ours_jar_no_medusa_helios_first', four_headers)
    finally:
        api.close()
    signer.mark_success()
lab.save()
