# Aggiornamento documenti - venerdi 20 novembre 2026 (una volta al giorno)

Stato: TESTO PRONTO, NON ancora applicato a status.md, backlog.md, AUTOMATION_TEST_PLAN.md nel repository. Ogni voce dice cosa e' verificato e con quale prova (output incollato da Michele nella chat del 20/11). Cio' che non e' stato visto resta "non visto". I punteggi FMEA sono proposte, non rivalutati qui.

Commit sul server: 19269f1 (doppioni + monitor job fermi, in produzione dalle 14:06 UTC) -> 6f057d1 (simulatore: voce Google finta + script dei percorsi di errore) -> befba69 (casella "Da fare" + avviso tetto di spesa + test idempotenza; in produzione dalle 15:56 UTC). Rollback del deploy di oggi: 19269f1 (hash completo 19269f1555f9562b17f0aa33c190b3547402aeaa). Rollback precedente: f088cce.

---

## DA AGGIUNGERE A status.md

### 2026-11-20 - Verificato oggi

- **Monitor job fermi ricostruito** (maintenance_scheduler.py). Prima non funzionava (file, stati e campi sbagliati). Ora: stati running/preparing, ultima attivita' = file piu' recente nella cartella del job, ogni 10 minuti, avviso rosso con id e minuti. test_stuck_jobs 13/13. SOGLIA 45 MINUTI PROVVISORIA (un solo campione pulito: 18 minuti di generazione, silenzio massimo 3 minuti): da rivedere dopo i primi video reali Relinx. Non ancora visto scattare su un job realmente fermo.
- **Controllo doppioni sull'API partner** (partner_duplicates.py) in produzione dal commit 19269f1. Sull'istanza finta: stesso annuncio con riferimento diverso crea il job, lo collega al primo (possible_duplicate_of) e manda UNA mail "Possibile doppione". Non ancora visto su una richiesta reale.
- **Richieste ripetute / idempotenza** (fake_idempotency.py, 10 verifiche su 10 PASS): stesso external_ref due volte = stesso job, una cartella, una mail; 8 richieste simultanee = un solo job (il sospetto di race condition NON si e' verificato in questa prova, quindi nessuna modifica al codice; resta una sola esecuzione, non una prova generale); dopo un job fallito lo stesso riferimento puo' creare un nuovo job (voluto).
- **Webhook con agenzia non raggiungibile + riavvio** (fake_webhook_fail.py, 10/10 PASS): 4 tentativi a 1, 5 e 15 minuti, dopo il riavvio i tentativi riprendono (3 dopo 101 secondi), stato finale "fallito", UNA sola mail all'operatore, nessun tentativo dopo l'ultimo, l'URL di callback non compare nello stato salvato, l'API partner mostra comunque il risultato.
- **Percorsi di fallimento** (istanza finta): foto insufficienti (T3) e rifiuto dell'operatore (T2) PASS: job conservato, stato e codice corretti, un solo webhook, nota interna mai all'agenzia, secondo rifiuto bloccato. T1 (tutte le clip falliscono) = il job resta in attesa (awaiting_approval/in_review), l'operatore e' avvisato, l'agenzia NON riceve webhook. RISCHIO ACCETTATO da Michele il 2026-11-20 ("Lascia com'e"). Chiamate Luma per un job da 6 scene tutto fallito: 24 (limitate, non un ciclo infinito).
- **Clip in parte riuscite, in parte fallite** (fake_partial_clips.py, 11 PASS e 1 FAIL): 6 scene, 3 con clip e 3 senza -> job in attesa, agenzia non avvisata, 15 chiamate Luma (5 per scena). Rifacendo SOLO le scene mancanti (endpoint approve): video completato, clip buone intatte, nessuna chiamata Luma oltre le scene mancanti, nessun webhook prima del rilascio. Il FAIL (P1e) e' un difetto del TEST, non del server; ma ha mostrato una cosa vera: con clip mancanti arrivano DUE mail per lo stesso problema ("Clip mancanti" e "Rework incompleto"). Michele (2026-11-20): lasciare cosi' per ora. Difetto minore, da rivedere se diventa rumoroso.
- **Casella "Da fare" nella dashboard** (operator_inbox.py, commit befba69, in produzione dalle 15:56 UTC; rollback 19269f1): ogni avviso inviato per mail o notifica viene anche salvato (un solo punto di scrittura: maintenance_scheduler.send_notification, nessuno invia mail o notifiche per altre strade, controllato nel test). Le azioni aperte stanno in cima con il pulsante "Fatto"; le informazioni (es. nuovo job) in una sezione chiusa. Si chiudono da sole: avvisi di un job quando viene rilasciato o rifiutato; avvisi del tetto quando il job parte. Verificato dal vivo: sezione presente, 0 azioni, rilascio manuale, avvio automatico acceso, nessun errore nel log. test_operator_inbox 23/23 (compresi 5 casi del tetto). Suite esistente: stessi 23 file non eseguibili nel mio ambiente di prova prima e dopo (librerie mancanti), nessuna rottura nuova; sul server i test collegati (webhook, clip fallite, avvio automatico, job fermi, doppioni, messaggi partner, voce Google finta) passano. Non ancora visto con un avviso reale in produzione.
- **Avviso del tetto di spesa giornaliero**: UNA mail e notifica per job quando e' fermo per il tetto (flag cap_alerted, il testo del motivo cambia con la spesa ma l'avviso no); l'attesa per slot occupato resta silenziosa. ATTENZIONE: in produzione il tetto e' PVS_AUTO_START_CAP_EUR=100, non il 30 di default: l'avviso scatta solo oltre 100 EUR impegnati in 24 ore. Da decidere il valore al lancio.
- **Monitor di arrivo clip** (PVS_ARRIVAL_MONITOR=1): e' di sola misura, registra e non manda nessun avviso. Niente da testare; se vuoi un avviso e' una nuova voce di backlog.
- **Simulatore**: aggiunta la voce Google finta (la voce predefinita non era simulata e ogni narrazione falliva), test G1-G7 PASS. Limiti noti dell'istanza finta: il testo finto di Claude non supera il controllo fatti, quindi l'avvio automatico rifiuta le bozze e i job si avviano a mano con start-generation.
- **Aperto con Relinx**: il 401 NON e' risolto, si aspetta Relinx; nessuna rotazione della chiave. Il segreto di firma dei webhook non e' impostato (WEBHOOK_SIGNING_SECRET vuoto -> webhook non firmati): da chiedere a Relinx.

### 2026-11-20 - Test 360p contro 1080p: AVVIATO, esito non noto
- Correzione di costo: il backlog del 19/11 diceva "circa 1-2 USD". Rifacendo il conto (3 bozze da 0,06 + 2 clip 1080p da 1,20 per scena) un'unica scena costa circa 2,58 USD. Michele ha scelto il disegno a 4 scene e 2 clip 1080p: 20 clip, 10,32 USD, tetto bloccato a 11 USD.
- Scene scelte dal registro dell'istanza di test a 360p (>= 2 esiti non-pass): 5dc50e0a scena 4 (bagno), ac81fedd scena 5 (esterno giardino), 50567a81 scena 0 (esterno), 50567a81 scena 4 (camera). Nessuna scena "sempre sicura" nel registro: i falsi allarmi NON sono misurati.
- Strumento: exp_res_compare.py (+ test_exp_res_compare.py, 11/11), passa dalla funzione di produzione, giudizio alla cieca (codici, clip mescolati). Avviato alle 17:08 ora di Roma in screen `rescmp`, log /tmp/rescmp.log. L'avvio e' visto, l'avanzamento no.
- Dopo: Michele guarda i video alla cieca e da' bad/part/ok per codice; poi `score` (gratis). Il risultato va comunicato a Douglas (Luma): la richiesta del test era sua.

---

## DA AGGIUNGERE A backlog.md

### 2026-11-20 - Decisioni di Michele
1. Webhook: 3 nuovi tentativi (1, 5, 15 minuti) poi UN avviso all'operatore (confermato dal test).
2. Doppioni: il video viene creato e l'operatore e' avvisato.
3. Consegna all'agenzia: manuale finche' Michele non decide diversamente.
4. Tutte le clip fallite: il job resta in attesa per Relinx, operatore avvisato. Rischio accettato il 2026-11-20 ("Lascia com'e").
5. Due mail per lo stesso problema di clip mancanti: lasciare cosi' (2026-11-20). Difetto minore.
6. Relinx 401: aspettare Relinx, nessuna rotazione di chiave.
7. Documenti (status.md, backlog.md, AUTOMATION_TEST_PLAN.md): aggiornati una volta al giorno.
8. Notifiche: tutte nella dashboard con le azioni importanti aperte in cima (fatto, befba69).

### Voci aperte
- Criteri di rilascio automatico (punto 10): proposta da fare a Michele, decide lui.
- Avviso per il monitor di arrivo clip: da decidere se serve.
- Tetto di spesa: 100 EUR in produzione, valore di lancio da decidere.
- Soglia job fermi 45 minuti provvisoria: rivedere dopo i primi video reali.
- Test P1e del file fake_partial_clips.py da correggere (deve cercare l'oggetto reale della mail e aspettarsi 2 avvisi, non 1).
- Test 360p contro 1080p: attendere il risultato e dirlo a Douglas; considerare in un secondo giro scene note come sicure per misurare i falsi allarmi.
- Segreto di firma dei webhook: chiedere a Relinx.
- Video completo con la nuova narrazione (THRINAKIE, circa 9-12 EUR, rilascio manuale).
- Riparazione JSON del Director con un nuovo tentativo; guardia per stanze principali mancanti; "Rigenera narrazione" cancella la timeline sui job ancorati.
- PVS_PARTNER_AGENCY_LIMIT_24H da 20 a 2 al lancio; consegna sicura della chiave; chiave fal inutilizzata e chiave server con scadenza; retention dei backup; riconciliare la fattura Luma con cost_actual.

---

## DA AGGIUNGERE A AUTOMATION_TEST_PLAN.md

### 2026-11-20 - Test aggiunti e risultati (prova = output incollato da Michele il 20/11, salvo dove scritto)
| Test | Cosa verifica | Esito |
|---|---|---|
| test_stuck_jobs SJ1-SJ13 | monitor job fermi | 13/13 PASS |
| test_fake_google_tts G1-G7 | voce Google finta | 7/7 PASS |
| fake_failure_paths T3, T2 | foto insufficienti, rifiuto operatore | PASS |
| fake_failure_paths T1 | tutte le clip falliscono | giudizio: rischio accettato 2026-11-20 |
| fake_webhook_fail W1-W9 | webhook non raggiungibile + riavvio | 10/10 PASS |
| fake_idempotency I1-I4 | richieste ripetute, doppioni, nuovo tentativo dopo fallimento | 10/10 PASS |
| fake_partial_clips P1-P2 | clip in parte fallite, rifacimento delle sole mancanti | 11 PASS / 1 FAIL (P1e = difetto del test, vedi sopra) |
| test_operator_inbox OI1-OI17, CAP1-CAP5 | casella dashboard, un solo punto di scrittura, avviso tetto una volta | 23/23 PASS (eseguito nella mia copia e sul server) |
| test_exp_res_compare R1-R11 | strumento test 360p, tetto di spesa rigido | 11/11 PASS (server) |
| Prova dal vivo casella | sezione presente, nessun errore | visto; avviso reale in produzione NON ancora visto |
| Test 360p contro 1080p | scene rischiose a 360p lo sono anche a 1080p | AVVIATO, esito non noto |

Quattro invarianti (nessun job perso, nessun doppio costo, stato finale corretto e visibile, operatore avvisato una volta): rispettate nei test sopra, con due eccezioni note: clip mancanti (due mail, accettato) e tutte le clip fallite (job in attesa, accettato). FMEA: righe da rivalutare con Michele (webhook non consegnato, richiesta ripetuta, tetto di spesa senza avviso, job fermi, clip in parte fallite); i punteggi qui NON sono stati cambiati.
