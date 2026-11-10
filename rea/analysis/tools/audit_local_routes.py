"""Independently audit route registration without importing/executing target code."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from xdis import Bytecode, load_module
from xdis.opcodes.opcode_3x import opcode_311


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "analysis/extracted/app/server.pyc"
code = load_module(str(SERVER))[3]
instructions = [
    inst for inst in Bytecode(code, opcode_311)
    if inst.opname not in {"CACHE", "EXTENDED_ARG"}
]
methods = {"get", "post", "put", "delete", "patch", "head", "options", "route"}
exempt = next(
    inst.argval for i, inst in enumerate(instructions[:-1])
    if inst.opname == "LOAD_CONST"
    and instructions[i + 1].opname == "STORE_NAME"
    and instructions[i + 1].argval == "_EXEMPT"
)
routes = []
for i, inst in enumerate(instructions[:-2]):
    if not (
        inst.opname == "LOAD_NAME" and inst.argval == "app"
        and instructions[i + 1].opname == "LOAD_METHOD"
        and instructions[i + 1].argval in methods
    ):
        continue
    method = instructions[i + 1].argval.upper()
    path = instructions[i + 2].argval
    assert instructions[i + 2].opname == "LOAD_CONST" and isinstance(path, str)
    function = next(
        x.argval for x in instructions[i + 3:]
        if x.opname == "LOAD_CONST" and hasattr(x.argval, "co_name")
    )
    packaged = path == "/dl" or path.startswith("/dl/") or path in {"/img", "/favicon.ico"}
    if "_check_admin" in function.co_names:
        auth = "admin_token (header x-admin-token or query admin_token)"
    elif path == "/dl/status":
        auth = "UI token for full response; anonymous response only running"
    elif path == "/dl":
        auth = "anonymous page; valid query k exchanges launch token for UI cookie"
    elif path.startswith("/dl"):
        auth = "UI token (when HG_UI_TOKEN is configured)"
    elif path in exempt or path.startswith("/admin"):
        auth = "no API-key requirement"
    else:
        auth = "API key and per-key rate limit"
    routes.append({
        "method": method,
        "path": path,
        "handler": function.co_name,
        "source_line": function.co_firstlineno,
        "registration_bytecode_offset": inst.offset,
        "packaged_middleware_allowed": packaged,
        "authentication_before_handler": auth,
        "handler_argument_names": list(function.co_varnames[:function.co_argcount]),
        "handler_direct_license_calls": "LIC" in function.co_names,
    })


def walk(co):
    yield co
    for value in co.co_consts:
        if hasattr(value, "co_code"):
            yield from walk(value)


terms = {
    "FastAPI", "APIRouter", "include_router", "add_api_route", "add_route",
    "BaseModel", "Flask", "HTTPServer", "socketserver", "require_key", "uvicorn",
}
modules = []
for path in sorted((ROOT / "analysis/extracted").rglob("*.pyc")):
    # Audit shipped application modules, excluding any extracted framework pyc.
    if "/python/" in str(path):
        continue
    objects = list(walk(load_module(str(path))[3]))
    hits = []
    for obj in objects:
        matched = sorted(set(obj.co_names) & terms)
        if matched:
            hits.append({"handler": obj.co_name, "source_line": obj.co_firstlineno, "names": matched})
    modules.append({"path": str(path.relative_to(ROOT)), "code_objects": len(objects), "framework_hits": hits})

assert len({(r["method"], r["path"]) for r in routes}) == len(routes)
framework = []
for path, handler in [
    ("/openapi.json", "openapi"), ("/docs", "swagger_ui_html"),
    ("/docs/oauth2-redirect", "swagger_ui_redirect"), ("/redoc", "redoc_html"),
]:
    framework.append({
        "path": path, "methods": ["GET", "HEAD"], "handler": handler,
        "packaged_middleware_allowed": False,
        "api_key_required_in_nonpackaged_mode": path not in exempt,
        "evidence": "analysis/extracted/python/Lib/site-packages/fastapi/applications.py:1105",
    })

report = {
    "source_sha256": hashlib.sha256(SERVER.read_bytes()).hexdigest(),
    "analysis_type": "static; target code not imported or executed",
    "explicit_route_count": len(routes),
    "explicit_unique_path_count": len({r["path"] for r in routes}),
    "explicit_method_counts": dict(Counter(r["method"] for r in routes)),
    "packaged_middleware_allowed_explicit_routes": sum(r["packaged_middleware_allowed"] for r in routes),
    "framework_routes": framework,
    "routes": routes,
    "scanned_modules": modules,
    "absence_scope": "Framework-symbol check across extracted shipped application Python code objects; not a runtime proof or third-party service inventory.",
}
other = ROOT / "analysis/evidence/local-routes.json"
if other.exists():
    other_routes = json.loads(other.read_text())
    ours = {(r["method"], r["path"], r["handler"]) for r in routes}
    theirs = {(r["method"], r["path"], r["handler"]) for r in other_routes}
    report["independent_local_routes_comparison"] = {
        "missing_from_local_routes": sorted(ours - theirs),
        "extra_in_local_routes": sorted(theirs - ours),
    }
out = ROOT / "analysis/evidence/audited-routes.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k not in {"routes", "scanned_modules", "framework_routes"}}, ensure_ascii=False, indent=2))
