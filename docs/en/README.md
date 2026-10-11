<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/mdgb-logo-scuro.svg">
    <img src="../brand/mdgb-logo.svg" alt="MDGB, Mobility Data &amp; Guardian Beacon" width="400">
  </picture>
</p>

# MDGB

> English translation of [`README.md`](../../README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

MDGB is a module that is mounted on an existing traffic light: it sees who is arriving at the crossing, asks the
controller to extend the green or to hold the red, warns drivers and pedestrians, and sends only anonymous data to a
central office. Vision and artificial intelligence run entirely on the board, without internet. If it fails, the
traffic light goes back exactly to how it was.

Project for the GOMA Smart Crossing challenge at HackTurin, on Arduino UNO Q.

## The parts

| Folder | What it does | Who |
|---|---|---|
| [`ai/`](ai/README.md) | vision: camera, recognition, counting, traffic-light rule, technician page | Paolo Malugani |
| [`firmware/`](firmware/unoq_panel/README.md) | App Lab app: traffic-light and sensor sketch, technician panel | Salvatore Gullotta |
| [`comms/`](comms/README.md) | network from the node to the central office, Bluetooth backup | Lorenzo Dragoni |
| [`app/`](app/README.md) | the central office: map of the nodes, alarms, statistics | Lorenzo Dragoni |
| [`hardware/`](hardware/BOM.md) | circuit, sensors, bill of materials | Kuzey Bicher |
| [`docs/`](docs/CONTRACTS.md) | contracts between the parts, logo in [`docs/brand/`](docs/brand/README.md) | everyone |

**Reference documentation** (problem, system with diagrams, AI and communications in detail, business plan):
[docs/MDGB_DOCUMENTATION.md](../MDGB_DOCUMENTATION.md).

How to start everything on the board: [`ai/docs/DEPLOY_UNOQ.md`](ai/docs/DEPLOY_UNOQ.md).
Team rules for git: [`PROMPT_GIT_TEAM.md`](PROMPT_GIT_TEAM.md). Specification: [`PROMPT_SMART_CROSSING.md`](PROMPT_SMART_CROSSING.md).

The logo is a placeholder: proposals and variants (map, trailer) in [`docs/brand/`](docs/brand/README.md).

## English translations in this folder

`docs/en/` mirrors the paths of the repository: `docs/en/ai/README.md` is the translation of `ai/README.md`, and so on.
The Italian files are the reference and are updated first: a translation may lag behind.

| Translation | Original |
|---|---|
| [README](README.md) | `README.md` |
| [Specification](PROMPT_SMART_CROSSING.md) | `PROMPT_SMART_CROSSING.md` |
| [Git rules of the team](PROMPT_GIT_TEAM.md) | `PROMPT_GIT_TEAM.md` |
| [Contracts between the modules](docs/CONTRACTS.md) | `docs/CONTRACTS.md` |
| [Instructions for the others (network and central)](docs/INSTRUCTIONS_FOR_OTHERS.md) | `docs/INSTRUCTIONS_FOR_OTHERS.md` |
| [Data out of the central office: customer API and MQTT](docs/DATA_API.md) | `docs/DATA_API.md` |
| [Logo](docs/brand/README.md) | `docs/brand/README.md` |
| [ai/ README](ai/README.md) | `ai/README.md` |
| [ai/ decisions](ai/DECISIONS.md) | `ai/DECISIONS.md` |
| [Deploying ai/ on the UNO Q](ai/docs/DEPLOY_UNOQ.md) | `ai/docs/DEPLOY_UNOQ.md` |
| [How well the vision counts (benchmark)](ai/docs/BENCHMARK.md) | `ai/docs/BENCHMARK.md` |
| [Expected pedestrian flow (forecast)](ai/forecast/README.md) | `ai/forecast/README.md` |
| [comms/ README](comms/README.md) | `comms/README.md` |
| [comms/ and app/ decisions](comms/DECISIONS.md) | `comms/DECISIONS.md` |
| [app/ README](app/README.md) | `app/README.md` |
| [App Lab app with the vision inside](firmware/unoq_mcu/README.md) | `firmware/unoq_mcu/README.md` |
| [App Lab app with the panel](firmware/unoq_panel/README.md) | `firmware/unoq_panel/README.md` |
| [Bill of materials](hardware/BOM.md) | `hardware/BOM.md` |
