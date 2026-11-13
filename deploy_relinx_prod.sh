#!/bin/bash
# deploy_relinx_prod.sh - NEW 2026-11-13. Moves PRODUCTION to the flow tested on the test instance, for the Relinx API test.
# Usage (after the git pull):  bash deploy_relinx_prod.sh [alt]      alt = also switch the automatic alternative photo ON
# Never touches jobs/ except the release-mode file written through the app's own endpoint. No secrets in this file.
PROJECT_DIR="/var/www/property-video-studio"
cd "$PROJECT_DIR" || exit 1
ALT=0; [ "${1:-}" = "alt" ] && ALT=1
step() { printf '\033[1;42;30m %s \033[0m\n' "$1"; }
stop() { printf '\033[1;41;37m STOP: %s \033[0m\n' "$1"; exit 1; }

step "1/7 jobs running in production"
RUNNING=$(python3 - <<'PY'
import json, glob
n = 0
for f in glob.glob("jobs/*/job_meta.json"):
    try:
        if json.load(open(f)).get("status") in ("running", "queued"):
            n += 1
    except Exception:
        pass
print(n)
PY
)
[ "$RUNNING" = "0" ] || stop "$RUNNING job(s) running or queued in production: wait, a restart would interrupt them"
echo "none running"

step "2/7 rollback point"
ROLLBACK=$(cat /root/pvs_rollback_hash.txt 2>/dev/null)
[ -n "$ROLLBACK" ] || stop "/root/pvs_rollback_hash.txt missing: it must be written BEFORE the git pull"
echo "rollback commit: $ROLLBACK   (to go back: git checkout --detach $ROLLBACK && ./start.sh)"
echo "now at: $(git rev-parse --short HEAD)"

step "3/7 the new code is on disk"
grep -q "CENTRAL_X_MIN" movement_director.py || stop "director fix not on disk (movement_director.py)"
grep -q "PVS_AUTO_START_MAX_ACTIVE" start.sh || stop "start.sh does not carry the production switches (upload the updated start.sh)"
[ -f release_rule.py ] && grep -q "_release_ready_tick" api_server.py || stop "api_server.py / release_rule.py not updated (the ready-to-release notice is missing)"
echo "director fix, start.sh switches and the release notice are in place"

step "4/7 syntax checks"
source venv/bin/activate
python3 -m py_compile api_server.py release_rule.py movement_director.py scene_rework.py alt_photo_rework.py auto_start.py clip_standard.py || stop "py_compile failed"
if command -v node >/dev/null 2>&1; then
  python3 - <<'PY'
import re
s = open("ui.html", encoding="utf-8").read()
blocks = re.findall(r"<script[^>]*>(.*?)</script>", s, re.S)
open("/tmp/ui_check.js", "w", encoding="utf-8").write("\n".join(blocks))
PY
  node --check /tmp/ui_check.js || stop "ui.html script block does not parse"
else
  echo "node not found: ui.html syntax not checked"
fi
echo "python and ui syntax OK"

step "5/7 per-deploy values and restart"
NB=$(date -u +%Y-%m-%dT%H:%M:%S)
printf 'PVS_AUTO_START_NOT_BEFORE=%s\nPVS_AUTO_ALT_PHOTO=%s\n' "$NB" "$ALT" > /root/pvs_overrides.env
echo "auto-start only for drafts created after $NB (UTC); automatic alternative photo: $ALT"
chmod +x start.sh
./start.sh || stop "start.sh reported a failure: see /tmp/property-video.log"

step "6/7 release mode = manual (the agency gets nothing until you release)"
KEY=$(grep '^UI_ACCESS_KEY=' .env | cut -d= -f2- | tr -d "\"' ")
curl -s -m 10 -X POST http://127.0.0.1:8000/operator/release-mode -H "X-Access-Key: $KEY" -F mode=manual; echo

step "7/7 what production really runs with"
curl -s -m 5 http://127.0.0.1:8000/health; echo
PID=$(fuser 8000/tcp 2>/dev/null | awk '{print $1}')
echo "server pid: $PID, commit: $(git rev-parse --short HEAD)"
tr '\0' '\n' < /proc/$PID/environ | grep -E '^PVS_(LUMA_RESOLUTION|AUTO_|PARTNER|PACE|ARRIVAL|NARRATION|ACCEPT|DIRECTOR|STANDARD|ANCHOR)' | sort
grep -h -E "\[Release\] mode|auto.start" /tmp/property-video.log | tail -3 | cut -c1-160
printf '\033[1;42;30m DEPLOY DONE \033[0m\n'
