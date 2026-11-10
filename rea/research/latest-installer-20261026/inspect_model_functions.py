"""Static listing only; no imports or execution of installer payload modules."""
import dis
import importlib.util
import json
import marshal
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
lines, index = [], {}
for module in ('hongguo', 'offline_dl'):
    raw = (ROOT / 'extracted/app' / (module + '.pyc')).read_bytes()
    assert raw[:4] == importlib.util.MAGIC_NUMBER
    root = marshal.loads(raw[16:])
    for code in root.co_consts:
        if not isinstance(code, types.CodeType):
            continue
        args = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]
        index[module + '.' + code.co_name] = dict(line=code.co_firstlineno, names=code.co_names, args=args)
        if not (code.co_name.startswith(('_vm', '_Vm')) or code.co_name in
                ('get_video_urls', 'get_video_tracks', '_video_model', '_api_once', 'resolve_down')):
            continue
        lines.extend([f'\n=== {module}.{code.co_name} source_line={code.co_firstlineno} ===', f'args={args!r}'])
        for instruction in dis.get_instructions(code):
            value = code.co_consts[instruction.arg] if instruction.opname == 'KW_NAMES' else instruction.argval
            if isinstance(value, types.CodeType):
                value = '<code ' + value.co_qualname + '>'
            lines.append(f'{instruction.offset:5} L{str(instruction.starts_line):5} {instruction.opname:32} {value!r}')
    instructions = list(dis.get_instructions(root))
    windows = set()
    for n, instruction in enumerate(instructions):
        if ('vm' in str(instruction.argval).lower() or instruction.argval == '_STRIKE_PATHS') and instruction.opname in ('STORE_NAME', 'STORE_GLOBAL', 'LOAD_CONST'):
            windows.update(range(max(0, n-8), min(len(instructions), n+4)))
    lines.append(f'\n=== {module}.module VM-related windows ===')
    for n in sorted(windows):
        instruction = instructions[n]
        value = instruction.argval
        if isinstance(value, types.CodeType):
            value = '<code ' + value.co_qualname + '>'
        lines.append(f'{instruction.offset:5} L{str(instruction.starts_line):5} {instruction.opname:32} {value!r}')
(ROOT / 'evidence/model-functions.txt').write_text('\n'.join(lines))
(ROOT / 'evidence/function-index.json').write_text(json.dumps(index, indent=2))
