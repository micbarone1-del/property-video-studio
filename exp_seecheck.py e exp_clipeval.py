"""docs_p23.py -- appends the 2026-11-02 (sera) ground truth of the clip evaluator (Michele's eye vs Claude) to status.md, backlog.md and
AUTOMATION_TEST_PLAN.md. Append-only, idempotent (marker). Run from /var/www/property-video-studio."""
from pathlib import Path

STATUS = '''
### 2026-11-02 (sera) - Valutatore di clip con 12 fotogrammi: confronto con l'occhio di Michele
- Verificato da Michele sulle immagini: TV, ciotola e telefono del soggiorno (scena 1) ESISTONO (il fotogramma che aveva aperto prima mostrava solo meta' immagine): Claude non inventa quegli oggetti. Il secondo rubinetto della vasca nel bagno originale compare solo nell'ultimo fotogramma (allucinazione di Luma confermata). La ciotola del clip s1_regia sta dietro la sedia: il FAIL di Claude ("sparisce e ricompare") era un falso allarme da parallasse.
- Bilancio (n=6 clip): corretti 2 (tenda fantasma job_scene_001: FAIL; s4_regia buono: pass), mancati 2 (secondo rubinetto job_scene_004: Claude lo vede ma lo attribuisce a "il bordo che entra con l'avanzare", ragionamento fisicamente sbagliato perche' un avanzamento dritto non porta contenuto nuovo dai bordi; deformazione di porta e termosifone in loop_s4), falso allarme 1 (s1_regia, ciotola nascosta dalla sedia), non verificato 1 (loop_s1: seconda ciotola, vetrina, sedia). Costo del giro circa 0.35 USD. Non basta per dare al controllo potere di decisione (rigenerazione automatica).
- Strumenti: exp_seecheck.py (oggetti con riquadri, modalita' --pair primo/ultimo fotogramma affiancati) e una regola fisica nel prompt di exp_clipeval.py ("niente di nuovo entra dai bordi in un avanzamento dritto") esistono nell'ambiente di lavoro ma la regola NON e' stata caricata ne' provata sul server (scelta di Michele di non caricare ulteriori versioni sperimentali); le liste di oggetti di Claude cambiano da un giro all'altro sulla stessa immagine (rumore).
- Proposta (da approvare, non iniziata): valutatore in modalita' osservatore in produzione, cioe' misure di movimento + controllo di contenuto dopo ogni clip, salvate nel job e nel report, senza rigenerare ne' scartare; circa 0.05 USD di Claude a clip. Serve per misurare precisione e richiamo su job reali prima di automatizzare azioni. Tocca il percorso di generazione: piano, commit di rollback e test end-to-end prima del codice.
'''

BACKLOG = '''
### 2026-11-02 (sera) - Valutatore di clip in modalita' osservatore [PROPOSTO, in attesa di approvazione]
- Obiettivo: raccogliere dati reali sull'affidabilita' del controllo (movimento + contenuto) senza agire: salvataggio nel job (job_meta), riga nel report, nessuna rigenerazione/scarto. Poi decidere soglie e azioni (rigenerazione con tetto, movimento prudente dopo 3 tentativi, segnalazione) sui dati.
- Da progettare prima del codice: punto di aggancio unico dopo la generazione del clip (nessun secondo percorso: sweep frontend/backend, manuale/scraper, legacy/corrente), costo per job, interruttore di spegnimento, log per clip di prompt/id Luma/X-Request-Id, regola fisica sul bordo e gestione dell'occlusione (parallasse) nel prompt del controllo, ripetizione del controllo per ridurre il rumore, criteri di precisione/richiamo fissati prima.
'''

PLAN = '''

## 2026-11-02 (evening) — Clip evaluator, 12 frames: ground truth vs Michele's eye (PROPOSALS, scores not reviewed)
- T-H9b RUN (12 key frames + object inventory, 6 clips): correct 2, missed 2 (second tap; door/radiator deformation), false alarm 1 (object hidden behind a chair by parallax), not verified 1. Precision/recall cannot be claimed on n=6. T-H10 evaluator in shadow mode on real jobs: NOT RUN (not built).
- Row Q16 stays open (proposal S6 O4 D7 = 168, ACT): a defective clip can still pass the content check; the physical rule on edges is untested on the server. New proposed row Q17: false alarm from occlusion (S3 O5 D3 = 45): triggers an unnecessary regeneration (cost) if the evaluator is given authority. Control: shadow mode first, measure, then act.
- Scores remain proposals until reviewed by the user; scoreboard totals NOT recomputed here.
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("Valutatore di clip con 12 fotogrammi: confronto con l'occhio", "Valutatore di clip in modalita' osservatore", "Clip evaluator, 12 frames: ground truth")

for (name, text), mark in zip(JOBS, MARK):
    p = Path(name)
    cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the evening entry, left as it is")
        continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
