from lab import *

lab = Lab('04-context-and-reuse')
with LocalSigner(ROOT/'vendor') as signer:
    api = lab.api(signer)
    try:
        def jar_without_extra():
            template = lab.template('ours', identity('context_jar_no_extra'), api)
            headers = lab.signed_headers(template, 'jar', api)
            for k in ('x-neptune', 'x-soter'): headers.pop(k, None)
            return lab.send('POST', template['url'], headers, template['body'])
        lab.case('jar_without_neptune_soter', jar_without_extra)
        lab.case('python_with_jar_neptune_soter', lambda: lab.hybrid_send(
            lab.template('ours', identity('context_py_extra'), api), 'python', ['x-neptune','x-soter'], api))
        lab.case('jar_without_extras_with_python_medusa', lambda: lab.hybrid_send(
            lab.template('ours', identity('context_jar_no_extra_py_medusa'), api), 'jar', ['x-medusa'], api,
            drop=['x-neptune','x-soter']))
        for fields, group in [(['x-gorgon'], 'gorgon'), (['x-helios'], 'helios'),
                               (['x-argus','x-ladon'], 'argus_ladon')]:
            lab.case('python_with_jar_'+group, lambda f=fields, g=group: lab.hybrid_send(
                lab.template('ours', identity('context_py_'+g), api), 'python', f, api))
        stable = identity('context_stable_env')
        def stable_environment():
            original = plugin.random
            def randint(a,b):
                if (a,b) == (100,120): return 110
                if (a,b) == (10001,12000): return 11000
                return original.randint(a,b)
            plugin.random = SimpleNamespace(randint=randint)
            try:
                return lab.sign_and_send(lab.template('ours', stable, api), 'python', api)
            finally:
                plugin.random = original
        lab.case('python_stable_pid_launch_first', stable_environment)
        lab.case('python_stable_pid_launch_repeat', stable_environment)
        lab.case('script_baseline_A_after_interval', lambda: lab.plugin_native(identity('baseline_A')))
        original_ids = {'device_id': str(ORIGINAL['query']['device_id']),
                        'install_id': str(ORIGINAL['query']['iid'])}
        lab.case('python_original_stored_ids', lambda: lab.sign_and_send(
            lab.template('ours', original_ids, api), 'python', api))
        lab.case('python_fresh_end_control', lambda: lab.sign_and_send(
            lab.template('ours', identity('context_fresh_end_control'), api), 'python', api))
        api.device = deepcopy(ORIGINAL)
        lab.case('our_original_single_end_control', lambda: api._api_once('POST', SINGLE_MODEL_PATH,
            body={'biz_param': BIZ, 'video_id': VID}))
    finally:
        api.close()
    signer.mark_success()
lab.save()
