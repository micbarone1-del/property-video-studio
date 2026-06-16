# v2 Release Test Plan
### For Claude in Chrome · Property Video Studio

Follow every step. Report PASS/FAIL after each before moving on.
Do not improvise fixes. If something fails, stop and report the full error.

---

## PRE-FLIGHT

Open the Hostinger browser terminal (hPanel → VPS → Manage → Terminal).

```bash
cd /var/www/property-video-studio && source venv/bin/activate && echo "READY"
```

PASS: shows READY
FAIL: folder missing — stop and alert user

---

## STEP 1 — Verify new files on GitHub

```bash
curl -s https://raw.githubusercontent.com/micbarone1-del/property-video-studio/main/api_server.py | grep "v3"
curl -s https://raw.githubusercontent.com/micbarone1-del/property-video-studio/main/vision_analysis.py | grep "Florence"
curl -s https://raw.githubusercontent.com/micbarone1-del/property-video-studio/main/cost_tracker.py | grep "cost_tracker"
```

PASS: all three return a matching line
FAIL: any returns nothing — files not uploaded yet. Stop and tell user.

---

## STEP 2 — Pull all files from GitHub

```bash
git pull https://micbarone1-del@github.com/micbarone1-del/property-video-studio.git main
```

PASS: output lists changed files including api_server.py, ui.html, vision_analysis.py,
      cost_tracker.py, start.sh, requirements.txt, video_generation.py
FAIL: "Already up to date" — GitHub upload incomplete
FAIL: auth error — token expired, alert user

---

## STEP 3 — Install any new dependencies

```bash
pip install -r requirements.txt
```

PASS: completes without errors
FAIL: any error — copy the error and report it before continuing

---

## STEP 4 — Make start.sh executable

```bash
chmod +x start.sh
```

---

## STEP 5 — Test the start script

Kill any existing server first:
```bash
fuser -k 8000/tcp 2>/dev/null; screen -wipe 2>/dev/null; sleep 1
```

Then run the new start script:
```bash
./start.sh
```

PASS: script prints green "✓ Server is running!" with URL
PASS: curl http://localhost:8000/health returns {"status":"ok",...}
FAIL: any red error — copy and report

---

## STEP 6 — Verify new files loaded correctly

```bash
python3 -c "from vision_analysis import analyse_input, analyse_output, analyse_tts; print('vision_analysis OK')"
python3 -c "from cost_tracker import estimate_job_cost, format_cost_display; print('cost_tracker OK')"
```

PASS: both print OK
FAIL: any ImportError — copy and report

---

## STEP 7 — Test vision analysis standalone

```bash
python3 vision_analysis.py tts /dev/null "Benvenuti in questo splendido appartamento"
```

PASS: returns JSON with verdict=reject (file doesn't exist — expected)
This confirms the module loads and TTS QC logic runs.

---

## STEP 8 — UI smoke test

Open http://187.77.196.94:8000 in browser.
Open browser console (F12 → Console tab).

PASS: page loads with dark green header
PASS: zero JavaScript errors in console
PASS: "⚙ System" button visible in header
PASS: "Auto QC" toggle visible in property details section
PASS: Cost estimate panel appears after uploading one photo
PASS: voiceover field shows character counter as you type
PASS: camera dropdown shows "⭐ Auto — adapts to room type (recommended)"

---

## STEP 9 — Test diagnostics endpoint

Click the "⚙ System" button in the header.

PASS: modal opens showing disk space, job counts, fal.ai reachable, ElevenLabs reachable
FAIL: modal shows error or doesn't open — check server logs

Also test directly:
```bash
curl http://localhost:8000/diagnostics
```
PASS: returns JSON with disk_free_gb, fal_reachable, elevenlabs_reachable fields

---

## STEP 10 — Test image analysis endpoint

Upload one photo in the UI and wait 10-30 seconds.

PASS: AI badge appears on the scene card showing detected space type
      e.g. "🏠 Grande interno" or "🏠 Balcone/Terrazza"
PASS: Camera movement dropdown auto-fills based on space type
PASS: Server logs show [Vision] Florence description: ...

FAIL: badge never appears — check server logs for [Vision] errors
NOTE: if FAL_KEY has insufficient credits, vision will fail gracefully
      and the badge simply won't appear. This is acceptable.

---

## STEP 11 — Test word count / auto-duration

In any scene card, type a voiceover sentence of about 20 words.

PASS: character counter appears (e.g. "~9s")
PASS: duration slider auto-updates to match
PASS: typing a very long text (60+ words) shows red "⚠ Testo troppo lungo" warning
PASS: duration slider caps at 20s and warning persists

---

## STEP 12 — Full pipeline test with QC

Submit a job with ONE photo:
- Property name: v2 Test QC
- Auto QC: ON
- Lighting: ON, Upscaling: OFF
- Caption: "soggiorno" (to test Italian space detection)
- Voiceover: "Benvenuti in questo splendido soggiorno luminoso"
- Camera: Auto
- Duration: 8s (should auto-fill from voiceover)

Watch server logs via:
```bash
screen -r property-video
```
(Ctrl+A then D to return)

Expected log sequence:
```
[Job xxxx] 2% — Starting pipeline…
[Job xxxx] Enhancing image 1 of 1…
[Job xxxx] Generating audio 1 of 1…
[TTS QC] verdict=pass duration=X.Xs expected=~Xs
[Job xxxx] Generating video clip 1 of 1…
[VideoGen] space=large camera=auto trajectory=horizontal_zoom_bend
[Job xxxx] QC check on clip 1 of 1…
[Vision QC] verdict=pass/flag/reject
```

PASS scenarios:
A) All QC passes → progress reaches 100% → video ready for download
B) QC flags a scene → progress pauses at 75% → QC review panel appears in UI
   → approve or redo buttons visible → clicking Assemble Video proceeds

FAIL: job shows "failed" status → copy full error from logs

---

## STEP 13 — Test rate limiting (security)

```bash
for i in {1..6}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/jobs/ \
    -F "images=@/var/www/property-video-studio/jobs/$(ls jobs/ | head -1)/images/scene_000.jpg" \
    -F 'config=[{"caption":"test","voiceover":"","duration":8,"camera_hint":"auto"}]' \
    -F 'property_name=test'
done
```

PASS: first 5 requests return 200, 6th returns 429
FAIL: all return 200 (rate limiting not working — acceptable for now, note it)

---

## STEP 14 — Commit to GitHub

```bash
cd /var/www/property-video-studio
git add -A
git commit -m "v2 release: vision QC, cost tracking, diagnostics, security, start script"
git push https://micbarone1-del@github.com/micbarone1-del/property-video-studio.git main
```

PASS: push succeeds
FAIL: auth error — alert user to renew GitHub token

---

## FINAL REPORT

```
v2 TEST REPORT
==============
Date/time:           _______________

Pre-flight:          PASS/FAIL
Step 1 GitHub:       PASS/FAIL
Step 2 Pull:         PASS/FAIL
Step 3 Deps:         PASS/FAIL
Step 4 chmod:        PASS/FAIL
Step 5 Start script: PASS/FAIL
Step 6 Imports:      PASS/FAIL
Step 7 TTS QC:       PASS/FAIL
Step 8 UI smoke:     PASS/FAIL
Step 9 Diagnostics:  PASS/FAIL
Step 10 Image AI:    PASS/FAIL/PARTIAL (no credits)
Step 11 Word count:  PASS/FAIL
Step 12 Full pipeline:
  Pipeline completed:   yes/no
  QC triggered:         yes/no
  QC verdict:           pass/flag/reject
  Video downloaded:     yes/no
Step 13 Rate limit:  PASS/FAIL/SKIPPED
Step 14 GitHub:      PASS/FAIL

Errors encountered:
[paste any errors here]

Italian space detection working: yes/no
Camera auto-fill working:        yes/no
Cost panel visible:              yes/no
Start script working:            yes/no

Overall verdict: WORKING / PARTIAL / FAILING
```
