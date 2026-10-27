import re
import sys
import cost_tracker
q = chr(34)
res = []
def check(name, ok):
    res.append(ok)
    print(("PASS " if ok else "FAIL ") + name)
ui = open("ui.html").read()
api = open("api_server.py").read()
check("I1 the page has no hard-coded infra numbers", not re.search(r"34\.79\s*/\s*20", ui))
check("I2 the page reads the infra cost from the server", "/cost/infra" in ui and "infraCostPerJob" in ui)
check("I3 the endpoint exists and uses the shared rolling count", "/cost/infra" in api and "_get_rolling_monthly_job_count()" in api.split("/cost/infra")[1][:600])
check("I4 backend maths: 4 jobs -> monthly cost / 4", abs(cost_tracker.get_infra_cost_per_job(4) - cost_tracker.VPS_MONTHLY_EUR / 4) < 1e-9)
check("I5 no job yet -> the documented fallback", abs(cost_tracker.get_infra_cost_per_job(0) - cost_tracker.VPS_MONTHLY_EUR / cost_tracker.MONTHLY_JOBS_DEFAULT) < 1e-9)
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
