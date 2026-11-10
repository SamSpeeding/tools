"""Read CPython 3.11 code objects without importing/executing target code."""
import difflib
import dis
import hashlib
import importlib.util
import json
import marshal
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = Path('/Users/tt/Desktop/rea/research/latest-installer-20261014/extracted')
NEW = ROOT / 'extracted'
OUT = ROOT / 'evidence/bytecode'
OUT.mkdir(parents=True, exist_ok=True)


def load(path):
    raw = path.read_bytes()
    assert raw[:4] == importlib.util.MAGIC_NUMBER
    return marshal.loads(raw[16:]), raw


def norm(code, semantic=False):
    changes = dict(co_filename='<normalized>', co_consts=tuple(norm(c, semantic) if isinstance(c, types.CodeType) else c for c in code.co_consts))
    if semantic:
        changes.update(co_firstlineno=1, co_linetable=b'')
    return code.replace(**changes)


def walk(code):
    yield code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from walk(c)


def val(x):
    if isinstance(x, types.CodeType):
        return {'type':'code_ref','name':x.co_qualname}
    if isinstance(x, bytes):
        return {'type':'bytes','hex':x.hex()}
    if isinstance(x, tuple):
        return {'type':'tuple','value':[val(c) for c in x]}
    if isinstance(x, frozenset):
        return {'type':'frozenset','value':sorted([val(c) for c in x], key=repr)}
    return {'type':type(x).__name__,'value':repr(x)}


def own(code):
    return {key:val(getattr(code,key)) for key in (
        'co_argcount','co_posonlyargcount','co_kwonlyargcount','co_nlocals',
        'co_stacksize','co_flags','co_code','co_consts','co_names',
        'co_varnames','co_freevars','co_cellvars','co_exceptiontable','co_name','co_qualname')}


def indexed(code):
    result={}
    counts={}
    for c in walk(code):
        k=c.co_qualname
        counts[k]=counts.get(k,0)+1
        result[k+'#'+str(counts[k])]=c
    return result


def listing(c):
    lines=[f'function: {c.co_qualname}',f'source_line: {c.co_firstlineno}']
    for ins in dis.get_instructions(c):
        arg=repr(ins.argval) if ins.arg is not None else ''
        if isinstance(ins.argval, types.CodeType):
            arg='<code '+ins.argval.co_qualname+'>'
        lines.append(f'{ins.offset:6} {ins.opname:32} {arg}')
    return '\n'.join(lines)+'\n'


report=[]
for path in sorted(NEW.rglob('*.pyc')):
    rel=path.relative_to(NEW)
    if not (OLD/rel).exists():
        continue
    a,ab=load(OLD/rel);b,bb=load(path)
    am=indexed(a);bm=indexed(b)
    changed=[]
    for k in sorted(am.keys() & bm.keys()):
        fields=[f for f in own(am[k]) if own(am[k])[f]!=own(bm[k])[f]]
        if fields:
            changed.append(dict(function=k,fields=fields,old_line=am[k].co_firstlineno,new_line=bm[k].co_firstlineno))
    tag=str(rel).replace('/','__')
    if changed:
        left='\n'.join(listing(am[x['function']]) for x in changed)
        right='\n'.join(listing(bm[x['function']]) for x in changed)
        (OUT/(tag+'.old.txt')).write_text(left)
        (OUT/(tag+'.new.txt')).write_text(right)
        (OUT/(tag+'.diff')).write_text(''.join(difflib.unified_diff(left.splitlines(True),right.splitlines(True),fromfile='previous-1.0.0.73/'+str(rel),tofile='new-20261016/'+str(rel))))
    rec=dict(path=str(rel),old_sha256=hashlib.sha256(ab).hexdigest(),new_sha256=hashlib.sha256(bb).hexdigest(),
        header_equal=ab[:16]==bb[:16],old_filename=a.co_filename,new_filename=b.co_filename,
        filename_normalized_equal=norm(a)==norm(b),
        code_without_source_location_equal=norm(a,True)==norm(b,True),
        old_code_objects=len(am),new_code_objects=len(bm),
        added=sorted(bm.keys()-am.keys()),removed=sorted(am.keys()-bm.keys()),changed=changed)
    report.append(rec)
(ROOT/'evidence/bytecode-diff.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
for r in report:
    print(r['path'], 'UNCHANGED' if r['code_without_source_location_equal'] else 'CHANGED', json.dumps(r['changed'],ensure_ascii=False))
