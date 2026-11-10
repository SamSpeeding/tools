"""Read Python bytecode metadata only; never import/execute the target module."""
import json
from pathlib import Path
from xdis.load import load_module
from xdis.bytecode import Bytecode
from xdis.op_imports import get_opcode_module

ROOT = Path(__file__).resolve().parents[2]
version, _, _, code, implementation, *_ = load_module(str(ROOT / 'analysis/extracted/app/server.pyc'))
op = get_opcode_module(version, implementation)
instructions = [i for i in Bytecode(code, op) if i.opname not in ('CACHE', 'EXTENDED_ARG')]
lines = (ROOT / 'analysis/evidence/server.dis.txt').read_text().splitlines()
anchors = {}
for no, line in enumerate(lines, 1):
    if line.startswith('# Method Name:'):
        anchors.setdefault(line.split(':', 1)[1].strip(), no)

def clean(value):
    if value is Ellipsis:
        return {'required': True}
    if hasattr(value, 'co_name'):
        return {'code': value.co_name, 'line': value.co_firstlineno}
    if isinstance(value, (list, tuple)):
        return [clean(x) for x in value]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)

routes = []
for i, inst in enumerate(instructions):
    if inst.opname != 'LOAD_NAME' or inst.argval != 'app':
        continue
    method = instructions[i+1]
    if method.opname != 'LOAD_METHOD' or method.argval not in ('get','post','put','patch','delete','options','head'):
        continue
    j = i+2
    while instructions[j].opname == 'EXTENDED_ARG':
        j += 1
    path = instructions[j].argval
    assert isinstance(path, str) and path.startswith('/'), (i,path)
    while instructions[j].opname != 'CALL':
        j += 1
    j += 1
    stack, kwargs = [], ()
    while instructions[j].opname != 'MAKE_FUNCTION':
        ins = instructions[j]
        if ins.opname == 'LOAD_CONST':
            stack.append(ins.argval)
        elif ins.opname == 'LOAD_NAME':
            stack.append({'symbol': ins.argval})
        elif ins.opname == 'BUILD_TUPLE':
            parts = stack[-ins.arg:] if ins.arg else []
            if ins.arg:
                del stack[-ins.arg:]
            stack.append(tuple(parts))
        elif ins.opname == 'KW_NAMES':
            kwargs = ins.argval
        elif ins.opname == 'CALL':
            args = stack[-ins.arg:] if ins.arg else []
            if ins.arg:
                del stack[-ins.arg:]
            target = stack.pop()
            assert target in ({'symbol':'Query'}, {'symbol':'Body'}), target
            kwvalues = args[-len(kwargs):] if kwargs else []
            args = args[:-len(kwargs)] if kwargs else args
            stack.append({'factory':target['symbol'],'args':args,'kwargs':dict(zip(kwargs,kwvalues))})
            kwargs = ()
        elif ins.opname not in ('PRECALL','PUSH_NULL','EXTENDED_ARG','CACHE','NOP'):
            raise ValueError((path, ins))
        j += 1
    handler = stack.pop()
    flags = instructions[j].arg
    annotations = stack.pop() if flags & 4 else ()
    annotation_map = dict(zip(annotations[::2],annotations[1::2]))
    defaults = stack.pop() if flags & 1 else ()
    assert not stack, (path,stack)
    params = []
    names = handler.co_varnames[:handler.co_argcount]
    for n, name in enumerate(names):
        typ = annotation_map.get(name, {'symbol':'unknown'})
        required = n < len(names)-len(defaults)
        default = None if required else defaults[n-(len(names)-len(defaults))]
        location = 'injected' if typ == {'symbol':'Request'} else 'query'
        if isinstance(default,dict) and default.get('factory') == 'Body':
            location = 'body'
        declaration = clean(default)
        validation = {}
        if isinstance(default, dict) and default.get('factory') in ('Body','Query'):
            validation = default['kwargs']
            default = default['args'][0] if default['args'] else None
            required = default is Ellipsis
            if required:
                default = None
        if location == 'injected':
            required = False
        params.append({'name':name,'type':typ['symbol'],'location':location,'required':required,'default':clean(default),
                       'validation':clean(validation),'declaration':declaration})
    if path.startswith('/dl/license'): category='license'
    elif path.startswith('/dl/update'): category='update'
    elif path.startswith('/dl/library') or path == '/dl/poster': category='library'
    elif path.startswith('/admin') or path == '/stats': category='admin'
    elif path.startswith('/dl'): category='desktop_ui'
    elif path in ('/','/ui','/img'): category='page_or_asset'
    else: category='content_api'
    routes.append({'method':method.argval.upper(),'path':path,'handler':handler.co_name,'source_line':handler.co_firstlineno,
                   'classification':category,'disassembly_line':anchors[handler.co_name], 'parameters':params,
                   'constants':clean(handler.co_consts),'names':list(handler.co_names)})
(ROOT / 'analysis/evidence/local-routes.json').write_text(json.dumps(routes,ensure_ascii=False,indent=2)+'\n')
print(f'{len(routes)} explicitly registered routes')
for r in routes:
    signature = ', '.join(f"{p['name']}:{p['type']}={p['default']!r}" for p in r['parameters'])
    print(r['method'],r['path'],r['handler'],r['source_line'],f'({signature})')
