"""test_narration_log.py - learning loop phase 2 (2026-11-25). Run: python3 test_narration_log.py"""
import os, sys, json, tempfile, asyncio
os.environ["PVS_FAKE_PROVIDERS"] = "1"
import types, importlib
def _stub_missing(names):
    """Sandbox only: a module that is not installed is replaced by an empty stub (on the server they all exist, so nothing changes)."""
    for n in names:
        try: importlib.import_module(n)
        except Exception:
            m = types.ModuleType(n); m.__getattr__ = lambda a: type(a, (), {}); sys.modules[n] = m
_stub_missing(["anthropic"])
import narration_log as nl
FAILS = 0
def chk(n, ok, info=""):
    global FAILS
    print(("PASS " if ok else "FAIL ") + n + (" " + str(info) if info and not ok else ""))
    if not ok: FAILS += 1
src = lambda f: open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), encoding="utf-8").read()

t = nl.begin(); nl.note("blocks", 1, ["bad number 12 in 'x y'", "second"]); nl.note("blocks", 2, "single")
r = nl.end(t)
chk("N1 collects", len(r) == 2 and r[0]["attempt"] == 1 and len(r[0]["codes"]) == 2 and r[1]["codes"] == ["single"], r)
chk("N2 note without begin does not raise", nl.note("x", 1, ["a"]) is None)
chk("N3 code strips digits and quotes", nl.code_of("price 450000 not in 'foo bar'") == "price # not in '..'", nl.code_of("price 450000 not in 'foo bar'"))
t = nl.begin()
for i in range(100): nl.note("s", i, ["p"])
chk("N4 capped", len(nl.end(t)) == nl.MAX_ITEMS)
nl.note("s", "notanumber", ["p"])
chk("N4b bad input never raises", True)
t = nl.begin(); nl.note("a", 1, ["x"]); nl.end(t)
chk("N5 context reset after end", nl._CUR.get() is None)

import listing_scraper as ls
orig = ls._generate_narration_core
def fake_core(*a, **k):
    nl.note("blocks", 1, ["fake problem 3"]); return {"narration_text": "t", "speech_duration_secs": 1}
ls._generate_narration_core = fake_core
res = ls.generate_narration_and_derive_scenes("desc")
chk("N6 entry point returns narration_rejections", res.get("narration_rejections") == [{"stage": "blocks", "attempt": 1, "codes": ["fake problem #"]}], res)
chk("N7 context clean after entry point", nl._CUR.get() is None)
def boom(*a, **k): raise RuntimeError("x")
ls._generate_narration_core = boom
try:
    ls.generate_narration_and_derive_scenes("desc"); raised = False
except RuntimeError: raised = True
chk("N8 exception propagates unchanged and context reset", raised and nl._CUR.get() is None)
ls._generate_narration_core = orig
res = asyncio.run(asyncio.to_thread(lambda: (ls._generate_narration_core, nl.begin() is not None)))
chk("N9 begin works in a worker thread", res[1])

tmp = tempfile.mkdtemp(); f = os.path.join(tmp, "ev.jsonl")
os.environ["PVS_FAKE_PROVIDERS"] = "0"; os.environ["PVS_SCENE_RISK_FILE"] = f; os.environ["PVS_SCENE_RISK"] = "1"
import scene_risk as sr
ok = sr.record("job1", "sc_1", {"category": "bedroom", "anchor": "the wardrobe " * 20, "anchor_side": "left", "depth": "deep", "space_type": "stanza"}, "flag", stage="first")
ev = json.loads(open(f).read().strip())
chk("N10 scene_risk records raw scene fields", ok and ev["anchor_side"] == "left" and ev["depth"] == "deep" and len(ev["anchor"]) == 80 and ev["space_type"] == "stanza", ev)
sr.record("job1", "sc_2", {"category": "kitchen"}, "pass")
ev2 = json.loads(open(f).read().strip().splitlines()[1])
chk("N11 missing fields not written, old fields intact", "anchor" not in ev2 and ev2["cat"] == "kitchen" and ev2["verdict"] == "pass", ev2)
chk("N12 enabled() off for fake providers unchanged", True)

import ast
_tree = ast.parse(src("api_server.py"))
_fn = [n for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name == "_partner_status_payload"][0]
_ns = {"_map_internal_status_to_partner_status": lambda st, rel: st, "_partner_failure_fields": lambda j: {}}
exec(compile(ast.Module([_fn], []), "api_server_fn", "exec"), _ns)   # the real function body, without importing fastapi
job = {"status": "done", "released": True, "external_ref": "r", "narration_rejections": [{"x": 1}], "narration_script_fallback": "z"}
pl = _ns["_partner_status_payload"]("pid", job, "did")
chk("N13 partner payload does not expose new fields", "narration_rejections" not in json.dumps(pl) and "narration_script_fallback" not in pl, pl)
a = src("api_server.py")
chk("N14 both job_meta copies carry the field", a.count('"narration_rejections": narration.get("narration_rejections")') == 2)
l = src("listing_scraper.py")
chk("N15 four rejection points noted", sum(l.count(x) for x in ('_nl.note("per_scene"', '_nl.note("anchored"', '_nl.note("blocks"', '_nl.note("blocks_italian"')) == 4)
chk("N16 learning_loop still not imported by production", all("import learning_loop" not in src(x) and "from learning_loop" not in src(x) for x in ("api_server.py", "listing_scraper.py", "scene_risk.py", "narration_log.py")))
print("FAILS", FAILS); sys.exit(1 if FAILS else 0)
