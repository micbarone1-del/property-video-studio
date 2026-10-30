"""docs_p21.py -- appends the 2026-10-30 (sera) end-frame results (bake-off, loop, two clips, residual metric) to status.md, backlog.md and
AUTOMATION_TEST_PLAN.md. Append-only, idempotent (marker). Run from /var/www/property-video-studio."""
from pathlib import Path

STATUS = '''
### 2026-10-30 (sera) - Fotogramma finale: confronto modelli, ciclo completo, due clip, esito (sperimentale, NON in produzione)
- Confronto modelli (exp_bakeoff.py, job 91056c3e scene 1 e 4, 3 prove singole per modello, stesso piano del regista, senza correzioni): PASS uni-1 2/6, nb2 1/6, kontext 0/6, qwen-angles 0/6, depth-render 0/6. Qwen Multiple Angles con zoom 6-8 non avanza (scala 1.01, espansione -0.55: sposta la vista di lato). Kontext: layout specchiato, divano cambiato, passo indietro nel bagno (scala 0.90). Depth render: scena 1 nessun movimento (1.01); scena 4 solo con dz 2.2 (scala 1.77) ma water duplicato e deformato; salto 1.00 -> 1.77 tra dz 1.7 e 2.2 NON spiegato. Costo circa 30 immagini.
- Ciclo completo del regista (exp_loop.py, tentativi con correzioni, ordine nb2/uni-1/uni-1, piano fisso, 3 giri per scena): scena 1 PASS 3/3 (tentativi 2,1,2), scena 4 PASS 2/3 (tentativi 1,1; un giro FAIL: deriva laterale e verticale, poi 2 oggetti inventati). Sono 6 giri: non dimostra il 100%; i PASS del bagno sono al limite delle soglie (scala 1.206, espansione 0.185). Nb2 al primo tentativo: 3/6 gate+QC; uni-1 nel ciclo 2/4. Tra nb2 e uni-1 la differenza e' dentro il rumore (totale prove: nb2 4/12, uni-1 4/10).
- Due clip Luma con questi fotogrammi (scena 1 L1_a2 uni-1 scala 1.465; scena 4 L1_a1 nb2 scala 1.206), giudizio di Michele (n=1 ciascuno): scena 1 avanza "leggermente a zig-zag"; scena 4 verso la fine deforma porta e termosifone per adattarsi al fotogramma finale. I due clip del regista precedenti (scena 1 scala 1.28, scena 4 scala 1.31) erano stati giudicati "fine". Il controllo di Claude sul fotogramma NON ha visto le deformazioni: il fotogramma finale fissa dove arriva il clip, non come.
- Metrica di incoerenza (exp_geometry.py esteso: residuo dopo allineamento globale + flusso ottico) provata sui 4 fotogrammi con clip: NON separa buoni e cattivi (scena 1 buono p90 21.99 contro cattivo 15.82; scena 4 buono 25.54 contro cattivo 16.00): in una stanza reale la parallasse domina il residuo. Scartata come gate; resta come indicatore nello strumento. (Verificata solo su caso sintetico: zoom puro residuo ~0.2 px, oggetto cambiato 3.6 px.)
- Decisione di Michele: dopo 3 tentativi falliti la scena va con movimento prudente e viene segnalata nel report (da progettare, non implementato). Direzione in valutazione (proposta di Michele, 18:02): tornare all'assetto "lean" (Luma senza fotogramma finale, prompt ottimizzato in forma positiva) e usare geometria + Claude per VALUTARE il clip prodotto, con nuova generazione se fallisce. Il fotogramma finale resta spento (PVS_END_FRAME non attivato) e non e' stato integrato.
- Costi del giorno (stime da riconciliare con le fatture): clip Luma circa 4.4 + 2.2 EUR, immagini circa 30 + 10 (nb2 circa 0.08 USD, uni-1 15 crediti), Claude circa 0.4 USD.
'''

BACKLOG = '''
### 2026-10-30 (sera) - Esito fotogramma finale e direzione "lean + valutazione del clip" [DA DECIDERE]
- Esito: il fotogramma finale ha ridotto l'accelerazione nella scena 1 e il regista passa spesso entro 3 tentativi, ma i clip con fotogramma finale hanno mostrato zig-zag e deformazioni (n=1 ciascuno), e nessun controllo sul fotogramma le ha previste. Non e' una soluzione affidabile al 100% come singolo espediente.
- Proposta di Michele (da confermare): Luma con prompt ottimizzato in forma positiva (le attuali circa 15 negazioni non funzionano: la documentazione di Luma consiglia di descrivere cosa si vuole), valutazione del clip prodotto con geometria + Claude (tenda/oggetti apparsi, accelerazione, deriva), rigenerazione se fallisce, dopo 3 tentativi movimento prudente + segnalazione nel report.
- Da costruire prima di decidere: (1) valutatore di clip (profilo di velocita' dal flusso ottico per secondo; Claude su fotogrammi chiave per oggetti nuovi), VALIDATO a costo quasi zero sui clip gia' esistenti, compresi quelli originali con tenda fantasma e accelerazione; (2) prova A/B del prompt positivo contro quello attuale su scena 1 e scena 4 (circa 4 clip, circa 4.4 EUR, da approvare); (3) politica di uscita: tentativi massimi, tetto di spesa per scena, movimento prudente, segnalazione. Tutto con architettura unica: nessun secondo percorso accanto a quello esistente; end_frame.py / PVS_END_FRAME da ritirare o riutilizzare, non duplicare.
- Il fotogramma finale resta come leva opzionale (flag spento) solo se il valutatore mostrera' che risolve un difetto specifico (accelerazione).
- Aperto: log per clip di prompt, id generazione Luma, X-Request-Id (non ancora fatto); email a Luma non ancora inviata da Michele; documento di progetto unico (rischi, test, stato, backlog) richiesto da Michele per dopo questa fase.
'''

PLAN = '''

## 2026-10-30 (evening) — End-frame experiment: results and what they do and do not show (PROPOSALS, scores not reviewed)
- Tests: T-H1 validation batch: NOT RUN. T-H4 bake-off of five image generators (30 single attempts, scenes 1 and 4 of job 91056c3e): RUN, uni-1 2/6, nb2 1/6, kontext 0/6, qwen 0/6, depth 0/6; thresholds are proposals. T-H5 full director loop, 6 rounds (nb2, uni-1, uni-1): scene 1 3/3, scene 4 2/3; n too small to claim a rate. T-H6 two Luma clips from loop frames: both judged worse by Michele (zig-zag; door and radiator deformed near the end), n=1 each, so Luma variance is not separated from frame quality. T-H7 incoherence metric (global alignment residual + optical flow) as a predictor: FAIL as a gate, does not separate the two good clips from the two bad ones.
- Row Q13 (end frame invents objects / colour mismatch): evidence says the Claude check does not see deformation of edge objects (door, radiator); S/O/D not re-scored here. Q12 (ghost animation) remains open: no clip test of the curtain scene with the new frames was reported by Michele.
- New proposed row Q16: end frame that passes every check still yields a clip with zig-zag path or deformed objects (S6 O4 D6 = 144, ACT, proposal). Control proposed: evaluate the PRODUCED CLIP (flow-based speed/path profile plus Claude on key frames), regenerate up to 3 times, then cautious movement and a report flag. Not built.
- Invariants: no double cost (cap attempts and per-scene spend), operator informed once (flag in report).
- Scores remain proposals until reviewed by the user; scoreboard totals NOT recomputed here.
'''

JOBS = [("status.md", STATUS), ("backlog.md", BACKLOG), ("AUTOMATION_TEST_PLAN.md", PLAN)]
MARK = ("Fotogramma finale: confronto modelli, ciclo completo", "Esito fotogramma finale e direzione", "End-frame experiment: results and what they do")

for (name, text), mark in zip(JOBS, MARK):
    p = Path(name)
    cur = p.read_text(encoding="utf-8")
    if mark in cur:
        print(f"{name}: already contains the evening entry, left as it is")
        continue
    p.write_text(cur.rstrip("\n") + "\n" + text, encoding="utf-8")
    print(f"{name}: appended ({len(text)} characters)")
