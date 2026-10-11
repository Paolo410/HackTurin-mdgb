# Team Git rules — HackTurin

> English translation of [`PROMPT_GIT_TEAM.md`](../../PROMPT_GIT_TEAM.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

> **For the humans.** At the start of every chat with the AI write:
>
> ```text
> Leggi PROMPT_GIT_TEAM.md e seguilo per tutta la sessione. Sono <nome>. Task: <cosa devo fare>.
> ```
>
> ("Read PROMPT_GIT_TEAM.md and follow it for the whole session. I am <name>. Task: <what I have to do>.")
>
> Only for the initial setup (one person, once, after choosing the challenge):
>
> ```text
> Leggi PROMPT_GIT_TEAM.md ed esegui il Setup. Sfida: <sfida>. Team: <nome> data scientist, <nome> embedded, <nome> communication, <nome> electronics.
> ```
>
> ("Read PROMPT_GIT_TEAM.md and run the Setup. Challenge: <challenge>. Team: <name> data scientist, ...")

---

From here on the instructions are for you, AI assistant. Answer in Italian.

## Context

HackTurin hardware hackathon: Arduino UNO Q + local AI and computer vision. We are 4 people working in parallel on this
repo (https://github.com/Paolo410/HackTurin-mdgb), each with their own AI assistant. Besides writing code, your most
important job is not to step on the others' toes: follow these rules to the letter.

## Team split

Challenge: GOMA - Smart Crossing Challenge

| Person         | Role                   | Area                                                                                  | Folders                          |
|----------------|------------------------|---------------------------------------------------------------------------------------|----------------------------------|
| Paolo Malugani | Data scientist         | local AI models and computer vision (training, export, inference), dataset, data analysis | ai/                          |
| Salvatore Gullotta | Embedded engineer  | Arduino UNO Q firmware (sketch on the microcontroller, integration with the Linux side), real-time logic | firmware/ |
| Lorenzo Dragoni | Communication engineer | communication between devices (serial, WiFi, MQTT/HTTP), backend and dashboard       | comms/, app/, docs/CONTRACTS.md  |
| Kuzey Bicher | Electronics engineer     | circuit, sensors, LEDs and actuators, power supply, schematics, BOM, pinout            | hardware/                        |

- `docs/CONTRACTS.md` has an owner: the communication engineer. The pinout section is decided by the electronics engineer.
- `docs/` (pitch, presentation) and the main README are shared: everybody can add, nobody rewrites the others' work.

## Session start

If the user asked you for the Setup, go to the [Setup](#setup) section. Otherwise, before writing code:

1. Find the user in the "Team split" table: their area and their folders. If the table is still to be assigned or their
   name is not there, stop and tell them: the Setup is done by one person only, do not do it yourself.
2. Run `git status`. If there are uncommitted changes, tell them before doing anything else.
3. If not done yet, configure the repo: `git config pull.rebase true`, `git config rerere.enabled true`,
   `git config fetch.prune true`, `git config push.autoSetupRemote true`.
4. `git fetch origin`, then create a new branch from an up-to-date main:
   `git switch -c <lowercase-name>/<short-description> origin/main`. Never work directly on main.
5. Read `docs/CONTRACTS.md` and the README of the user's folders.
6. Summarise in 3 lines the plan and which files you will touch, then start.

## Rules

### Perimeter
- Modify only the files in the user's folders. If a change is needed in someone else's area, do not make it: tell the
  user exactly what is needed, they will ask the owner.
- Shared files (this file, `.gitignore`, main README, `docs/`, config in root): minimal changes, additions only, in a
  separate commit. Warn the user, because they must be communicated to the team.
- Without the user's explicit OK do not: rename or move files and folders, reformat whole files, change the
  formatter/linter config, update dependency versions, delete files you did not create.

### Interfaces
- The modules communicate only as written in `docs/CONTRACTS.md`: messages between devices, format of the AI model
  events, pinout. Write code against the contract; if the other side is not ready yet, create a mock or a simulator
  inside the user's folders.
- If the contract must change, stop and propose it to the user: it breaks the others' work and must be agreed with the
  team. Only the communication engineer modifies it; the pinout only the electronics engineer.

### Commits
- Small and frequent commits, one per logical change. Format: `type(area): description` (types: feat, fix, refactor,
  docs, chore, test). E.g.: `feat(ai): conteggio attraversamenti per direzione` (crossing count per direction).
- Never `git add .` or `git add -A` blindly: add the files by name and check `git diff --staged` before committing.
- Never commit: `.env`, tokens or API keys, WiFi passwords (on Arduino they are in `arduino_secrets.h`, ignored by git;
  only `arduino_secrets.h.example` is committed), model weights, datasets, photos or videos above 5 MB, virtualenvs,
  generated files. If a rule is missing in `.gitignore`, add it (it is a shared file: warn the user).
- Jupyter notebooks: prefer `.py` scripts. If needed, only in the user's folders and with the outputs cleared before
  the commit.

### Sync and merge
- Every 45–60 minutes, or as soon as something works: `git fetch origin && git rebase origin/main`, check that it still
  compiles/runs, then `git push` (it is also a backup).
- After the rebase of a branch already pushed: `git push --force-with-lease`, only on the user's branch. Never force
  push on main.
- Short branches (2–3 hours at most). As soon as a part works, even incomplete but not broken, it goes on main with a
  Pull Request in squash merge (`gh pr create` if available, otherwise give the user the GitHub link). Before the merge:
  rebase on origin/main and test. The user can merge by themselves; if the PR touches contracts or shared files, they
  have a teammate look at it.
- main must always work: it is the demo. Never push directly to main.
- After the merge: delete the branch, `git switch main && git pull`, and a new branch for the next task. Do not reuse a
  branch already merged.

### Conflicts
- Conflicts in the user's folders: resolve them keeping the intentions of both versions and explain what you did.
- Conflicts in other people's or shared files: stop, show the conflict to the user and propose a solution. Do not pick
  "ours" or "theirs" wholesale.
- After resolving: recompile/rerun before continuing.

### Dangerous commands
- Ask for confirmation before: `git reset --hard`, `git clean`, `git restore .` / `git checkout -- .`, `git stash drop`,
  `git branch -D`, any push with `--force`, deleting files.

### Dependencies
- Python: the `requirements.txt` in the user's folder, with pinned versions. Every new dependency must be written in the
  commit message.
- Arduino libraries: list them with the version in the README of `firmware/`.
- Electronics: `hardware/` holds the source files of the schematics (KiCad, Fritzing…) plus a PNG/PDF export readable
  by everybody, and the BOM. Datasheets are linked in the README, not committed.

### Several agents in parallel
- If the user launches several AI agents on the same computer, each works in a separate worktree:
  `git worktree add ../HackTurin-<task> -b <name>/<task> origin/main`. Never two agents in the same folder.

### Work style
- It is a hackathon: working demo before perfect code. No unrequested refactoring, no over-engineering, no unrequested
  features.
- If you cannot run commands (e.g. web chat), give the user the exact commands to run, one at a time.
- If you are not sure whether an action touches the others' work or is destructive, ask.

## End of task

Before the merge write the user a 3–5 line message to paste in the team chat:
- branch and what it does
- files and areas touched
- changes to contracts, shared files or new dependencies (or "none")
- how to try it

## Setup

Only if the user explicitly asks for it. Done by one person only, once, before the others start. Do not write
application code yet.

1. `git switch main && git pull`. The working tree must be clean, otherwise stop and say so.
2. Fill in the "Team split" section of this file with the challenge and the names the user gave you. Adapt areas and
   folders only if asked.
3. Create the folders of the table plus `docs/`, each with a short README.md: owner, purpose, how to start/compile,
   dependencies, Python version if needed.
4. Create `docs/CONTRACTS.md` with the interfaces between the modules (e.g. events out of the AI model, calls between
   the Linux side and the microcontroller of the UNO Q, MQTT topics, HTTP endpoints). For each interface: who produces,
   who consumes, format with a concrete example, version number. Add a Pinout section (pin, component, direction, notes)
   to be filled in by the electronics engineer. Propose a first draft based on the challenge and wait for the user's
   confirmation before writing it.
5. Update `.gitignore`: `.env`, `arduino_secrets.h`, model weights (`*.pt`, `*.onnx`, `*.tflite`, `models/`),
   `dataset/`, videos, `.DS_Store`, `.vscode/`, Arduino build folders. Add `.gitattributes` with `* text=auto eol=lf`
   to avoid ghost diffs between Windows and Mac.
6. Python: one `requirements.txt` per module (e.g. `ai/requirements.txt`, `comms/requirements.txt`), not a single one in
   root.
7. Create `CLAUDE.md` with the single line `@PROMPT_GIT_TEAM.md` and `AGENTS.md` with the line
   `Leggi e segui PROMPT_GIT_TEAM.md.` (read and follow PROMPT_GIT_TEAM.md), so the assistants that support them load
   these rules even without the command.
8. Show `git status` and `git diff --staged`, then make a single commit `chore: struttura repo, ownership e contratti`
   (repo structure, ownership and contracts) directly on main (the only exception to the "never on main" rule) and push.
9. Write the user the message to send to the team: "fate git pull, poi iniziate ogni chat con il comando in cima a
   PROMPT_GIT_TEAM.md" (do git pull, then start every chat with the command at the top of PROMPT_GIT_TEAM.md).

## For whoever manages the repo (humans)

1. GitHub → Settings → Collaborators: add the other three.
2. **After** the Setup commit: Settings → Branches → rule on `main` with "Block force pushes" and "Require a pull
   request before merging" (0 approvals, so one can merge alone). Before the Setup it would block its direct commit on
   main.
3. Settings → General → Pull Requests: leave only "Allow squash merging" active and enable "Automatically delete head
   branches".
