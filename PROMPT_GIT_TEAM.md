# Regole Git del team — HackTurin

> **Per gli umani.** A inizio di ogni chat con l'AI scrivete:
>
> ```text
> Leggi PROMPT_GIT_TEAM.md e seguilo per tutta la sessione. Sono <nome>. Task: <cosa devo fare>.
> ```
>
> Solo per il setup iniziale (una persona, una volta, dopo aver scelto la sfida):
>
> ```text
> Leggi PROMPT_GIT_TEAM.md ed esegui il Setup. Sfida: <sfida>. Team: <nome> firmware, <nome> vision, <nome> app, <nome> docs.
> ```

---

Da qui in poi le istruzioni sono per te, assistente AI. Rispondi in italiano.

## Contesto

Hackathon hardware HackTurin: Arduino UNO Q + AI e computer vision in locale. Siamo 4 persone che lavorano in parallelo su questo repo (https://github.com/Paolo410/HackTurin-mdgb), ognuna con il proprio assistente AI. Oltre a scrivere codice, il tuo compito più importante è non pestare i piedi agli altri: segui alla lettera queste regole.

## Divisione del team

Sfida: _da decidere_

| Persona        | Area                                        | Cartelle        |
|----------------|---------------------------------------------|-----------------|
| _da assegnare_ | firmware e hardware (Arduino, sensori, LED) | firmware/       |
| _da assegnare_ | computer vision / AI locale                 | vision/         |
| _da assegnare_ | app / backend / dashboard                   | app/            |
| _da assegnare_ | integrazione, script, documentazione, pitch | docs/, scripts/ |

## Inizio sessione

Se l'utente ti ha chiesto il Setup, vai alla sezione [Setup](#setup). Altrimenti, prima di scrivere codice:

1. Trova l'utente nella tabella "Divisione del team": la sua area e le sue cartelle. Se la tabella è ancora da assegnare o il suo nome non c'è, fermati e diglielo: il Setup lo fa una persona sola, non farlo tu.
2. Lancia `git status`. Se ci sono modifiche non committate, diglielo prima di fare qualsiasi altra cosa.
3. Se non è già fatto, configura il repo: `git config pull.rebase true`, `git config rerere.enabled true`, `git config fetch.prune true`, `git config push.autoSetupRemote true`.
4. `git fetch origin`, poi crea un branch nuovo da main aggiornato: `git switch -c <nome-in-minuscolo>/<descrizione-breve> origin/main`. Non lavorare mai direttamente su main.
5. Leggi `docs/CONTRACTS.md` e il README delle cartelle dell'utente.
6. Riassumi in 3 righe il piano e quali file toccherai, poi parti.

## Regole

### Perimetro
- Modifica solo i file nelle cartelle dell'utente. Se serve una modifica nell'area di un altro, non farla: di' all'utente esattamente cosa serve, la chiederà all'owner.
- File condivisi (questo file, `docs/CONTRACTS.md`, `.gitignore`, README principale, config in root): modifiche minime, solo aggiunte, in un commit separato. Avvisa l'utente, perché vanno comunicate al team.
- Senza OK esplicito dell'utente non: rinominare o spostare file e cartelle, riformattare file interi, cambiare la config di formatter/linter, aggiornare versioni di dipendenze, cancellare file che non hai creato tu.

### Interfacce
- I moduli comunicano solo come scritto in `docs/CONTRACTS.md`. Scrivi codice contro il contratto; se l'altra parte non è ancora pronta, crea un mock o un simulatore dentro le cartelle dell'utente.
- Se il contratto va cambiato, fermati e proponilo all'utente: rompe il lavoro degli altri e va concordato col team.

### Commit
- Commit piccoli e frequenti, uno per modifica logica. Formato: `tipo(area): descrizione` (tipi: feat, fix, refactor, docs, chore, test). Es.: `feat(vision): conteggio attraversamenti per direzione`.
- Mai `git add .` o `git add -A` alla cieca: aggiungi i file per nome e controlla `git diff --staged` prima di committare.
- Mai committare: `.env`, token o API key, password WiFi (su Arduino stanno in `arduino_secrets.h`, ignorato da git; si committa solo `arduino_secrets.h.example`), pesi dei modelli, dataset, foto o video sopra i 5 MB, virtualenv, file generati. Se manca una regola nel `.gitignore`, aggiungila (è un file condiviso: avvisa l'utente).
- Notebook Jupyter: preferisci script `.py`. Se servono, solo nelle cartelle dell'utente e con gli output puliti prima del commit.

### Sincronizzazione e merge
- Ogni 45–60 minuti, o appena qualcosa funziona: `git fetch origin && git rebase origin/main`, verifica che compili/giri ancora, poi `git push` (vale anche come backup).
- Dopo il rebase di un branch già pushato: `git push --force-with-lease`, solo sul branch dell'utente. Mai force push su main.
- Branch corti (massimo 2–3 ore). Appena una parte funziona, anche incompleta ma non rotta, va su main con una Pull Request in squash merge (`gh pr create` se disponibile, altrimenti dai all'utente il link GitHub). Prima del merge: rebase su origin/main e test. L'utente può mergiare da solo; se la PR tocca contratti o file condivisi, la fa guardare a un compagno.
- main deve funzionare sempre: è la demo. Mai push diretto su main.
- Dopo il merge: cancella il branch, `git switch main && git pull`, e branch nuovo per il task successivo. Non riusare un branch già mergiato.

### Conflitti
- Conflitti nelle cartelle dell'utente: risolvili mantenendo le intenzioni di entrambe le versioni e spiega cosa hai fatto.
- Conflitti in file di altri o condivisi: fermati, mostra il conflitto all'utente e proponi una soluzione. Non scegliere in blocco "ours" o "theirs".
- Dopo aver risolto: ricompila/riesegui prima di continuare.

### Comandi pericolosi
- Chiedi conferma prima di: `git reset --hard`, `git clean`, `git restore .` / `git checkout -- .`, `git stash drop`, `git branch -D`, qualunque push con `--force`, cancellare file.

### Dipendenze
- Python: il `requirements.txt` nella cartella dell'utente, con versioni fissate. Ogni nuova dipendenza va scritta nel messaggio di commit.
- Librerie Arduino: elencale con la versione nel README di `firmware/`.

### Più agenti in parallelo
- Se l'utente lancia più agenti AI sullo stesso computer, ognuno lavora in un worktree separato: `git worktree add ../HackTurin-<task> -b <nome>/<task> origin/main`. Mai due agenti nella stessa cartella.

### Stile di lavoro
- È un hackathon: demo funzionante prima di codice perfetto. Niente refactoring non richiesti, niente over-engineering, niente feature non chieste.
- Se non puoi eseguire comandi (es. chat web), dai all'utente i comandi esatti da lanciare, uno alla volta.
- Se non sei sicuro che un'azione tocchi il lavoro di altri o sia distruttiva, chiedi.

## Fine task

Prima del merge scrivi all'utente un messaggio di 3–5 righe da incollare nella chat del team:
- branch e cosa fa
- file e aree toccate
- cambi a contratti, file condivisi o nuove dipendenze (oppure "nessuno")
- come provarlo

## Setup

Solo se l'utente lo chiede esplicitamente. Lo fa una persona sola, una volta, prima che gli altri inizino. Non scrivere ancora codice applicativo.

1. `git switch main && git pull`. Il working tree deve essere pulito, altrimenti fermati e dillo.
2. Compila la sezione "Divisione del team" di questo file con la sfida e i nomi che ti ha dato l'utente. Adatta aree e cartelle solo se te lo chiede.
3. Crea le cartelle della tabella, ognuna con un README.md breve: owner, scopo, come si avvia/compila, dipendenze, versione di Python se serve.
4. Crea `docs/CONTRACTS.md` con le interfacce tra i moduli (es. protocollo seriale Arduino↔PC, formato JSON degli eventi, topic MQTT, endpoint HTTP). Per ogni interfaccia: chi produce, chi consuma, formato con un esempio concreto, numero di versione. Proponi una prima bozza in base alla sfida e aspetta la conferma dell'utente prima di scriverla.
5. Aggiorna `.gitignore`: `.env`, `arduino_secrets.h`, pesi dei modelli (`*.pt`, `*.onnx`, `*.tflite`, `models/`), `dataset/`, video, `.DS_Store`, `.vscode/`, cartelle di build di Arduino. Aggiungi `.gitattributes` con `* text=auto eol=lf` per evitare diff fantasma tra Windows e Mac.
6. Python: un `requirements.txt` per ogni modulo (es. `vision/requirements.txt`), non uno unico in root.
7. Crea `CLAUDE.md` con la sola riga `@PROMPT_GIT_TEAM.md` e `AGENTS.md` con la riga `Leggi e segui PROMPT_GIT_TEAM.md.`, così gli assistenti che li supportano caricano queste regole anche senza il comando.
8. Mostra `git status` e `git diff --staged`, poi fai un unico commit `chore: struttura repo, ownership e contratti` direttamente su main (unica eccezione alla regola "mai su main") e push.
9. Scrivi all'utente il messaggio da mandare al team: "fate git pull, poi iniziate ogni chat con il comando in cima a PROMPT_GIT_TEAM.md".

## Per chi gestisce il repo (umani)

1. GitHub → Settings → Collaborators: aggiungere gli altri tre.
2. **Dopo** il commit del Setup: Settings → Branches → regola su `main` con "Block force pushes" e "Require a pull request before merging" (0 approvazioni, così si può mergiare da soli). Prima del Setup bloccherebbe il suo commit diretto su main.
3. Settings → General → Pull Requests: lasciare attivo solo "Allow squash merging" e attivare "Automatically delete head branches".
