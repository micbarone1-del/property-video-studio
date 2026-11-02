"""docs_p22.py -- appends the 2026-11-02 decision (lean set-up + clip evaluator), the Next Scene result, the first clip-evaluator run and the PARKED backlog item
"retry later: prevent hallucinations in the image-to-video engine" to status.md, backlog.md and AUTOMATION_TEST_PLAN.md.
Append-only, idempotent (marker). Run from /var/www/property-video-studio."""
from pathlib import Path

STATUS = '''
### 2026-11-02 - Decisione: assetto "lean" + valutazione del clip; Next Scene scartato; primo giro del valutatore di clip
- Decisione di Michele (2026-11-02): si parte con l'assetto lean: Luma senza fotogramma finale, prompt ottimizzato, geometria + Claude per VALUTARE il clip prodotto, nuova generazione se fallisce, dopo 3 tentativi movimento prudente + segnalazione nel report. Il fotogramma finale resta spento (PVS_END_FRAME non attivato) e non e' in produzione. Il lavoro sul fotogramma finale e' sospeso, non cancellato: vedi la voce PARKED in backlog.md.
- Next Scene (Qwen Image Edit Plus + Next Scene LoRA su fal, lora 0.75, stesso piano del regista, scene 1 e 4, 3 prove ciascuna): 0/6, scala media 1.0 (0.975-1.016): non avanza. Altre vie cercate il 2026-10-30: FLUX.2 Multiple Angles (stessa famiglia di Qwen Angles, non provato), Stable Virtual Camera (nessuna API, licenza non commerciale), HunyuanWorld Voyager/Mirror e GEN3C (da ospitare, licenze da verificare), Lyra 2 (pesi solo ricerca; esiste fal-ai/lyra-2/splat ma input/output/prezzo non letti), SpAItial Echo (splat, non verificato se renderizza da una posa), Marble (nessun endpoint di rendering da posa: servirebbe un renderer di splat nostro).
- Valutatore di clip, primo giro (exp_clipeval.py, 12 clip, 6 fotogrammi, costo Claude circa 0.37 USD): contenuto: ha trovato la tenda fantasma nel clip originale della scena 1 (FAIL con tende apparse e cuscini spariti); NON ha visto il secondo rubinetto nel clip originale del bagno, ne' lo zig-zag, ne' la deformazione di porta e termosifone dei due clip del ciclo (verdetto pass). Ha segnalato anche cose da guardare a occhio (recinzione deformata in job_scene_000, testo di un libro che cambia in endclip_s1_tenda). Movimento: accelerazione ultimo/primo secondo 3.46-7.59 negli originali con scatti (jerk fino a 3.45), 1.35-1.9 nei clip con fotogramma finale tranne loop_s4 (3.98); lo zig-zag NON emerge (inversioni 1/1 come il clip buono). Secondo giro (12 fotogrammi + inventario degli oggetti): NON ancora eseguito (la versione caricata sul server era la prima).
'''

BACKLOG = '''
### 2026-11-02 - [PARKED] Riprovare piu' avanti la prevenzione delle allucinazioni nel motore image-to-video (Luma)
- Perche' parcheggiato: nelle prove del 2026-10-29/30 nessun espediente ha eliminato in modo affidabile tenda fantasma, secondo rubinetto, accelerazione e deformazioni; Michele ha scelto di partire con l'assetto lean (Luma senza fotogramma finale + valutatore del clip + rigenerazione con tetto + movimento prudente e segnalazione) e di riprovare dopo.
- Cosa e' stato provato (n piccoli, vedi status.md): fotogramma finale da modelli d'immagine (nb2, uni-1, Pro, Kontext, Qwen Angles, Next Scene, depth render) e ciclo del regista (5/6 giri PASS entro 3 tentativi ma clip con zig-zag/deformazioni); metrica di incoerenza (non separa); ritaglio come fotogramma finale (escluso: zoom 2D).
- Da riprovare quando: (1) il valutatore di clip e la rigenerazione sono in produzione e danno dati reali sui difetti ricorrenti; (2) prompt in forma positiva al posto delle circa 15 negazioni (mai provato, A/B su scena 1 e 4 circa 4.4 EUR); (3) video.keyframes (fotogramma intermedio) per l'accelerazione del bagno; (4) fotogramma finale come leva SOLO per l'accelerazione, se il valutatore la mostra come difetto dominante (dato attuale: 1.35-1.9 contro 3.5-7.6); (5) nuove versioni/funzioni di Luma e domanda a Luma support (email non ancora inviata da Michele); (6) ricostruzione 3D con rendering da posa (Marble, SpAItial Echo, Lyra 2 su fal) se arriva un endpoint che restituisce l'immagine, oppure insieme alla funzione di visita 3D richiesta da Relinx; (7) compensazione dell'accelerazione in montaggio (rimappatura di velocita'), non provata, rischio di scatti.
- Vincoli: nessun secondo percorso accanto a quello esistente (end_frame.py / PVS_END_FRAME da ritirare o riutilizzare); ogni test con criteri fissati prima; licenze da verificare prima di qualunque modello in produzione (FLUX.1 dev non commerciale per i pesi, Stable Virtual Camera e Lyra non commerciali).
### 2026-11-02 - Assetto lean con valutazione del clip [IN CORSO]
- Da fare: (a) rendere affidabile il controllo di contenuto (12 fotogrammi + inventario degli oggetti: prova pronta, da eseguire) e decidere cosa fare dello zig-zag, che il movimento non vede; (b) soglie del movimento (accelerazione, scatto) fissate su clip con difetto noto prima dell'uso; (c) politica: tentativi massimi, tetto di spesa per scena, movimento prudente dopo 3 tentativi, segnalazione nel report; (d) log per clip di prompt, id generazione Luma, X-Request-Id; (e) nessun codice di produzione prima di concordare il piano.
'''

PLAN = '''

## 2026-11-02 — Lean set-up decision and clip evaluator: tests and rows (PROPOSALS, scores not reviewed)
- T-H8 Next Scene LoRA as end-frame generator (6 attempts): FAIL, scale 1.0, no forward move. T-H9 clip evaluator first run (12 clips, 6 key frames): content check caught 1 of 4 defects known by eye (ghost curtain: yes; second tap, zig-zag, door/radiator deformation: no); motion metric separates acceleration (originals 3.46-7.59, end-frame clips 1.35-1.9, one 3.98) but not zig-zag. T-H9b the same with 12 frames and an inventory prompt: NOT RUN. No thresholds adopted yet.
- Row Q16 (a clip with a defect passes every automatic check): the first evaluator run would have passed 3 of 4 known-defective clips on content: ACT stays open, proposal S6 O4 D7 = 168. Control proposed: clip evaluation + regeneration cap + cautious movement + report flag; not built. Q12-Q15 unchanged (end frame parked, flag off).
- Invariants: no double cost (cap attempts and spend per scene before enabling regeneration), operator informed once (report flag).
- Scores remain proposals until reviewed by the user; scoreboard totals NOT recomputed here.
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("Decisione: assetto \"lean\" + valutazione del clip", "Riprovare piu' avanti la prevenzione delle allucinazioni", "Lean set-up decision and clip evaluator")

for (name, text), mark in zip(JOBS, MARK):
    p = Path(name)
    cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the 2026-11-02 entry, left as it is")
        continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
