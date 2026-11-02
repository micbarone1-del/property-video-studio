"""docs_p25.py -- appends the 2026-11-02 (late morning) decisions and code changes to status.md, backlog.md and AUTOMATION_TEST_PLAN.md.
Append-only, idempotent (marker). Run from /var/www/property-video-studio AFTER docs_p24.py."""
from pathlib import Path

STATUS = '''
### 2026-11-02 (11:00) - Seconda foto vera come fotogramma finale, assemblaggio completo, retention, prompt positivo come standard
- Decisione di Michele: gli elementi COERENTI che emergono dallo spostamento della camera (es. il tavolino dietro il tavolo da pranzo) sono accettabili; al cliente si manda un disclaimer. Il test con push-in dritto sulla scena 1 (blocco 329, ~2.2 EUR) e' ANNULLATO.
- Evidence: exp_pairs.py (gratuito, locale, sola lettura) sul job 91056c3e: 0 foto su 6 hanno una foto partner con almeno 40 punti condivisi (4-16 punti; soglia 40 = PROPOSTA). L'annuncio ha una foto per ambiente. Per questo annuncio la "seconda foto vera" non e' applicabile. NON verificato su altri annunci: la frequenza reale non e' nota.
- Evidence: assemblaggio del job 91056c3e con clip ESISTENTI (costo di generazione 0, POST /jobs/91056c3e/narration/reassemble sull'istanza di test): stato done. Clip usati: produzione del 30/10 per le scene 0, 2, 3, 5; clip positivi+descritti (ultimi) per scena 1 (soggiorno, ...1793610974) e scena 4 (bagno, ...1793611266), copiati in clips/<scene_id>.mp4 senza toccare gli originali scene_001/004. La scena 0 (esterno) ha un clip rifiutato dal controllo di produzione e nessuna versione positiva. Il giudizio di Michele sul video: NON ancora dato.
- Evidence: disco del server 24% (44G/197G); jobs 1.9G (50 cartelle), pvs_test_jobs 590M, backup /var/backups/pvs_jobs 32G (30 giorni di snapshot, ~16 volte il peso dei job).
- Codice scritto (NON ancora deployato, NON ancora eseguito sul server): (1) retention_policy.py: la pulizia dei job non cancella piu' dopo 7 giorni; cancella solo con disco >= 80%, i job fermi da piu' tempo per primi, fino al 65%; mai: job con flag "keep", job running/queued, job con attivita' negli ultimi 14 giorni. Soglie = PROPOSTE, da rivedere col volume giornaliero, modificabili con PVS_RETENTION_HIGH_PCT / LOW_PCT / MIN_DAYS. Una sola regola usata da api_server (/diagnostics) e maintenance_scheduler (prima c'erano due copie del 7). Endpoint POST /jobs/{id}/keep e bottone Tieni/Tenuto nella library. Test sandbox: test_retention_policy.py 12/12 PASS.
- Codice scritto (NON deployato): (2) described_view.py: prompt positivo + descrizione dell'inquadratura finale attesa come STANDARD per i clip Luma (PVS_POSITIVE_PROMPT=0 torna alle regole vecchie; qualsiasi fallimento della descrizione = regole vecchie per quel clip). Un solo punto di chiamata in video_generation.generate_video_single (prima generazione e rework), movimento ricavato dallo stesso remap del prompt (_remap_movement, estratto senza cambiare comportamento), prompt esatto e descrizione salvati accanto al clip (<clip>.view.json), costo Claude reale aggiunto al claude_usage del job in entrambi i percorsi. Test sandbox: test_described_view.py 24/24 PASS. Suite esistente nella sandbox: gli stessi 10 file falliscono prima e dopo (mancano moduli nella sandbox); da rilanciare sul server.
- NON verificato: le scene outdoor/elevated con la parola "scene" al posto di "room" non sono mai state generate con il prompt positivo; il costo reale della descrizione (stimato pochi centesimi per clip); nessun clip generato con questo codice.
'''

BACKLOG = '''
### 2026-11-02 - Elementi coerenti emergenti accettati + disclaimer al cliente [DECISO, testo da definire]
- Decisione di Michele: con una sola foto per ambiente, Luma puo' mostrare elementi coerenti ma non presenti nella foto (es. un tavolino dietro il tavolo). Sono accettabili. Al cliente si invia un disclaimer che lo dice. Da definire: testo (IT/EN), dove compare (report/email/API partner), eventuale campo nel payload Relinx. Il QC di produzione non deve rifiutare un clip solo per questo (da verificare con le regole di clip_qc_verdict).
### 2026-11-02 - Seconda foto vera come fotogramma finale [PARCHEGGIATO]
- exp_pairs.py: 0/6 sul job 91056c3e. Rivalutare solo se su altri annunci (lancio gratuito di exp_pairs) emergono coppie con >= 40 punti condivisi. Con una sola foto: nessun fotogramma finale e disclaimer. Un eventuale clip di prova A->B costerebbe ~1.1 EUR e richiede l'ok di Michele.
### 2026-11-02 - Retention della library basata sulla capacita' del disco [CODICE SCRITTO, NON DEPLOYATO]
- Requisito: i video possono servire per GIAL; non devono sparire. Regola in retention_policy.py (vedi status.md). Soglie 80/65/14 giorni = proposte, da rivedere col volume giornaliero. Flag keep + bottone Tieni nella library. Aperto: il backup in /var/backups/pvs_jobs pesa 32G e cresce piu' dei job (snapshot giornalieri, 30 giorni): controllare la crescita prima che riempia il disco; il cleanup non lo tocca. Aperto: nessun soft-delete (spostare nella stessa partizione non libera spazio): il recupero dopo una cancellazione e' il backup notturno.
### 2026-11-02 - Prompt positivo con descrizione come standard [CODICE SCRITTO, NON DEPLOYATO]
- Requisito di Michele: standard dal prossimo video, attivo di default. Dettagli in status.md. Da fare dopo il deploy: un video completo end-to-end su un annuncio, giudizio a occhio di Michele accanto al verdetto del QC, costo reale della descrizione, test su scene outdoor/elevated.
### 2026-11-02 - Test di automazione completa: almeno 5 video senza interferenza [RICHIESTO, NON SCOPERTO]
- Requisito di Michele: produrre almeno 5 video in sequenza, senza che lui intervenga, con qualita' accettabile. Aperto: cosa fa il sistema quando il QC segnala (flag/reject) oggi si ferma in awaiting_scenes e serve /approve; serve la regola di scarto e rework automatico (1 tentativo poi escalation, rework_policy) o l'accettazione automatica dei flag; criterio di "qualita' accettabile"; quali 5 annunci; budget massimo; come si riceve il report finale. Parallelismo: per ora una coda di job (la milestone coda/dashboard autonoma esiste gia' in backlog); non si prevede generazione parallela delle clip dello stesso job.
'''

PLAN = '''

## 2026-11-02 (late morning) — Retention by disk capacity, positive prompt as standard: tests (PROPOSALS, scores not reviewed)
- T-RET1..T-RET12 test_retention_policy.py: 12/12 PASS in the sandbox (policy only; nothing is deleted by the test). NOT run on the server. NOT run: a real cleanup on the server with the disk above the high-water mark.
- T-DV1..T-DV24 test_described_view.py: 24/24 PASS in the sandbox with a faked Claude. NOT run: a real Luma clip with the new prompt, outdoor/elevated wording, the real cost of the description.
- Existing suite in the sandbox: the same 10 test files fail before and after (modules missing in the sandbox: test_batch_redo, test_download_retry, test_draft_check, test_end_frame, test_extract_truncation, test_foreground_risk, test_furnished_check, test_label_first, test_luma, test_scene_facts). To be run on the server after the deploy.
- New failure modes (proposals, S/O/D not reviewed): FM-RET: the automatic cleanup deletes a job that was still needed (S9, O3, D4 = 108, ACT; control: keep flag, 14-day floor, only above 80%, nightly backup); FM-DV: the described last view contains something that is not in the photo and Luma reproduces it (S5, O4, D6 = 120, ACT; control: clip QC, PVS_POSITIVE_PROMPT=0). Scores remain proposals until reviewed; scoreboard totals NOT recomputed here.
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("Seconda foto vera come fotogramma finale, assemblaggio completo, retention", "Elementi coerenti emergenti accettati", "Retention by disk capacity, positive prompt as standard")

for (name, text), mark in zip(JOBS, MARK):
    p = Path(name)
    cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the entry, left as it is")
        continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
