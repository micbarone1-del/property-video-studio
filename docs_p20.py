"""docs_p20.py -- appends the 2026-10-30 end-frame ("director") findings to status.md, backlog.md and AUTOMATION_TEST_PLAN.md.
Append-only, idempotent (a marker line prevents a second run from duplicating). Run from /var/www/property-video-studio."""
from pathlib import Path

STATUS = '''
### 2026-10-30 (pomeriggio) - Fotogramma finale "regista" per Luma: esperimenti (NON in produzione)
- Origine: Michele ha chiesto di correggere la causa radice dei difetti del job 91056c3e (tenda animata nella scena 1, secondo rubinetto nella scena 4, accelerazione). Misurato sul job: velocita' di montaggio 0.86-1.02 (non e' il nostro retiming); il movimento per secondo cresce DENTRO la clip (cucina 3.18 -> 17.66, camera 1.13 -> 5.69, circa 5x): e' Luma (in parte e' prospettiva, non separata). L'anchor oggi vale solo per walk_in_explore e outward_view (PRODUCTION_ANCHOR_MOVEMENTS): prudenza (rotazione/arco/quasi-fermo mai provati con Luma), non scelta di progetto; subtle_rotate e approach_facade non usano anchor.
- Documentazione Luma (docs.agents.lumalabs.ai, letta il 2026-10-30): nessun negative prompt (consigliano di descrivere cosa si vuole); start_frame/end_frame e video.keyframes (immagini a posizioni arbitrarie dei 120 frame); nessun controllo documentato di velocita' o scena statica; supporto support+luma-agents-api@lumalabs.ai (chiedono generation id e X-Request-Id). Il nostro prompt contiene circa 15 negazioni (_LUMA_RULES): NON ancora riscritto. Mail a Luma: bozza preparata, NON ancora inviata. Non registriamo X-Request-Id ne' il prompt esatto di ogni clip.
- Scoperta: il primo fotogramma che Luma riceve e' enhanced_lit (colori neutralizzati, R~G~B), NON images/scene_NNN.jpg (caldo, es. scena 4 141/120/99 contro 119/119/119). I primi fotogrammi finali, generati dall'originale, avevano circa 20 punti di scarto su R/B: corretto generando dal file reale (stessa selezione di exp_luma.load_scene) e con allineamento globale del colore.
- Strumenti sperimentali (solo cartella scratch, nessuna modifica a job o produzione): exp_endframe.py, exp_endclip.py, exp_director.py (Claude sceglie bersaglio e scala, Nano Banana 2 disegna, controllo Claude + controllo geometrico, max 3 tentativi), exp_geometry.py (OpenCV SIFT: scala, rotazione, punto di espansione, quota dentro la vista iniziale).
- Misure reali: fotogrammi finali "1 m" e "0.5 m" scala 1.006 e 1.048 (clip quasi ferme, confermato a occhio da Michele). Fotogrammi del regista: scala 1.25-1.30, rotazione sotto 1 grado, 100% dentro la vista iniziale; punto di espansione (0.097, 0.007) scena 1 e (0.112, -0.138) scena 4 (prima versione 0.278, -0.222, bersaglio tendina). uni-1: output 2784x1504 (upscaling, contrasto piu' basso nella scena 4): scartato; Nano Banana 2 e Pro simili, scelto il 2 (piu' economico, 1365x768). Clip con fotogramma del regista: scena 1 movimento/sec 4.4-5.5 (ultimo/primo 1.07, costante), scena 4 2.26-5.46 (2.42, accelera ancora, in parte prospettiva). Giudizio visivo di Michele: "i video sembrano andare bene", spostamento del bagno leggerissimo come previsto; nessuna tenda fantasma ne' secondo rubinetto segnalati (n=1 per scena).
- Costi dell'esperimento (stime, da riconciliare con le fatture): 4 clip Luma circa 4.4 EUR, immagini Nano Banana/uni-1 circa 1.2 USD, Claude circa 0.13 USD.
- NON verificato: affidabilita' (una sola prova per scena); soglie del controllo geometrico (PROPOSTE: scala >= 1.2, punto di espansione <= 0.2, rotazione <= 2.5, dentro >= 0.97); tende reali statiche in inquadratura (da provare); accelerazione del bagno; le altre 4 scene; un secondo annuncio. I test del regista nel sandbox usano risposte simulate: il comportamento reale e' solo quello visto in queste esecuzioni.
- Hostinger: avviso kernel CVE-2026-98432; server Debian 13, kernel 6.12.111; `apt update` del 2026-10-30: nessun kernel aggiornabile (2 pacchetti non kernel). Da ricontrollare ogni pochi giorni; riavvio solo dopo snapshot e senza job in corso.
'''

BACKLOG = '''
### 2026-10-30 - Fotogramma finale "regista" (end frame) per Luma [SCOPED, sperimentale, NON costruito in produzione]
- Obiettivo: eliminare alla radice le allucinazioni/animazioni di Luma (tenda fantasma, secondo rubinetto) e l'accelerazione, con affidabilita' massima; il rework passa dalle clip (circa 1.1 EUR) ai fotogrammi (circa 0.08 USD).
- Metodo (direzione approvata da Michele): per ogni scena Claude (visione) decide il bersaglio (fisso, lontano, nel terzo centrale; mai porte/tende/specchi/schermi/persone/piante/acqua/sanitari) e la scala in base a profondita' e carattere della stanza (non in metri); Nano Banana 2 (fal-ai/nano-banana-2/edit) disegna il fotogramma finale a partire dal PRIMO FOTOGRAMMA REALE (enhanced_lit), colori allineati; controllo Claude + controllo geometrico (scala >= 1.2, punto di espansione <= 0.2 dal centro, rotazione <= 2.5 gradi, dentro >= 0.97: soglie PROPOSTE); max 3 tentativi; poi Luma con start_frame + end_frame e prompt breve in positivo; poi il QC clip esistente. Il ritaglio come fotogramma finale e' ESCLUSO (zoom 2D, Michele).
- Decisioni e perche': uni-1 scartato (upscaling 2784x1504, meno contrasto); Nano Banana 2 provvisorio (Pro simile, costo doppio); generazione via fal (stessa chiave gia' in uso), in produzione si puo' aggirare fal (Google diretto circa 15% in meno ma serve una nuova chiave; uni-1 solo se migliora); il fotogramma intermedio (video.keyframes) solo se l'accelerazione resta (bagno 2.42).
- Architettura (sweep fatto sul codice): `_generate_luma_direct` accetta gia' end_frame_url; end_frame.py + PVS_END_FRAME (coppia di ritagli, spenta di default) e' un SECONDO percorso per lo stesso slot: va sostituito/ritirato, non affiancato. L'analisi anchor (vision_analysis.analyse_input) e' una sola: il regista riusa camera_plan.ANCHOR_UNSAFE_STEMS per la sicurezza dei bersagli.
- Aperto: (1) batteria di validazione con criteri fissati prima (nessun elemento nuovo, scala >= 1.2, espansione <= 0.2, ultimo/primo secondo < 1.5, QC clip ok) su 6 scene del 1312 + un secondo annuncio, circa 7 EUR di clip per annuncio, DA APPROVARE; (2) tende reali statiche in inquadratura: provare apposta; (3) cosa fare dopo 3 tentativi falliti (proposta: comportamento attuale con segnalazione al QC, mai in silenzio); (4) prompt di produzione con circa 15 negazioni: riscrittura in positivo da testare a parte; (5) registrare per ogni clip prompt esatto, generation id e X-Request-Id; (6) mail a Luma (bozza pronta, non inviata); (7) costo per video con fotogrammi (stima +0.5-1 EUR, da misurare); (8) integrazione nella pipeline dietro flag: piano tecnico da concordare prima del codice.
'''

PLAN = '''

## 2026-10-30 — Luma end-frame ("director") experiment: risk rows and tests (PROPOSALS, scores not reviewed)
- Proposed FMEA rows: Q12 Luma invents or animates elements absent from the photo when only a start frame is given (ghost curtain scene 1, second tap scene 4 of job 91056c3e): S8 O5 D5 RPN 200 ACT; control: end frame + geometry gate + clip QC (NOT in production). Q13 end frame invents content or differs in colour/light from the start frame: S8 O4 D4 RPN 128 ACT; control: generate from the real start frame, global colour match, Claude QC + geometric check. Q14 end frame too similar (static clip) or sideways (slide): S5 O5 D4 RPN 100 ACT; control: geometry gate (thresholds proposed). Q15 dependency on image-generation providers (fal queue, model availability) and per-image cost: S5 O3 D3 RPN 45.
- Tests: T-H1 validation batch (6 scenes of listing 1312 + a second listing, criteria fixed beforehand): NOT RUN. T-H2 director flow with simulated model answers (sandbox only: scale too low, sideways drift, pass): PASS in sandbox, NOT run on the server. T-H3 geometry measurement on synthetic zoom/shift images (sandbox): PASS; on real pairs: 6 measured, indicator only (global similarity model, inlier share 37-60%).
- Real evidence so far (n=1 per scene): clips with the director end frame: scene 1 steady motion (last/first second 1.07), scene 4 still accelerating (2.42); Michele's eye: videos fine, no ghost curtain or second tap reported. Not proven reliable.
- Invariants touched: final state correct and visible; no double cost (each retry of a still is a paid call: cap 3 attempts).
- Scores remain proposals until reviewed by the user; scoreboard totals NOT recomputed here.
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("Fotogramma finale \"regista\"", "Fotogramma finale \"regista\"", "Luma end-frame (\"director\")")

for (name, text), mark in zip(JOBS, MARK):
    p = Path(name)
    cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the 2026-10-30 entry, left as it is")
        continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
