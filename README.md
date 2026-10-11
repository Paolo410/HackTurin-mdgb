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

Come avviare tutto sulla scheda: [`ai/docs/DEPLOY_UNOQ.md`](ai/docs/DEPLOY_UNOQ.md).
Regole del team per git: [`PROMPT_GIT_TEAM.md`](PROMPT_GIT_TEAM.md). Specifica: [`PROMPT_SMART_CROSSING.md`](PROMPT_SMART_CROSSING.md).

Il logo è un segnaposto: proposte e varianti (mappa, trailer) in [`docs/brand/`](docs/brand/README.md).
