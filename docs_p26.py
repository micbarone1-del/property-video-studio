"""docs_p26.py -- 2026-11-02 14:36: p25 deployed; incident of the live integration test. Append-only, idempotent (marker). Run after docs_p25.py."""
from pathlib import Path

STATUS = '''
### 2026-11-02 (14:36) - p25 deployato (commit 4dd94f4), video 91056c3e visto da Michele, incidente test_batch_redo
- Evidence: commit 4dd94f4 pushato dal server, riavviate produzione (8000) e test (8002), /health ok su entrambe, nessun job in corso al riavvio. Sul server: test_retention_policy 12/12 e test_described_view 24/24 PASS; test_prompt_rules, test_camera_candidates, test_anchor_direction, test_draft_check rc=0.
- Evidence: test_end_frame 31/32 sul server; l'unico FAIL e' E16 (tetto 10 EUR degli esperimenti), probabilmente per il registro di spesa reale di exp_luma non isolato dal test (NON verificato; non tocca file modificati). test_luma.py non e' un test (script manuale, stampa l'uso, rc=1 normale).
- INCIDENTE (mio errore): ho incluso test_batch_redo.py in un blocco di verifica. E' un test di INTEGRAZIONE contro l'istanza viva di produzione (127.0.0.1:8000): ha creato il job a49a2b7d "TEST_batch_redo" (3 scene, Luma) e ha generato 3 clip vere, stimate circa 3.3 EUR di Luma + 0.03 EUR di QC (dal preventivo del job; actual_cost vuoto, non verificato). Il job e' in awaiting_approval (1 clip segnalata), NON approvato e NON cancellato. Il test e' fallito sul passo C2 perche' ha atteso troppo poco. Regola da ora: test_batch_redo e simili (chiamano 127.0.0.1:8000) si lanciano solo con ok esplicito di Michele; mai in un giro di verifica generico.
- Video 91056c3e assemblato con i clip esistenti: giudizio di Michele: "ok e ben sincronizzato"; difetto: la scena 0 (facciata, clip del 30/10 col prompt VECCHIO) va troppo veloce verso la facciata e supera un cancello molto vicino alla parete. Il prompt positivo con descrizione NON era applicato a quella scena; da ricontrollare col prossimo video (Michele spera di regolarlo con la descrizione dell'inquadratura finale; NON verificato).
- URL dell'istanza di test (dal log di start_test.sh): http://187.77.196.94:8002 (porta 8002, UI); produzione http://187.77.196.94:8000.
'''

BACKLOG = '''
### 2026-11-02 - Scena 0 (facciata): velocita' e cancello vicino alla parete [APERTO, NON verificato]
- Osservazione di Michele sul video 91056c3e: il clip della facciata (approach_facade, prompt vecchio) avanza troppo veloce e supera un cancello molto vicino alla parete. Passo: rigenerare la scena con il prompt positivo + descrizione (ora standard) e giudicare a occhio; se la velocita' resta il problema, e' un'accelerazione di Luma (misurata altrove), non del prompt. Le scene outdoor/elevated non sono mai state provate col prompt positivo.
### 2026-11-02 - Test vivi sull'istanza di produzione [REGOLA]
- test_batch_redo.py (e ogni test che chiama 127.0.0.1:8000) crea job veri e spende: solo con ok esplicito di Michele, mai in blocchi di verifica generici. Da valutare: spostarlo sull'istanza di test o proteggerlo con una conferma.
'''

PLAN = '''

## 2026-11-02 (14:36) — p25 deployed; live-test incident
- T-DV and T-RET suites PASS on the server (12/12, 24/24). Still NOT run: a real clip with the new prompt; a real cleanup above the 80% mark; the keep button in the library (UI wiring checked by source only).
- Incident IN-1: test_batch_redo.py (live integration test against production) was run by mistake in a verification block: 3 real Luma clips, about EUR 3.3 (estimate), job a49a2b7d left in awaiting_approval. Control added: live tests only with the operator's explicit OK (proposal; scores not reviewed).
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("p25 deployato (commit 4dd94f4)", "Scena 0 (facciata): velocita'", "p25 deployed; live-test incident")
for (name, text), mark in zip(JOBS, MARK):
    p = Path(name); cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the entry, left as it is"); continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
