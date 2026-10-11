<img src="assets/logo.svg" alt="MDGB" width="56" align="right">

# unoq_mcu — app App Lab "mdgb"

Owner: Salvatore Gullotta. Un'unica app di App Lab che fa tutto sulla UNO Q:

- `sketch/` — lo sketch del MCU (semaforo simulato, fail-safe, sensori, RFID), invariato rispetto a `code1.zip`;
- `python/main.py` — le stesse callback Bridge di prima, più `mcu_event` e l'avvio della visione;
- `python/vision.py` — camera (periferica `Camera` di App Lab) → `smartcrossing` di `ai/` (profilo `unoq`) →
  C1/C2 allo sketch con `Bridge.call("mdgb_line", ...)` → pagina web;
- `python/health.py` — controllo di ogni parte del nodo, una volta al secondo (vedi sotto);
- `assets/` — pannello del tecnico: riepilogo, controllo sensori, semaforo, vista dal vivo con i riquadri,
  traffico, registro.

## Pannello del tecnico (porta 7000)

Pensato per un tecnico con il telefono, anche all'aperto: tema chiaro (scuro se il dispositivo lo chiede), colori
della segnaletica, font di sistema (funziona senza internet). Tre schede:

- **Stato**: una frase in cima ("Tutto funziona", "Una cosa da controllare", "2 cose da sistemare"), poi le parti
  da sistemare con il **cosa fare**, poi una riga per ogni parte che funziona; a lato il semaforo e i dettagli
  tecnici (richiudibili).
- **Traffico**: vista dal vivo con i riquadri (nella versione pannello, il pulsante per la pagina della visione) e
  i passaggi contati.
- **Registro**: eventi in frasi, filtrabili (Sensori, Traffico, Sicurezza), scaricabili in un file di testo.

Le parti controllate:

| Parte | Come si controlla | Non funziona se |
|---|---|---|
| Camera | arrivano immagini; autodiagnosi della visione | nessuna immagine da 2 s; lente coperta o abbagliamento = da controllare |
| Riconoscimento (AI) | fotogrammi elaborati | fermo da 3 s; sotto 5 FPS = da controllare |
| Collegamento con lo sketch | heartbeat accettati dallo sketch | sketch in fail-safe |
| Ciclo del semaforo | `led_status` dello sketch | nessun cambio di fase da 60 s |
| Accelerometro | `sensor_movement` | nessun dato da 5 s o sempre 0; fuori da 0,65–1,15 g = scossa |
| Temperatura e umidità (AHT20) | `sensor_env` | nessun dato da 5 s o lettura a −50 °C (sensore muto) |
| Qualità dell'aria (SGP30) | `sensor_air` | nessun dato da 5 s |
| Sensore di luce | `sensor_light` | nessun dato da 5 s; sempre 0 o sempre al massimo = da controllare |
| Lettore badge | `rfid_data` | — si prova passando il badge ("da provare" finché non succede) |
| Salvataggio eventi | file C3 in `data/` | errore di scrittura |

Nei primi 15 s dall'avvio le parti senza dati sono "in attesa", non guaste. Ogni cambio di stato finisce nel
registro (scheda "Sensori") e nella console di App Lab con il prefisso `diagnosi:`. Il registro tiene gli ultimi
100 eventi solo in memoria; "Scarica" salva sul dispositivo del tecnico un file di testo con il controllo sensori e
gli eventi. Il semaforo non dipende da questi controlli.

Il codice della visione **non è copiato qui**: lo script di build mette dentro `python/` il pacchetto
`ai/smartcrossing`, `config.yaml`, la calibrazione e il modello presi dal repo.

## Creare lo zip

```bash
python firmware/tools/build_applab_zip.py
```

Esce `firmware/dist/mdgb.zip` (ignorato da git). Serve `ai/models/yolox_nano_dynamic.onnx`
(`bash ai/scripts/get_model.sh`), oppure `--models-dir <cartella con il modello>`.
Se c'è `ai/calib.json` viene usato quello, altrimenti `calib.example.json` (i riquadri si vedono lo stesso;
zone, linee di conteggio e velocità sono giuste solo con la calibrazione della camera vera).

## Avviare

1. App Lab → My Apps → importa `mdgb.zip`; se esiste già un'app `mdgb`, cancellala o rinominala prima.
2. Run. Al primo avvio App Lab installa `python/requirements.txt` (onnxruntime, supervision): ci vuole qualche minuto.
3. Apri la pagina dell'app (pulsante di App Lab, oppure `http://<ip-scheda>:7000`).

Variabili d'ambiente facoltative: `MDGB_CAMERA=csi:0` per scegliere la camera (default: la prima libera),
`MDGB_LIVE_VIEW=0` per mandare alla pagina solo i riquadri e i numeri, senza immagine.

La camera la usa questa app: non avviare insieme `ai/deploy/run_vision.sh` o il servizio `mdgb-ai`.

## Provato

- Sul PC, con moduli `arduino.*` finti e un video al posto della camera: profilo `unoq` a circa 12 FPS,
  C1 e heartbeat verso lo sketch, eventi C3 scritti, pagina con i riquadri giusti.
- Da verificare sulla scheda: installazione di `requirements.txt` nel container, ordine dei colori di
  `Camera.capture()` (atteso BGR), FPS reali.

## Badge del tecnico e cicalino (11/10)

- Il codice del badge autorizzato sta in `sketch/arduino_secrets.h` (`SECRET_TECH_BADGE`), ignorato da git; nel repo
  c'è solo `sketch/arduino_secrets.h.example`.
- Cicalino muto mentre c'è il tecnico: dal badge 2 minuti di silenzio, anche senza visione, poi finché la visione
  manda `"tech": true` nel comando C1, cioè fino al logout dalla pagina. Resta il bip di conferma del badge.
  Senza heartbeat il campo non vale più e l'antifurto torna a suonare (`ai/DECISIONS.md`, punto 36).
- Prova su PC, con un badge finto: `firmware/unoq_mcu/host_test/run.sh`, che stampa "all checks passed".

