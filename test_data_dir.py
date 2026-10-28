import os, sys, subprocess, glob
HERE = os.path.dirname(os.path.abspath(__file__))
res = []


def check(name, ok):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


def paths(env_value):
    env = dict(os.environ)
    env.pop("PVS_DATA_DIR", None)
    if env_value:
        env["PVS_DATA_DIR"] = env_value
    code = "import cost_model, partner_api; print(cost_model.AGENCIES_FILE); print(cost_model.SALES_FILE); print(partner_api.PARTNERS_FILE)"
    out = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env, capture_output=True, text=True)
    return out.stdout.split()


p = paths(None)
check("D1 default: agencies, sales and partner keys stay next to the code (production unchanged)", len(p) == 3 and all(os.path.dirname(x) == HERE for x in p))
p = paths("/tmp/pvs_data_dir_test")
check("D2 with PVS_DATA_DIR: all three move to that folder", len(p) == 3 and all(os.path.dirname(x) == "/tmp/pvs_data_dir_test" for x in p))
src = [open(f).read() for f in glob.glob(os.path.join(HERE, "*.py")) if not os.path.basename(f).startswith(("test_", "listing_scraper_new"))]
check("D3 one place decides the folder: the variable is read in exactly one module", sum(s.count("getenv(" + chr(34) + "PVS_DATA_DIR" + chr(34) + ")") for s in src) == 1)
api = open(os.path.join(HERE, "api_server.py")).read()
check("D4 the fake instance refuses to start on the real data files", "PVS_FAKE_PROVIDERS=1 requires PVS_DATA_DIR" in api)
fake = open(os.path.join(HERE, "start_fake.sh")).read()
check("D5 start_fake.sh gives the fake instance its own data folder", "PVS_DATA_DIR=$FAKE_STATE/data" in fake)
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
