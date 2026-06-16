#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — Property Video Studio one-command startup
# Usage: ./start.sh
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_DIR="/var/www/property-video-studio"
VENV_DIR="$PROJECT_DIR/venv"
PORT=8000
SCREEN_NAME="property-video"
SERVER_IP=$(hostname -I | awk '{print $1}')

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Property Video Studio — Starting up"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Check project folder ──────────────────────────────────────────────
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}✗ Project folder not found: $PROJECT_DIR${NC}"
    exit 1
fi
cd "$PROJECT_DIR"
echo -e "${GREEN}✓ Project folder found${NC}"

# ── Step 2: Check .env file ───────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo -e "${RED}✗ .env file missing — copy .env.template to .env and fill in your keys${NC}"
    exit 1
fi

FAL_KEY_SET=$(grep -c "FAL_KEY=" .env)
FAL_KEY_BLANK=$(grep "FAL_KEY=your_fal_key_here" .env | wc -l)

if [ "$FAL_KEY_BLANK" -gt 0 ]; then
    echo -e "${RED}✗ FAL_KEY not set in .env — please add your fal.ai API key${NC}"
    exit 1
fi
echo -e "${GREEN}✓ API keys configured${NC}"

# ── Step 3: Activate virtual environment ──────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo -e "${YELLOW}⚠ Virtual environment not found — creating it now...${NC}"
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo -e "${GREEN}✓ Virtual environment created and libraries installed${NC}"
else
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
fi

# ── Step 4: Clear port 8000 if in use ─────────────────────────────────────────
PORT_PID=$(fuser $PORT/tcp 2>/dev/null)
if [ ! -z "$PORT_PID" ]; then
    echo -e "${YELLOW}⚠ Port $PORT in use (PID $PORT_PID) — clearing it...${NC}"
    fuser -k $PORT/tcp 2>/dev/null
    sleep 1
    echo -e "${GREEN}✓ Port $PORT cleared${NC}"
else
    echo -e "${GREEN}✓ Port $PORT is free${NC}"
fi

# ── Step 5: Kill any existing screen session ──────────────────────────────────
screen -S "$SCREEN_NAME" -X quit 2>/dev/null
screen -wipe 2>/dev/null
sleep 1

# ── Step 6: Start server in screen session ────────────────────────────────────
echo -e "${YELLOW}↑ Starting server...${NC}"
screen -dmS "$SCREEN_NAME" bash -c "
    cd $PROJECT_DIR
    source $VENV_DIR/bin/activate
    uvicorn api_server:app --host 0.0.0.0 --port $PORT 2>&1 | tee /tmp/property-video.log
"

# ── Step 7: Wait and verify ───────────────────────────────────────────────────
echo "  Waiting for server to start..."
sleep 4

HEALTH=$(curl -s --max-time 5 http://localhost:$PORT/health 2>/dev/null)
if echo "$HEALTH" | grep -q "ok"; then
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  ✓ Server is running!${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  Open in browser:  ${YELLOW}http://$SERVER_IP:$PORT${NC}"
    echo ""
    echo "  Commands:"
    echo "    View logs:   screen -r $SCREEN_NAME"
    echo "    Stop server: screen -r $SCREEN_NAME → Ctrl+C"
    echo "    Detach:      Ctrl+A then D"
    echo ""
else
    echo ""
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}  ✗ Server failed to start${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  Check the logs:"
    echo "    cat /tmp/property-video.log"
    echo "    screen -r $SCREEN_NAME"
    echo ""
    exit 1
fi
