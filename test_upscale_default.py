"""PVS_UPSCALE_DEFAULT: one default for URL and partner jobs (flag and cost estimate). No network."""
import ast, os
fails = []; total = 0
def check(name, cond, extra=""):
    global total
    total += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)
src = open("api_server.py").read()
fn = next(ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "default_upscale_images")
ns = {"os": os}; exec(fn, ns); f = ns["default_upscale_images"]
old = os.environ.pop("PVS_UPSCALE_DEFAULT", None)
check("U1 unset = on (behaviour unchanged)", f() is True)
for v in ("0", "false", "No", "OFF", " 0 "):
    os.environ["PVS_UPSCALE_DEFAULT"] = v
    check(f"U2 '{v}' = off", f() is False)
for v in ("1", "true", "yes", ""):
    os.environ["PVS_UPSCALE_DEFAULT"] = v
    check(f"U3 '{v}' = on", f() is True)
if old is None: os.environ.pop("PVS_UPSCALE_DEFAULT", None)
check("U4 no hard-coded upscale True left at job creation", '"upscale_images": True' not in src)
check("U5 both job creations use the helper", src.count('"upscale_images": default_upscale_images()') == 2)
check("U6 both cost estimates use the helper (flag and cost agree)", src.count("do_upscale=default_upscale_images()") == 2)
check("U7 generation and rework still read the job's own flag", src.count('do_upscale=job.get("upscale_images", True)') == 2)
check("U8 manual upload keeps its own form field", "upscale_images: bool = Form(True)" in src)
print(f"\nRESULT: {'ALL PASS' if not fails else 'FAILURES'} ({total - len(fails)}/{total})")
for n in fails: print("FAIL", n)
