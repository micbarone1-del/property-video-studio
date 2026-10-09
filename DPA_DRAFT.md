# Accordo sul trattamento dei dati per la fase di test -- BOZZA 2026-10-09

_Bozza di lavoro, non e' consulenza legale: va fatta rivedere da un legale prima della firma. I dati delle parti sono segnaposto._

**Parti.** Relinx [ragione sociale, sede] (titolare del trattamento) e [Fornitore -- Property Video Studio] (responsabile del trattamento).

1. **Oggetto e finalita'.** Il responsabile elabora foto, descrizioni e dati dell'annuncio ricevuti via API solo per produrre il video richiesto dall'agenzia. Nessun altro uso e nessun addestramento di modelli sui dati.
2. **Dati trattati.** Foto degli immobili, descrizioni e indirizzi, testo dell'agenzia, logo. Non sono previsti dati personali di acquirenti o inquilini. Se nelle foto compaiono persone o targhe, il titolare lo segnala e il responsabile puo' oscurarle o scartare l'immagine.
3. **Sub-responsabili.** Il responsabile usa fornitori di intelligenza artificiale e di hosting per elaborare immagini e generare voce e video (elenco allegato, aggiornato su richiesta). I termini dei fornitori vanno verificati sul punto dell'uso dei dati per l'addestramento.
4. **Conservazione.** Foto e video dei test sono cancellati entro [30] giorni dalla fine della fase di test, salvo diversa richiesta del titolare. I backup seguono la stessa scadenza.
5. **Sicurezza.** Accesso protetto da chiave, connessione cifrata, link con scadenza, registro degli accessi.
6. **Violazioni.** Il responsabile avvisa il titolare entro 48 ore da una violazione dei dati.
7. **Cancellazione e restituzione.** Su richiesta o a fine accordo il responsabile cancella o restituisce i dati e lo conferma per iscritto.
8. **Diritti sulle immagini.** Il titolare conferma di avere il diritto di usare le foto fornite e che le agenzie hanno dato il consenso all'uso su questo servizio.
9. **Durata.** Dalla firma alla fine della fase di test, rinnovabile per il pilota.

Data, luogo, firme.

## Da verificare prima di inviarla (nostro lato)
- Punto 3: contratti reali dei fornitori (Anthropic, ElevenLabs, fal, Luma, Google/Veo, hosting): uso dei dati, regione, conservazione.
- Punto 4: la retention reale oggi (backup nightly 30 giorni in /var/backups/pvs_jobs/) deve combaciare con quanto promesso.
- Punto 8: risposta di Relinx sulla liberatoria delle agenzie (Q4).
