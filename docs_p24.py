"""docs_p24.py -- appends the 2026-11-02 prompt-form results (positive rules + described last view) and Michele's movement-progression principle to
status.md, backlog.md and AUTOMATION_TEST_PLAN.md. Append-only, idempotent (marker). Run from /var/www/property-video-studio."""
from pathlib import Path

STATUS = '''
### 2026-11-02 (tarda mattina) - Prompt in forma positiva con descrizione dell'inquadratura finale attesa (exp_prompt.py)
- Idea di Michele: invece di dare a Luma un fotogramma finale (rischio di nuovi errori), descrivere in positivo, con parole, l'inquadratura finale attesa. Implementazione sperimentale: Claude descrive in 2 frasi (max 70 parole) la regione centrale 1/scala della foto (scala 1.3 per l'avanzamento, 1.1 per la rotazione leggera); il ritaglio NON va a Luma, serve solo come fonte delle parole e viene salvato per il controllo a occhio. Le circa 15 negazioni di _LUMA_RULES sono sostituite da regole positive (foto congelata, tutto resta uguale in posto/forma/numero/stato, si muove solo la camera a velocita' costante). Stesso movimento e ritmo di produzione, stessa foto enhanced_lit.
- Risultati sul job 91056c3e (n=2 per scena, costo reale 4.40 EUR, controllo qualita' di produzione): scena 4 (bagno, subtle_rotate): pass e pass (nel giro originale il controllo aveva dato flag per il secondo rubinetto); scena 1 (soggiorno, walk_in_explore): flag minor (tavolino di vetro e mobile TV non nella foto, specchio sul muro sinistro, tavolo e sedie non piu' visibili) e reject major (mobiletto TV, tavolino, tavolo sparito, il mobile bianco diventa una specie di camino); nel giro originale: reject (tenda fantasma). Il controllo descrive in entrambi i clip della scena 1 una camera che "gira verso il divano": il token walk_in_explore dice "moving through the room" senza direzione dritta.
- NON verificato: il giudizio a occhio di Michele sui 4 clip (il controllo di produzione e' esso stesso imperfetto); n=2 non permette percentuali; l'effetto separato di regole positive generiche contro regole + descrizione; la stabilita' della descrizione tra chiamate (le due descrizioni della scena 1 differivano un poco).
'''

BACKLOG = '''
### 2026-11-02 - Principio di progressione dei movimenti (Michele) [DECISO, nessun lavoro ora]
- Prima imparare a CONTROLLARE i movimenti semplici (avanzamento dritto), poi definire come introdurre i movimenti piu' complessi. La rotazione leggera (oggi subtle_rotate nelle stanze piccole) potra' essere reintrodotta in una fase successiva, se il sistema funziona, usando un dettaglio sul lato della stanza al centro del frame esistente che permetta di andare dritti e girare leggermente dentro il frame iniziale. Da capire poi se e dove questa rotazione e' fattibile senza rischi aggiuntivi. Per ora non si lavora sulla rotazione.
### 2026-11-02 - Prompt positivo + descrizione dell'inquadratura finale: prossimo passo [PROPOSTO]
- Scena 1: provare lo stesso prompt (regole positive + descrizione) con un token di movimento positivo e dritto (STRAIGHT_MOTION in exp_prompt.py) al posto di walk_in_explore ("moving through the room"), 2 clip circa 2.2 EUR. Se vince, STRAIGHT_MOTION sostituisce camera_plan.CENTRE_MOTION (una sola implementazione). Poi eventuale integrazione in produzione dietro interruttore, con piano e commit di rollback concordati.
'''

PLAN = '''

## 2026-11-02 (late morning) — Positive prompt + described last view: tests (PROPOSALS, scores not reviewed)
- T-H11 positive rules + Claude description of the expected last view, Luma ray-3.2 1080p, production clip QC as judge, n=2 per scene, job 91056c3e: scene 4 pass, pass (baseline flag: second tap); scene 1 flag, reject (baseline reject: ghost curtain). Human check of the 4 clips by Michele: NOT YET RECORDED. T-H12 same plus a positive straight movement token on scene 1: NOT RUN.
- Row Q12 (ghost animation / invented elements) stays open (S8 O5 D5 = 200, ACT, proposal): the bathroom improved in 2/2, the living room did not (0/2 pass), and the judge is the imperfect production QC; no rate can be claimed from n=2.
- Scores remain proposals until reviewed by the user; scoreboard totals NOT recomputed here.
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("Prompt in forma positiva con descrizione dell'inquadratura finale attesa", "Principio di progressione dei movimenti", "Positive prompt + described last view")

for (name, text), mark in zip(JOBS, MARK):
    p = Path(name)
    cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the entry, left as it is")
        continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
