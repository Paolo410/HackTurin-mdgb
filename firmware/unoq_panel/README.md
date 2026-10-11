<img src="../unoq_mcu/assets/logo.svg" alt="MDGB" width="56" align="right">

# unoq_panel — il vecchio "mdgb" con il pannello del tecnico, senza visione dentro

Owner: Salvatore Gullotta. È l'app App Lab `mdgb` di `code1.zip` (la visione gira **fuori** da App Lab, come
servizio di `ai/`) con in più il pannello del tecnico di `unoq_mcu/assets/`.

Cosa resta identico a `code1.zip`: lo sketch (preso da `unoq_mcu/sketch/`, che è uguale byte per byte),
`app.yaml` e tutte le righe di `python/main.py`. In `main.py` ci sono solo **righe aggiunte**: una per callback,
che passa il valore al pannello, più l'import e l'avvio. Senza queste la pagina non riceverebbe niente.

Il pannello non apre la camera e non parla con la visione:

- i sensori, la fase del semaforo, il badge e l'allarme arrivano dalle callback dello sketch;
- il collegamento visione → sketch dai messaggi `led_status` dello sketch ("VISIONE collegata" / "FAIL-SAFE");
- camera, riconoscimento, conteggi e passaggi dalle righe C3 che la visione scrive in `data/c3` dell'app
  (`~/ArduinoApps/mdgb/data/c3`). Serve la visione installata con `push_to_arduino.sh --applab mdgb`;
  se scrive altrove, le schede Camera e Riconoscimento restano rosse con il "cosa fare".
- La vista dal vivo con i riquadri resta sulla pagina della visione (porta 8090): il pannello ha il pulsante.

Non registra `mcu_event` sul Bridge: quelle righe le riceve già la visione e il router ne accetta uno solo.

**Verso la centrale** (aggiunto da Paolo l'11/10, con l'ok del team): `main.py` passa i valori anche a
`mdgb_link.py` di Lorenzo (preso da `comms/applab/` quando si crea lo zip). Scrive sensori, urto, badge e fail-safe in
`data/c3/applab-*.jsonl`, che la rete porta alla centrale anche a visione spenta. La visione non ne fa una seconda
copia (`mcu.save_bridge_lines: false` in `ai/config.yaml`).

**Badge del tecnico:** il codice non è più nello sketch. Sta in `../unoq_mcu/sketch/arduino_secrets.h`, ignorato da
git: si crea da `arduino_secrets.h.example`. Senza quel file `build_applab_zip.py` si ferma e lo dice.

## Creare lo zip e avviare

```bash
python firmware/tools/build_applab_zip.py --panel
```

Esce `firmware/dist/mdgb-pannello.zip` (cartella `mdgb` dentro, 12 file, nessun modello). In App Lab: cancella o
rinomina l'app `mdgb` esistente, importa lo zip, Run. Pagina su `http://<ip-scheda>:7000`. Nessuna dipendenza da
installare. Poi la visione come prima:

```bash
~/HackTurin-mdgb/ai/deploy/run_vision.sh start
```

## Provato

Sul PC con moduli `arduino.*` finti e un finto servizio della visione che scrive righe C3: stato, conteggi,
passaggi, quasi incidenti, sensori mancanti e badge compaiono nel pannello. Da verificare sulla scheda: che
`/app/data/c3` del container sia `~/ArduinoApps/mdgb/data/c3`.
