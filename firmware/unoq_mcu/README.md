# unoq_mcu — app App Lab "mdgb"

Owner: Salvatore Gullotta. Un'unica app di App Lab che fa tutto sulla UNO Q:

- `sketch/` — lo sketch del MCU (semaforo simulato, fail-safe, sensori, RFID), invariato rispetto a `code1.zip`;
- `python/main.py` — le stesse callback Bridge di prima, più `mcu_event` e l'avvio della visione;
- `python/vision.py` — camera (periferica `Camera` di App Lab) → `smartcrossing` di `ai/` (profilo `unoq`) →
  C1/C2 allo sketch con `Bridge.call("mdgb_line", ...)` → pagina web;
- `assets/` — pagina web: immagine dal vivo con i riquadri su persone, ciclisti, veicoli e animali, stato del
  semaforo, motivo, FPS, ms per fase, conteggi.

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
