"""Sets the user name and the password of the technician's page (see smartcrossing/status_page.py).

Usage, from ai/ (on the board: ~/venv/bin/python scripts/operator_login.py):
    python scripts/operator_login.py

Asks for a user name and a password and writes them to operator.credentials_file (ai/.env, ignored by git):
the user name in clear, the password only as a salted hash. Readable by the owner only.
Run it again to change them; restart the vision afterwards.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.config import load_config, resolve_path  # noqa: E402
from smartcrossing.status_page import HASH_VAR, USER_VAR, hash_password  # noqa: E402

MIN_PASSWORD_CHARS = 8


def write_credentials(path: Path, user: str, password: str) -> None:
    """Replaces the two lines of the credentials in the file and keeps whatever else is there."""
    kept = []
    if path.is_file():
        kept = [line for line in path.read_text(encoding="utf-8").splitlines()
                if line.partition("=")[0].strip() not in (USER_VAR, HASH_VAR)]
    lines = kept + [f"{USER_VAR}={user}", f"{HASH_VAR}={hash_password(password)}"]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def main() -> int:
    path = Path(resolve_path(load_config()["operator"]["credentials_file"]))
    user = input("Utente del tecnico: ").strip()
    if not user or "=" in user or any(c.isspace() for c in user):
        print("Il nome utente non può essere vuoto né contenere spazi o '='.", file=sys.stderr)
        return 2
    password = getpass.getpass("Password (almeno 8 caratteri, non si vede mentre scrivi): ")
    if len(password) < MIN_PASSWORD_CHARS:
        print("Password troppo corta.", file=sys.stderr)
        return 2
    if getpass.getpass("Ripeti la password: ") != password:
        print("Le due password sono diverse: niente è stato cambiato.", file=sys.stderr)
        return 2
    write_credentials(path, user, password)
    print(f"Salvato in {path} (solo l'impronta della password). Riavvia la visione per usarle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
