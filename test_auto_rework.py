import os, sys, re
import auto_rework as ar
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
sc = [{"scene_id": f"s{i}"} for i in range(4)]
qc = lambda i, enf=True: {"scene": i, "type": "video", "standard_enforced": enf}
ok = lambda j, ids: {"allowed": True, "reasons": []}
no = lambda j, ids: {"allowed": False, "reasons": ["cap"]}
os.environ.pop("PVS_AUTO_REWORK", None)
chk("A1 switch off by default", ar.plan({}, [qc(1)], [1], [], [], sc, ok)["scene_ids"] == [])
os.environ["PVS_AUTO_REWORK"] = "1"
p = ar.plan({}, [qc(1)], [1], [], [], sc, ok)
chk("A2 measured reject only -> plan", p["scene_ids"] == ["s1"] and p["indexes"] == [1])
chk("A3 two measured rejects", ar.plan({}, [qc(0), qc(2)], [0, 2], [], [], sc, ok)["scene_ids"] == ["s0", "s2"])
chk("A4 flagged scene present -> no", ar.plan({}, [qc(1)], [1], [3], [], sc, ok)["scene_ids"] == [])
chk("A5 failed clip present -> no", ar.plan({}, [qc(1)], [1], [], [2], sc, ok)["scene_ids"] == [])
chk("A6 judge-only reject -> no", ar.plan({}, [qc(1, False)], [1], [], [], sc, ok)["scene_ids"] == [])
chk("A7 mixed measured + other reject -> no", ar.plan({}, [qc(0), qc(1, False)], [0, 1], [], [], sc, ok)["scene_ids"] == [])
chk("A8 already auto-reworked -> no", ar.plan({"auto_reworked": ["s1"]}, [qc(1)], [1], [], [], sc, ok)["scene_ids"] == [])
chk("A9 budget refuses -> no", ar.plan({}, [qc(1)], [1], [], [], sc, no)["scene_ids"] == [])
chk("A10 no rejects -> no", ar.plan({}, [], [], [], [], sc, ok)["scene_ids"] == [])
chk("A11 missing scene_id -> no", ar.plan({}, [qc(1)], [1], [], [], [{}, {}], ok)["scene_ids"] == [])
chk("A12 missing qc entry -> no", ar.plan({}, [], [1], [], [], sc, ok)["scene_ids"] == [])
src = open("api_server.py").read()
chk("A13 hook wired before the pause notification", src.index("import auto_rework as _ar") < src.index('job_id, "QC flagged"'))
chk("A14 hook uses the shared runner and sets the loop guard",
    'await _run_redo(job_id, _ap["scene_ids"]' in src and 'setdefault("auto_reworked"' in src)
import py_compile; py_compile.compile("api_server.py", doraise=True)
chk("A15 api_server compiles", True)
print("FAILS", F)
