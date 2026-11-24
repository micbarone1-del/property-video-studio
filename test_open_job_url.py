"""2026-11-24: link dashboard -> app (/?job=ID) and app -> dashboard. Runs the REAL openJobFromUrl() taken from ui.html in node with stubs."""
import re, subprocess, sys, json, tempfile, os
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)
ui = open("ui.html", encoding="utf-8").read()
op = open("operator_page.html", encoding="utf-8").read()
m = re.search(r"function openJobFromUrl\(\) \{.*?\n\}\n", ui, re.S)
chk("L1 openJobFromUrl exists in ui.html and showApp calls it", bool(m) and re.search(r"function showApp\(\)[^}]*openJobFromUrl\(\);", ui, re.S))
def run(search):
    js = "const calls=[]; global.location={search:%s,pathname:'/'}; global.history={replaceState:(a,b,c)=>calls.push(['replace',c])};\n" % json.dumps(search)
    js += "global.editJob=(a,b)=>calls.push(['edit',a,b]); global.showError=(m)=>calls.push(['err',m]);\n" + m.group(0) + "\nopenJobFromUrl(); console.log(JSON.stringify(calls));"
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False); f.write(js); f.close()
    r = subprocess.run(["node", f.name], capture_output=True, text=True); os.remove(f.name)
    return json.loads(r.stdout.strip() or "null")
chk("L2 no parameter: nothing happens", run("") == [])
chk("L3 ?job=abc12345 opens the job with the editJob path and cleans the address", run("?job=abc12345") == [["replace", "/"], ["edit", "abc12345", "abc12345"]])
chk("L4 a rework id keeps its base id", run("?job=abc12345_rw2")[1] == ["edit", "abc12345_rw2", "abc12345"])
chk("L5 a hostile value is refused, never reaches editJob", all(c[0] != "edit" for c in run("?job=" + "%3Cscript%3E")) and any(c[0] == "err" for c in run("?job=" + "%3Cscript%3E")))
chk("L6 the header has the dashboard button", 'id="dash-btn" onclick="location.href=\'/operator-page\'"' in ui)
chk("L7 dashboard: a link to the app on every job row and on inbox items", op.count("/?job=' + encodeURIComponent(") == 2)
print("RESULT:", "ALL PASS" if ok else "FAILURES"); sys.exit(0 if ok else 1)
