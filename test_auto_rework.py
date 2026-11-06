import os, sys, re
import auto_rework as ar
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
sc = [{"scene_id": f"s{i}"} for i in range(4)]
qc = lambda i, enf=True: {"scene": i, "type": "video", "verdict": "reject", "standard_enforced": enf}
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
chk("A6 reject of the existing QC (not measured) -> plan", ar.plan({}, [qc(1, False)], [1], [], [], sc, ok)["scene_ids"] == ["s1"])
chk("A7 measured + existing-QC reject together -> both", ar.plan({}, [qc(0), qc(1, False)], [0, 1], [], [], sc, ok)["scene_ids"] == ["s0", "s1"])
chk("A7b entry that is not a reject -> no", ar.plan({}, [dict(qc(1), verdict="flag")], [1], [], [], sc, ok)["scene_ids"] == [])
chk("A8 already auto-reworked -> no", ar.plan({"auto_reworked": ["s1"]}, [qc(1)], [1], [], [], sc, ok)["scene_ids"] == [])
chk("A9 budget refuses -> no", ar.plan({}, [qc(1)], [1], [], [], sc, no)["scene_ids"] == [])
chk("A10 no rejects -> no", ar.plan({}, [], [], [], [], sc, ok)["scene_ids"] == [])
chk("A11 missing scene_id -> no", ar.plan({}, [qc(1)], [1], [], [], [{}, {}], ok)["scene_ids"] == [])
chk("A12 missing qc entry -> no", ar.plan({}, [], [1], [], [], sc, ok)["scene_ids"] == [])
src = open("api_server.py").read()
chk("A13 hook wired before the pause notification", src.index("import auto_rework as _ar") < src.index('job_id, "QC flagged"'))
chk("A14 hook uses the shared runner and sets the loop guard",
    'await _run_redo(job_id, _ap["scene_ids"]' in src and 'setdefault("auto_reworked"' in src)

fq = lambda i, **k: dict({"scene": i, "type": "video", "severity": "minor", "people_detected": False, "space_matches": True, "issues": ["x"]}, **k)
os.environ.pop("PVS_AUTO_APPROVE_FLAGS", None)
chk("B1 flags: switch off by default", ar.approvable_flags([fq(1)], [1]) == [])
os.environ["PVS_AUTO_APPROVE_FLAGS"] = "1"
chk("B2 minor flag approvable", ar.approvable_flags([fq(1)], [1]) == [1])
chk("B3 two minor flags", ar.approvable_flags([fq(1), fq(2)], [1, 2]) == [1, 2])
chk("B4 major flag -> none", ar.approvable_flags([fq(1, severity="major")], [1]) == [])
chk("B5 people -> none", ar.approvable_flags([fq(1, people_detected=True)], [1]) == [])
chk("B6 other space -> none", ar.approvable_flags([fq(1, space_matches=False)], [1]) == [])
chk("B7 QC error -> none", ar.approvable_flags([fq(1, error="x")], [1]) == [])
chk("B8 all-or-none: one bad flag blocks all", ar.approvable_flags([fq(1), fq(2, severity="major")], [1, 2]) == [])
chk("B9 missing qc entry -> none", ar.approvable_flags([fq(1)], [1, 2]) == [])
chk("B10 no flags -> none", ar.approvable_flags([], []) == [])
rr = ar.review_record([fq(1)], [1])
chk("B11 review record", rr == [{"scene": 1, "severity": "minor", "issues": ["x"]}])
chk("B12 flags cleared + measured reject -> plan ok", ar.plan({}, [qc(1)], [1], [], [], sc, ok)["scene_ids"] == ["s1"])
chk("B13 wiring: auto-approval in gate, only without failed, endpoints exist",
    "_ar0.approvable_flags(qc_results, flagged_scenes)" in src and "if not failed_scenes:" in src
    and '"/operator/review-queue"' in src and '"/jobs/{job_id}/review-done"' in src
    and "([] if _cleared else flagged_scenes)" in src)
chk("B14 approval only when no reject: reject keeps the pause", "if _cleared and not rejected_scenes:" in src)
chk("B15 rework QC gate: minor flags left after a rework are auto-approved, then reassembly",
    "_arq.approvable_flags(job.get(\"qc_results\") or [], qc[\"flagged\"])" in src and "if not qc[\"rejected\"] and qc[\"flagged\"]:" in src)
chk("B16 auto-approval record merges, does not overwrite", "_prev + _ar.review_record" in src)
chk("B17 flag that speaks of a possible human figure -> never approved", ar.approvable_flags([fq(1, issues=["Possibile figura umana poco chiara (puo essere una texture)"])], [1]) == [])
chk("B18 structure flag stays approvable", ar.approvable_flags([fq(1, issues=["Struttura/arredo diverso dalla foto: a window appears"])], [1]) == [1])
chk("B19 one person-flag blocks the whole set (all or none)", ar.approvable_flags([fq(1), fq(2, issues=["persona nel frame"])], [1, 2]) == [])
import py_compile; py_compile.compile("api_server.py", doraise=True)
chk("A15 api_server compiles", True)
print("FAILS", F)
