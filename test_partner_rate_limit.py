"""test_partner_rate_limit.py - the partner 24h limit per agency is ONE setting (2026-10-30). No network, no app import."""
import ast, os
fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)
src = open("api_server.py", encoding="utf-8").read()
tree = ast.parse(src)
fn = next(ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "partner_agency_limit_24h")
ns = {"os": os, "PARTNER_AGENCY_LIMIT_24H_DEFAULT": 2}; exec(fn, ns); f = ns["partner_agency_limit_24h"]
old = os.environ.pop("PVS_PARTNER_AGENCY_LIMIT_24H", None)
check("R1 default is 2 (the value agreed with Relinx)", f() == 2)
os.environ["PVS_PARTNER_AGENCY_LIMIT_24H"] = "15"
check("R2 setting 15 gives 15", f() == 15)
for bad in ("abc", "", "0", "-3", "2.5"):
    os.environ["PVS_PARTNER_AGENCY_LIMIT_24H"] = bad
    check(f"R3 bad value {bad!r} falls back to 2", f() == 2)
if old is None: os.environ.pop("PVS_PARTNER_AGENCY_LIMIT_24H", None)
i = src.index("recent_relinx_jobs = sorted")
check("R4 the endpoint compares with the setting, no number 2 written in it", "len(recent_relinx_jobs) >= _limit" in src[i:i + 900] and "max 2 videos per agency per 24h (agency" not in src)
check("R5 the default constant is 2 and only one place reads the env setting", "PARTNER_AGENCY_LIMIT_24H_DEFAULT = 2" in src and src.count('os.getenv("PVS_PARTNER_AGENCY_LIMIT_24H"') == 1)
check("R6 the pilot tool uses ONE agency id for all test listings", '"agency_external_id": "gial-test"' in open("relinx_pilot_check.py", encoding="utf-8").read())
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
