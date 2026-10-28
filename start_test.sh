#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# start_test.sh -- THIRD instance: REAL providers (Claude etc.), but its own jobs AND data folders (2026-10-28)
#   port 8002, local only. Used for draft-level partner tests (POST /v1/videos stops in draft: no video is generated).
#   Real Claude calls cost cents; operator emails are real. The production instance (port 8000, jobs/) is not touched.
# Usage: ./start_test.sh        Stop: screen -S property-video-test -X quit
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_DIR="/var/www/property-video-studio"
VENV_DIR="$PROJECT_DIR/venv"
FAKE_JOBS="/var/www/pvs_test_jobs"
FAKE_STATE="/var/www/pvs_test_state"
PORT=8002
SCREEN_NAME="property-video-test"

cd "$PROJECT_DIR" || exit 1
mkdir -p "$FAKE_JOBS" "$FAKE_STATE"
fuser -k $PORT/tcp 2>/dev/null
screen -S "$SCREEN_NAME" -X quit 2>/dev/null
screen -wipe 2>/dev/null
sleep 1
screen -dmS "$SCREEN_NAME" bash -c "
    cd $PROJECT_DIR
    source $VENV_DIR/bin/activate
    PVS_JOBS_DIR=$FAKE_JOBS PVS_FAKE_DIR=$FAKE_STATE PVS_DATA_DIR=$FAKE_STATE/data \
      uvicorn api_server:app --host 127.0.0.1 --port $PORT 2>&1 | tee /tmp/property-video-test.log
"
sleep 5
HEALTH=$(curl -s --max-time 5 http://localhost:$PORT/health 2>/dev/null)
echo "$HEALTH"
if echo "$HEALTH" | grep -q '"fake_providers":false'; then
    echo "TEST instance OK on port $PORT (UI: http://$(hostname -I | awk '{print $1}'):$PORT)"
else
    echo "TEST instance NOT healthy -- see /tmp/property-video-test.log"
    exit 1
fi
