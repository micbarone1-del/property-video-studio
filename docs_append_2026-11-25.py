"""Append-only, idempotent docs update 2026-11-25 (learning loop phases 2-4). Run in the repo root: python3 docs_append_2026-11-25.py"""
import os
M = "<!-- DOC-2026-11-25j -->"
STATUS = M + """
## DOC-2026-11-25j - Ciclo di apprendimento fasi 2-4 (2026-11-25)
- Stato reale: codice su GitHub e sul server (pull fatto, sha verificate, py_compile OK), NON in produzione (produzione ancora cb8457b, nessun riavvio, nessun deploy). Nessun job vero eseguito con il codice nuovo.
- Fase 2 (registrazione): narration_log.py registra il codice di ogni rifiuto di narrazione (per scena, ancorata, blocchi, italiano) in job_meta `narration_rejections`; scene_risk salva anche anchor, anchor_side, depth, space_type. Il partner API non li espone (test N13).
- Fase 3 (ombra): learning_apply.matching() aggiunge `learn_shadow` alla riga del registro scene_risk; `python3 learning_apply.py` conta le scene che scattano (obiettivo 40 o 14/12/2026). Oggi: rules_loaded 0, scenes_firing 0 (output reale sul server).
- Fase 4 (applicazione): spenta. Richiede PVS_LEARN_APPLY=1 + PVS_LEARN_APPLY_UNTIL; cambia solo pov_movement verso un movimento gia' visto nei dati con tasso <= 0,8x; mai testo dei prompt. `python3 learning_apply.py check` scrive learning_apply_revert.json se i tassi peggiorano.
- Architettura: la classificazione delle scene vive solo in scene_kinds.py (prima era in learning_loop.py); learning_loop non e' importato dalla produzione, il ponte e' learning_rules.json.
- Prove: test_narration_log N1-N16, test_learning_apply A1-A24, test_learning_loop (L10 aggiornato), test_scene_risk, test_block_narration 75/75, test_scene_script 85/85: tutti PASS (sandbox; sul server PASS per i quattro test nuovi/toccati). NON eseguito: prova end-to-end sull'istanza finta, job vero.
- Limiti noti: il tier non e' noto in pianificazione (regole con tier solo in ombra); il controllo di ritorno non e' collegato a cron; fase 4 mai provata su job vero; righe FMEA non ri-valutate.
"""
BACKLOG = M + """
## DOC-2026-11-25j - Da fare dopo fasi 2-4 del ciclo di apprendimento
- Deploy in produzione di fasi 2-4: prima prova end-to-end sull'istanza finta con un job, poi deploy_relinx_prod.sh. Fino ad allora la registrazione dei motivi di rifiuto NON raccoglie dati reali. Stato: non fatto.
- Collegare `learning_apply.py check` a un cron (o al campionatore health) PRIMA di accendere PVS_LEARN_APPLY. Stato: non fatto.
- Rilancio periodico di `python3 learning_loop.py jobs` per produrre learning_rules.json (oggi solo a mano). Stato: non fatto.
- Fase 1b: caricare come seme i clip delle prove gia' etichettati (jobs/_test_scratch). Stato: non fatto.
- Tier non noto in pianificazione: decidere se applicare le regole con tier in un secondo punto (scelta del modello) o lasciarle in ombra. Domanda aperta.
- Ri-valutare le righe FMEA toccate (narrazione, registro scene, movimento) e proporle a Michele. Stato: non fatto.
"""
LOOP = M + """
## 10. Stato al 2026-11-25
Fasi 2-4 scritte e provate in unit test, su server ma NON in produzione. Fase 3 attiva in ombra (learn_shadow nel registro scene_risk), fase 4 spenta (interruttore + scadenza + ritorno automatico via `learning_apply.py check`, da collegare a un cron). Ponte con la produzione: solo learning_rules.json, scritto da learning_loop.py con le regole che HOLDS. Classificazione in scene_kinds.py. Oggi 0 regole caricate: corretto con pochi dati. Per la narrazione i motivi di rifiuto si raccolgono solo dopo il deploy.
"""
PLAN = M + """
## DOC-2026-11-25j - Test fasi 2-4 ciclo di apprendimento
| Test | Cosa | Stato |
|---|---|---|
| test_narration_log N1-N16 | motivi di rifiuto, campi scena, nessuna fuga nel partner API | PASS (sandbox e server) |
| test_learning_apply A1-A24 | ombra, interruttore, scadenza, solo movimento, ritorno, export | PASS (sandbox e server) |
| test_learning_loop (L10 aggiornato) | sola lettura, due file scritti | PASS (sandbox e server) |
| prova end-to-end istanza finta con fasi 2-4 | job completo con codice nuovo | NON ESEGUITO |
| fase 4 su job vero | applicazione movimento e ritorno | NON ESEGUITO |
Righe FMEA non ri-valutate (da proporre a Michele).
"""
for f, t in (("status.md", STATUS), ("backlog.md", BACKLOG), ("LEARNING_LOOP.md", LOOP), ("AUTOMATION_TEST_PLAN.md", PLAN)):
    s = open(f, encoding="utf-8").read()
    if M in s:
        print(f, "gia' presente"); continue
    open(f, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n" + t); print(f, "aggiunto")
