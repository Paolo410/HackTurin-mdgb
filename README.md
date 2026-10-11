<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/mdgb-logo-scuro.svg">
    <img src="docs/brand/mdgb-logo.svg" alt="MDGB, Mobility Data &amp; Guardian Beacon" width="400">
  </picture>
</p>

# MDGB

MDGB è un modulo che si installa sul semaforo esistente: vede chi sta arrivando all'attraversamento, chiede alla
centralina di allungare il verde o di trattenere il rosso, avvisa conducenti e pedoni e manda alla centrale solo dati
anonimi. Visione e intelligenza artificiale girano tutte sulla scheda, senza internet. Se si guasta, il semaforo torna
esattamente com'era.

Progetto per la sfida GOMA Smart Crossing di HackTurin, su Arduino UNO Q.

## Le parti

| Cartella | Cosa fa | Chi |
|---|---|---|
| [`ai/`](ai/README.md) | visione: camera, riconoscimento, conteggi, regola del semaforo, pagina del tecnico | Paolo Malugani |
| [`firmware/`](firmware/unoq_panel/README.md) | app App Lab: sketch del semaforo e dei sensori, pannello del tecnico | Salvatore Gullotta |
| [`comms/`](comms/README.md) | rete del nodo verso la centrale, backup Bluetooth | Lorenzo Dragoni |
| [`app/`](app/README.md) | la centrale: mappa dei nodi, allarmi, statistiche | Lorenzo Dragoni |
| [`hardware/`](hardware/BOM.md) | circuito, sensori, distinta dei componenti | Kuzey Bicher |
| [`docs/`](docs/CONTRACTS.md) | contratti tra le parti, logo in [`docs/brand/`](docs/brand/README.md) | tutti |

**Documentazione di riferimento** (problema, sistema con diagrammi, dettagli di AI e comunicazioni, business plan):
[italiano](docs/MDGB_DOCUMENTAZIONE.md) · [English](docs/MDGB_DOCUMENTATION.md). Tutti i documenti in inglese:
[`docs/en/`](docs/en/README.md).

Come avviare tutto sulla scheda: [`ai/docs/DEPLOY_UNOQ.md`](ai/docs/DEPLOY_UNOQ.md).
Quanto conta bene la visione, verificato su video veri: [`ai/docs/BENCHMARK.md`](ai/docs/BENCHMARK.md). Istruzioni per
l'assistente AI che guida il lancio della demo e il miglioramento del modello: [`ai/docs/ISTRUZIONI_AI.md`](ai/docs/ISTRUZIONI_AI.md).
Regole del team per git: [`PROMPT_GIT_TEAM.md`](PROMPT_GIT_TEAM.md). Specifica: [`PROMPT_SMART_CROSSING.md`](PROMPT_SMART_CROSSING.md).

Il logo è un segnaposto: proposte e varianti (mappa, trailer) in [`docs/brand/`](docs/brand/README.md).

## Avviare la centrale da qualunque PC

```bash
python avvia_centrale.py        # python3 su Mac e Linux; dalla cartella del repo
```

Un solo comando: al primo avvio prepara le librerie in `app/.venv`, poi apre la centrale di `app/` (broker MQTT,
dashboard, finestra) e annuncia in rete che questo PC è `mdgb-centrale.local`. La scheda è impostata una volta
sola su quel nome (`MQTT_HOST=mdgb-centrale.local` in `comms/.env`) e segue il PC che lancia il comando: non serve
cambiare indirizzi IP quando cambia la rete o il PC, né avere accesso alla scheda.

- Una centrale alla volta: due PC che lo lanciano insieme si contendono il nome.
- Va installato a mano solo il broker Mosquitto (`brew install mosquitto`, su Windows dal sito, su Linux `apt`).
- Se la porta 8080 del PC è occupata, la dashboard usa la prima libera e lo scrive.
- `comms/deploy/push_to_arduino.sh` senza `--broker` rimette nella scheda l'IP del PC da cui parte: per tenere il
  nome va lanciato con `--broker mdgb-centrale.local`.

