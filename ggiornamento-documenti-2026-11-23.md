# Aggiornamento documenti - lunedi 23 novembre 2026 (una volta al giorno)

Stato: TESTO PRONTO, NON ancora applicato a status.md, backlog.md, AUTOMATION_TEST_PLAN.md nel repository. Ogni voce dice cosa e' verificato e con quale prova (output incollato da Michele nella chat del 23/11). Cio' che non e' stato visto resta "non visto". I punteggi FMEA sono proposte, non rivalutati qui. Questo testo segue claude/aggiornamento-documenti-2026-11-20.md (da applicare prima, se non lo e' ancora).

Commit sul server oggi: 994d09a (backup cifrato via mail) -> 6ef4417 (saldo Luma nel controllo crediti) -> 24a6850 (watchdog del battito). Rollback del deploy del watchdog: 6ef4417 (hash completo 6ef4417264488312e302b7cdcbee53cfa09af2b1). Rollback del deploy Luma: 994d09a (hash completo 994d09a4fd76f4020190a6322876d062f62bfb50).

---

## DA AGGIUNGERE A status.md

### 2026-11-23 - Verificato oggi

- **Saldo Luma nel controllo crediti** (commit 6ef4417, in produzione). UN solo lettore: credit_monitor.get_luma_credits (GET agents.lumalabs.ai/v1/credits, risposta balance_credits, 0,003 USD a credito). Alimenta banner dell'interfaccia, avviso a inizio/fine job, controllo di manutenzione e riga "Crediti API" del cruscotto. Soglia di allarme 8.000 crediti (circa 24 USD) tramite LUMA_CREDIT_THRESHOLD nel .env: scelta sopra il punto di ricarica automatica di Luma (sotto 30 USD, ricarica 50 USD, carta Visa) perche' l'allarme segnali una ricarica che NON e' partita, non ogni ricarica normale. Prove: test_luma_credits (L1-L22) FAILS 0 sul server, test_health_kpi, test_stuck_jobs 13/13, test_operator_inbox 23/23, test_fake_providers 26/26; lettura dal vivo 17.779 crediti (53,34 USD, ok); riga "Crediti API" del cruscotto mostra Luma; get_all_credits dal vivo con soglia 8000, any_low False. NON visto: il banner dell'interfaccia con Luma sotto soglia (richiede un saldo basso, non simulato in produzione; coperto solo dai test in sandbox). L'endpoint /credits risponde 403 senza chiave (atteso). Il commento nel codice di credit_monitor.py riga 31 dice ancora "about USD 18" (vecchia soglia): da correggere al prossimo commit, nessun effetto sul comportamento.
- **Watchdog del battito** (heartbeat_watchdog.py, commit 24a6850, in produzione). Nel ciclo che l'app ha gia (_auto_start_loop, ogni 60 secondi, nessun ciclo nuovo): se il file di stato della manutenzione ha piu' di 30 minuti, UNA mail all'operatore, ripetuta al massimo ogni 6 ore; al ritorno alla normalita' lo stato si azzera, quindi un nuovo guasto avvisa subito. Un riavvio dell'app non causa una seconda mail (ultimo invio in heartbeat_watchdog_state.json, nel .gitignore). Nessun file di stato = guasto solo dopo 30 minuti di vita dell'app. Un solo lettore del battito: health_kpi.heartbeat_age_min (lo stesso della riga "Manutenzione"). Il cron di manutenzione gira ogni 5 minuti; la riga del cruscotto diventa gialla a 12 minuti e rossa a 20. Prove: test_heartbeat_watchdog W1-W17 FAILS 0 (server); verifica dal vivo dopo il deploy: eta battito 1,8 minuti, decisione "ok" con invio finto, nessun file di stato. NON visto: l'invio reale della mail con la manutenzione ferma, e la chiamata ogni minuto dal ciclo dell'app in produzione (coperti da test W16 e dal codice, nessuna prova dal vivo).
- **Valori di avvio dopo i riavvii**: dopo il riavvio con il solo start.sh (aggiunta soglia Luma nel .env) i 13 valori PVS_* di prima erano tutti presenti e invariati; con il deploy script restano invariati. Rilascio sempre manuale. Lezione: per riavviare usare deploy_relinx_prod.sh alt (controlla job in corso, punto di ritorno, valori di avvio), non start.sh da solo.
- **Backup cifrato via mail** (commit 994d09a, in produzione, fatto in precedenza oggi): Michele ha incollato i risultati (6B tutto verde, commit/deploy, file password, mail di prova, cron della domenica 04:30). Prima mail automatica attesa domenica 29/11.
- **Cruscotto di oggi** (screenshot ore 17:01): 0/2 job in generazione, 0 / 100 EUR impegnati, 6 job in attesa di Michele, 16 con scene da rivedere; Manutenzione, Disco (17,7% usato, 153 GB liberi), Backup (2 copie, 5,8 ore, 7 GB), Servizio, Crediti API, Job fermi tutti verdi; Luma 1080p. L'avviso "Da fare" sul disco (81,9%, 27 GB liberi, di 7 ore prima) era superato: da chiudere con "Fatto".
- **Test sulle scene sicure (360p/1080p, secondo giro): AVVIATO alle 19:11 ora di Roma, esito non noto.** Il primo giro usava scene rischiose (>= 2 esiti non-pass); qui scene con verdetti tutti buoni, per misurare i falsi allarmi. Dati veri del registro (istanza di test, 184 eventi): 162 scene distinte, 17 con almeno 2 verdetti (tutte rifatte dopo una segnalazione), 121 tutte buone ma con un solo verdetto, quindi "sicura" qui = UN solo verdetto buono (evidenza piu' debole di quanto previsto). Scelte, una per ambiente: 2eb628f1 scena 2 (soggiorno), 138eba71 scena 3 (camere), 138eba71 scena 0 (esterno), 2eb628f1 scena 4 (bagni). 20 clip, 10,32 USD (tetto di questo giro: gia speso 10,32 + 10,32). Strumento: exp_res_safe.py (sorgente di scelta, poi exp_res_compare.py con la lista sostituita) + catena /tmp/safe_chain.sh in background (genera i clip, poi la domanda di rotazione a Claude, exp_res_rotq.py, senza etichette umane). Senza etichette di Michele si misurano falsi allarmi e coerenza tra risoluzioni, NON la correttezza vera: se ci sono segnalazioni, Michele guarda solo quelle (2-3 clip). Log /tmp/safe_run.log e /tmp/safe_rotq.log. Test dello strumento S1-S10 PASS in sandbox (non lanciato sul server). Michele ha offerto di validare lui dei campioni del controllo qualita'.

### Da integrare dalla cronologia precedente (NON ripetuto qui: non riletto in questa sessione, nessun dettaglio inventato)
Incidente disco e riga "Salute del sistema" (health_kpi); backup_v2 con snapshot notturni; esito del test 360p contro 1080p comunicato a Douglas (Luma) con una mail breve di solo risultato; esperimenti di rotazione (misura gratuita dell'angolo: nessun valore, tolta; domanda esplicita a Claude: unica pista); idea del controllo di rotazione con scansione 3D (mai provata).

---

## DA AGGIUNGERE A backlog.md

### 2026-11-23 - Decisioni di Michele
1. Soglia di allarme Luma: allineata alla ricarica automatica di Luma (sotto 30 USD ricarica 50 USD); scelta 8.000 crediti (circa 24 USD) proposta da me e adottata.
2. Watchdog del battito: approvato ("Ok per ora"), soglia 30 minuti, ripetizione al massimo ogni 6 ore; frequenza giusta (la manutenzione gira ogni 5 minuti).
3. Rilascio automatico: decisione nostra, non di Relinx; proposta dei criteri da fare quando saremo stabili e chiusi i punti chiave.
4. Relinx 401: NON sappiamo se serve una nuova chiave: nessuna offerta di chiave finche' non c'e' un fatto che lo dica (Michele, 2026-11-23: "Facciamo casino. Fermati."). Prima del chase: Michele lo ha gia' fatto, nessuna risposta alle 19:00. Se arriva Relinx: mettiamo in attesa il resto.
5. Test scene sicure: via libera di Michele a procedere senza la sua revisione cieca ("Fai i QC solo in automatico, senza di me. Se possibile."), con la correzione di metodo scritta sopra.
6. 3D: Michele non intende Atlas (Marble e' discontinuato) ma uno strumento economico per costruire una nuvola di punti da una foto. Fattibile: profondita' da fal-ai depth-anything v2 (gia in depth_renderer.py, circa 0,001 EUR a immagine) + proiezione 3D con numpy/OpenCV.

### Voci aperte (nuove o cambiate)
- **Controllo di rotazione con nuvola di punti (3D economico)**: dopo il risultato del giro scene sicure. Test minimo: un clip buono e uno cattivo del primo giro (etichette di Michele come verita'), nuvola dalla foto d'origine, verificare se i fotogrammi in cui la camera gira mostrano contenuto fuori dalla nuvola; costo atteso circa 1 EUR o meno, una sessione. Limiti noti: una sola foto = solo il visibile; focale e scala stimate; profondita' sbagliata su vetri/specchi e ai bordi. Criterio di riuscita da scrivere prima: il numero deve separare i clip buoni dai cattivi. Prezzi di Atlas/Marble: non servono (Marble discontinuato).
- **Integrazione del controllo 360p nelle scene a rischio**, fasi: (1) secondo giro su scene sicure (in corso), (2) modalita' ombra (registra, non decide), (3) azione. Il controllo di rotazione a Claude va tarato sui falsi allarmi prima di (3).
- Watchdog: prova dal vivo con manutenzione ferma >30 minuti non fatta (non la facciamo senza ok di Michele).
- Correggere il commento "USD 18" in credit_monitor.py al prossimo commit.
- Casella "Da fare": chiudere l'avviso disco superato.
- Documenti: applicare agli stessi tre file (status.md, backlog.md, AUTOMATION_TEST_PLAN.md) i testi del 20/11 e del 23/11.
- Voci del 20/11 ancora aperte: criteri di rilascio automatico, tetto di spesa 100 EUR, soglia job fermi 45 minuti, test P1e, segreto di firma dei webhook (da chiedere a Relinx), video THRINAKIE, PVS_PARTNER_AGENCY_LIMIT_24H da 20 a 2 al lancio, chiave fal inutilizzata, retention backup, fattura Luma da riconciliare con cost_actual.
- Domani 24/11 alle 9:00 promemoria: controllare snap_2026-11-24 piccolo, riga Backup verde, riga Disco aggiornata, quando cancellare a mano jobs_2026-11-23_0300.tar.gz; domenica 29/11 alle 9:00: prima mail automatica cifrata.

---

## DA AGGIUNGERE A AUTOMATION_TEST_PLAN.md

### 2026-11-23 - Test aggiunti e risultati (prova = output incollato da Michele il 23/11, salvo dove scritto)
| Test | Cosa verifica | Esito |
|---|---|---|
| test_luma_credits L1-L22 | saldo Luma, un solo lettore, banner, avviso, manutenzione, simulatore | FAILS 0 (server) |
| test_heartbeat_watchdog W1-W17 | soglia 30 minuti, ripetizione 6 ore, azzeramento, invio fallito, file rotti, un solo lettore | FAILS 0 (server) |
| test_exp_res_safe S1-S10 | selezione scene sicure, una per ambiente, costo 10,32 USD | PASS in sandbox, NON lanciato sul server |
| Prova dal vivo saldo Luma | lettura reale e riga del cruscotto | visto (17.779 crediti) |
| Prova dal vivo watchdog | decisione "ok" con invio finto, nessun file di stato | visto; mail reale con manutenzione ferma NON vista |
| Prova dal vivo banner con Luma sotto soglia | banner con saldo basso | NON visto (solo test) |
| Giro scene sicure | falsi allarmi del controllo di rotazione, coerenza 360p/1080p | AVVIATO, esito non noto |

Quattro invarianti: nessuna novita' rispetto al 20/11 per job persi o doppio costo; informare l'operatore una volta: il watchdog ripete al massimo ogni 6 ore (una mail per periodo), il saldo Luma avvisa dentro i controlli gia esistenti. FMEA: proposte da rivalutare con Michele - manutenzione ferma senza accorgersene (O era alto, ora con rilevamento: D in calo), credito Luma esaurito a meta' lavoro (mitigato da ricarica automatica e allarme a 8.000 crediti); i punteggi qui NON sono stati cambiati.
