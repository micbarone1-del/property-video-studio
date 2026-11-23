# Aggiornamento documenti, 23/11/2026 sera (QC unico, nuvola di punti, domande extra, inventario, deploy)

Da aggiungere a status.md, backlog.md e AUTOMATION_TEST_PLAN.md quando Michele lo chiede. Stati sempre reali: "non eseguito" resta "non eseguito" finché non c'è un output.

## 1. Decisioni di Michele (23/11 sera)
- QC: l'obiettivo finale è un QC unico e snello (una chiamata a Claude, al massimo un segnale misurato, una sola funzione di decisione). Non si aggiungono strati.
- Nuvola di punti da foto (3D economico): scartata (sezione 2).
- Domande extra nel giudice a 6 frame: dietro interruttore, solo misura, con scadenza (sezione 4).
- Monitor `arrival` spento (PVS_ARRIVAL_MONITOR=0 in start.sh): approvato e in produzione dal deploy del 23/11 (sezione 7).
- Ogni funzione "in misura" deve avere scadenza o limite di video, dopo il quale si rilegge il log e si decide: produzione, ricalibrare o togliere.
- Aggiornare i documenti via Claude (Project), non da terminale.

## 2. Nuvola di punti: scartata (23/11)
Misura: profondità della foto (depth-anything, fal) -> nuvola 3D, posa della camera per frame con SIFT+PnP, quota di frame fuori dalla nuvola (out_max). Test su 40 clip etichettate da Michele (15 difettosi, 25 buoni), due giri (1120_160849 e 1123_181131).
- Nuvola, out_max > 0.15: 10/15 difettosi presi, 3/25 falsi allarmi. > 0.10: 12/15, 6/25.
- Misura geometrica già esistente (new_max, gratis, già calcolata): > 0.10: 12/15, 5/25. > 0.15: 8/15, 3/25. Pareggia la nuvola.
- Spostamento laterale (pan): inutile (17/25 falsi a soglia 0.05).
- Ipotesi "posa persa = rotazione ampia = difetto": falsa. I clip buoni perdono più pose dei difettosi (solo perse>=1: 3/15 contro 13/25). La stima della posa fallisce per ragioni innocue.
- Difetto del test (ammesso): i frame senza posa venivano esclusi dal massimo e contati come 0. Sistemarlo non cambia la conclusione.
- Caveat: campione piccolo, soglie scelte sugli stessi dati.
Esito: nuvola scartata, 3D low-cost non perseguito per ora. Script restano sul server come strumenti di esperimento (exp_pcloud.py, exp_geo_base.py, pc_lost.py), non nella repo.

## 3. Confronto new_max contro domande di Claude (40 clip)
- new_max > 0.10: 12/15 e 5/25. "Rivela cose non nel frame 1" (N): 11/15 e 4/25. "Scena estesa" (X): 12/15 e 5/25.
- (N o X) e new_max > 0.05: 12/15 e 3/25 (migliore). N e new_max > 0.05: 11/15 e 2/25.
- Mancati da tutti: erd e xto. Falso allarme comune: hyf (e sdl): da riguardare, forse etichetta clemente.
- Soglie scelte sugli stessi dati: indicative, non da copiare come valori definitivi.

## 4. Estensione del giudice (clip_standard.py): domande extra, SOLO MISURA
- Interruttore PVS_STANDARD_EXTRA=1, SPENTO di default, non nel .env. Le domande "revealed" e "extended_scene" viaggiano nella stessa chiamata del giudice (nessuna chiamata in più). Risposte nel log shadow (revealed_no, revealed_hint, extended_scene) e in summary()["extra"]. Nessun verdetto le legge.
- Con l'interruttore spento il prompt è identico all'originale (test S37) e la lettura tollerante è disattivata (S41).
- Cronologia dei difetti trovati col test A/B (40 clip x 3 chiamate, 1.24 EUR): (a) con la prima versione del prompt 5/40 risposte illeggibili; (b) il verdetto del giudice cambia da solo tra due chiamate IDENTICHE su 12/35 clip (34%), la velocità su 7/35; con le extra cambia su 13/35 ma quasi sempre più severo (11 più severo, 2 meno); (c) causa delle risposte illeggibili: non troncamento ma due oggetti JSON con testo in mezzo ("Extra keys:"), perché le chiavi erano scritte dopo l'esempio di risposta.
- Correzioni: v2 = chiavi extra DENTRO l'esempio di risposta, istruzione "un solo oggetto JSON", più lettura tollerante (unisce gli oggetti, vale solo con verdetto presente); v3 = lettura tollerante solo con l'interruttore acceso. Prova reale con il prompt v2: 20 chiamate, 20/20 leggibili, tutte col metodo normale (0.21 EUR). Campione piccolo.
- Commit: 68019d9 (v1+v2), 2b3a17d (v3). Test S29-S41 PASS, test_standard_3b 32/32, test_clip_pace, test_clip_qc 44/44 PASS. test_standard_enforce E3 FAIL, ma fallisce uguale senza le nostre modifiche (il test non è stato aggiornato dopo il 16/11, quando la geometria ha smesso di bocciare da sola): da sistemare.
- Nota: la parola di velocità del giudice NON guida il pace fix (dal 9/11 il pace fix usa la velocità misurata, motion_peak); il commento in clip_standard.py riga ~281 è obsoleto.
- SCADENZA: fino a 40 clip di produzione registrati con le extra oppure 14/12/2026, il primo dei due. Poi si rilegge il log contro le etichette di Michele e si decide: produzione (regola candidata: (N o X) e new_max > 0.05), ricalibrare o togliere. Prima di accendere in produzione: confronto della distribuzione dei verdetti prima/dopo.
- Accensione dell'interruttore in misura: decisione a parte, solo con l'ok di Michele. Il conto alla rovescia della scadenza parte dall'accensione, non dal deploy.

## 5. Inventario delle funzioni (23/11, dai log: 84 clip nel giudice shadow dal 5 al 17/11, 116 eventi scene a rischio dal 4 al 17/11)
Interruttori PVS_* attivi nell'app in produzione prima del deploy: ACCEPT_RENDERS=0, ARRIVAL_MONITOR=1 (spento con il deploy del 23/11), AUTO_ALT_PHOTO=1, AUTO_REWORK=1, AUTO_START=1 (cap 100 EUR, max attivi 2), DEFAULT_VOICE, FACT_MASK_AGENCY=1, LUMA_RESOLUTION=1080p, NARRATION_MODEL=claude-sonnet-5-5, PACE_FIX=1 (limite 26, minimo 6), PARTNER_AGENCY_LIMIT_24H=20. Giudice shadow e registro scene a rischio sono accesi di default.

| Funzione | Dati | Proposta |
|---|---|---|
| Verdetto del giudice shadow | fail 33/84 (39%), reject standard 36/84 (43%) contro 22/107 (21%) di non-pass del QC di produzione al primo controllo; instabile (34% tra chiamate uguali) | non promuoverlo mai; resta solo come contenitore delle domande extra |
| new_max (geometria) | >0.10: 12/78, >0.20: 5/78 | tenere, parte della regola candidata |
| Domande extra | nessun dato in produzione (spente) | accendere in misura, scadenza 40 clip o 14/12 |
| arrival (monitor) | 88% dei clip "supera il target", 71% oltre il doppio: non separa niente | spento (deploy 23/11) |
| plan_check | "più del previsto" 39/40, "direzione diversa dal piano" 19/40, mai confrontato con etichette | non promuovere; togliere dal prompt entro il 7/12 se non emerge un uso |
| pace fix | applicato su 1 clip su 34 (33 dentro il limite) | tenere così com'è |
| Registro scene a rischio | primo QC non-pass: exterior 36%, large 33%, outdoor 29%, living 21%, bathrooms 19%, kitchen 13%, bedrooms 9% (n 6-23 per categoria); rework risolve 5/9 | tenere (costo zero), rivedere a 300 eventi o con più volume dal pilota |

Osservazioni: arrival e plan_check dicono entrambi che il generatore viaggia più del piano quasi sempre: coerente, ma non è un difetto per Michele. Dal 17/11 i due log non si muovono; in jobs/ dopo il 17/11 risulta modificato un solo job (19/11). Probabile assenza di generazioni di produzione, non verificato.

## 6. Lezioni operative (da aggiungere a learnings / ways of working)
- Blocchi base64 incollati dal messaggio: un carattere ricopiato male da Claude (barra mancante) ha fatto fallire il controllo sha due volte. Il guardiano ha evitato file corrotti. Da ora i blocchi vanno consegnati come FILE generati dal programma (SendUserFile), non ricopiati nel testo.
- L'hPanel si pianta su incolla da circa 2.6 KB: restare sotto circa 1.5-1.8 KB per pezzo.
- Costo dei test del 23/11 sera: test A/B 1.24 EUR, verifiche troncamento e prompt v2 circa 0.5 EUR in totale.

## 7. Stato e cose aperte (23/11, dopo il deploy)
- DEPLOY ESEGUITO il 23/11/2026 alle 21:51:44 UTC (22:51 ora italiana), con deploy_relinx_prod.sh alt. Nessun job in corso al momento. Rollback salvato prima: fbe7fd94fedc1696038a670b7596b68c2e42737a. Commit in produzione b658f3a (include v3 2b3a17d e start.sh con ARRIVAL_MONITOR=0), pid 568218, health ok, release mode manual.
- Verificato nel processo dopo il deploy: PVS_ARRIVAL_MONITOR=0, nessun PVS_STANDARD_EXTRA, ACCEPT_RENDERS=0, AUTO_ALT_PHOTO=1, AUTO_REWORK=1, AUTO_START=1 (cap 100, max attivi 2, NOT_BEFORE 2026-11-23T21:51:44), LUMA_RESOLUTION=1080p, NARRATION_MODEL=claude-sonnet-5-5, PACE_FIX=1 (26, min 6), PARTNER_AGENCY_LIMIT_24H=20.
- NON ancora verificato dopo il deploy: PVS_DEFAULT_VOICE e PVS_FACT_MASK_AGENCY (il filtro del deploy non li mostra; prima del deploy c'erano).
- Il deploy ha riportato PVS_AUTO_START_NOT_BEFORE all'ora del deploy: l'avvio automatico vale solo per bozze create dopo.
- Test plan estensione del giudice: 1 patch compila e S29-S41 PASS; 2 suite esistenti PASS (E3 FAIL preesistente); 3 prova reale su 2 clip con extra: PASS strutturale (ihr, qdo; verdetti diversi tra senza e con extra, solo informativi); 4 dopo il deploy app su 8000, valori PVS_*, EXTRA assente: PARZIALE (ok tranne DEFAULT_VOICE e FACT_MASK_AGENCY da controllare); 5 primo job vero senza campi extra negli eventi shadow: NON ESEGUITO; 6 confronto prima/dopo all'accensione: NON ESEGUITO.
- Relinx (23/11 sera): Michele riferisce che Relinx ha problemi col proprio server ed è in migrazione; la sua ipotesi è che l'errore sulla chiave API fosse lato loro. IPOTESI NON VERIFICATA da nessun log nostro. Non si offre una nuova chiave (decisione già presa).
- Altre cose aperte: test E3 da aggiornare; commento obsoleto in clip_standard.py; "USD 18" nel commento di credit_monitor.py; prova dal vivo del watchdog (serve un'interruzione simulata); riguardare hyf e sdl (etichetta); decisione su QC unico (una chiamata Claude con le due domande + new_max + una funzione di decisione); portare questo aggiornamento in status.md, backlog.md e AUTOMATION_TEST_PLAN.md su GitHub (non ancora fatto).
