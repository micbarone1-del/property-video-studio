"""add_labels_1105.py - writes Michele's blind labels of round 6 (run 1105_093032) into motion_labels.json (2026-11-05).
Same format as the other runs: bad / part / ok per code. Safe to run twice (the run entry is replaced). Prints the counts.
  python3 add_labels_1105.py [--file motion_labels.json]
The classes come from Michele's words of 2026-11-05: bad = hallucination, rotation out of frame, backward showing a room, a new object; part = passable / a bit fast / risky but ok;
ok = ok (also 'almost static'). Correct any code by editing the lists below."""
import json, sys
from pathlib import Path
RUN = "1105_093032"
BAD = "opo yds twv wdf rvv upt jpw uac cep cis qus xzk vrx wik".split()
PART = "yrn vvl ens zge ets bxj haj kxu".split()
OK = ("ncl ovb smz njy ubt jie dlt qvf euu cdf toc ibu nwu nda ctd caq bcv ksf rfw qfm fgs oga "
      "goj tfo kgx lhv lai igq xvn vnd mbo fah ael pod").split()
def merge(path: Path) -> dict:
    allc = BAD + PART + OK
    assert len(allc) == len(set(allc)), "a code is in two classes"
    d = json.loads(path.read_text())
    d[RUN] = {"bad": BAD, "part": PART, "ok": OK}
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    return {"bad": len(BAD), "part": len(PART), "ok": len(OK), "total": len(allc)}
if __name__ == "__main__":
    f = Path(sys.argv[sys.argv.index("--file") + 1]) if "--file" in sys.argv else Path(__file__).resolve().parent / "motion_labels.json"
    print(RUN, merge(f))
