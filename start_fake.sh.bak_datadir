#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# start_fake.sh -- SECOND instance with FAKE providers (backlog 58a)
#   port 8001, own jobs folder, zero cost, nothing leaves the machine
#   (no fal/Luma/ElevenLabs/Claude call, no real email/push/webhook).
# The real instance (start.sh, port 8000, jobs/) is not touched.
# Usage: ./start_fake.sh        Stop: screen -S property-video-fake -X quit
# Faults: edit /var/www/pvs_fake_state/faults.json (see fake_providers.py).
# What would have left the machine: /var/www/pvs_fake_state/outbox.jsonl
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_DIR="/var/www/property-video-studio"
VENV_DIR="$PROJECT_DIR/venv"
FAKE_JOBS="/var/www/pvs_fake_jobs"
FAKE_STATE="/var/www/pvs_fake_state"
PORT=8001
SCREEN_NAME="property-video-fake"

cd "$PROJECT_DIR" || exit 1
mkdir -p "$FAKE_JOBS" "$FAKE_STATE"
fuser -k $PORT/tcp 2>/dev/null
screen -S "$SCREEN_NAME" -X quit 2>/dev/null
screen -wipe 2>/dev/null
sleep 1
screen -dmS "$SCREEN_NAME" bash -c "
    cd $PROJECT_DIR
    source $VENV_DIR/bin/activate
    PVS_FAKE_PROVIDERS=1 PVS_JOBS_DIR=$FAKE_JOBS PVS_FAKE_DIR=$FAKE_STATE \
      uvicorn api_server:app --host 0.0.0.0 --port $PORT 2>&1 | tee /tmp/property-video-fake.log
"
sleep 5
HEALTH=$(curl -s --max-time 5 http://localhost:$PORT/health 2>/dev/null)
echo "$HEALTH"
if echo "$HEALTH" | grep -q '"fake_providers":true'; then
    echo "FAKE instance OK on port $PORT (UI: http://$(hostname -I | awk '{print $1}'):$PORT)"
else
    echo "FAKE instance NOT healthy -- see /tmp/property-video-fake.log"
    exit 1
fi
