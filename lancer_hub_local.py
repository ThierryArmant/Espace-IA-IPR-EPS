"""Lance le Hub complet sur ce PC pour l'essayer : http://127.0.0.1:8080

Usage réservé à l'essai : le Hub n'est joignable que depuis ce PC.
Les données locales (base, clé, accès Nuage) sont dans « donnees-hub-local ».
"""
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "donnees-hub-local"
KEY = DATA / "cle_session.txt"
DATABASE = DATA / "hub.sqlite3"
NUAGE_LOGIN = DATA / "nuage_identifiant.txt"
NUAGE_PASSWORD = DATA / "nuage_mot_de_passe.txt"
NUAGE_SERVER = DATA / "nuage_serveur.txt"
NUAGE_ROOT = DATA / "nuage_dossier_depart.txt"


def write_private(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(value + "\n")


def has_animateur():
    if not DATABASE.exists():
        return False
    try:
        with sqlite3.connect(DATABASE) as db:
            return bool(db.execute("SELECT 1 FROM users WHERE admin=1").fetchone())
    except sqlite3.Error:
        return False


def connect_nuage():
    from nuage_stockage import StorageError, authorize_service_account
    print()
    print("=== Branchement de Nuage ===")
    print("Pour l'essai, votre propre compte Nuage convient.")
    print("Le Hub affichera les dossiers de ce compte et y rangera les dépôts.")
    try:
        login, password, server = authorize_service_account(print)
    except (StorageError, OSError, ValueError, KeyError) as error:
        print(f"Nuage n'a pas été branché : {error}")
        print("Le Hub démarre quand même, avec les fichiers stockés sur ce PC.")
        return
    write_private(NUAGE_LOGIN, login)
    write_private(NUAGE_PASSWORD, password)
    write_private(NUAGE_SERVER, server)
    print()
    print("Quel est le dossier Nuage qui contient vos dossiers principaux (CMI, Formateurs…) ?")
    print("Écrivez son chemin depuis la racine de Nuage, avec / entre les niveaux.")
    root = input("Dossier de départ [Dossiers IPR EPS] : ").strip() or "Dossiers IPR EPS"
    write_private(NUAGE_ROOT, root)
    print("Nuage est branché. Pour changer de dossier de départ, modifiez le fichier")
    print(f"  {NUAGE_ROOT}")


def main():
    DATA.mkdir(mode=0o700, exist_ok=True)
    if not KEY.exists():
        write_private(KEY, secrets.token_hex(32))
    os.environ.update(HUB_LOCAL_HTTP="1", HUB_SECRET_KEY_FILE=str(KEY), HUB_DATABASE=str(DATABASE))
    os.environ.pop("HUB_SECRET_KEY", None)

    if not NUAGE_LOGIN.exists():
        answer = input("Brancher le stockage Nuage maintenant ? (O/N) ").strip().lower()
        if answer.startswith("o"):
            connect_nuage()
    if NUAGE_LOGIN.exists():
        os.environ.update(
            HUB_NUAGE_LOGIN=NUAGE_LOGIN.read_text(encoding="utf-8").strip(),
            HUB_NUAGE_APP_PASSWORD_FILE=str(NUAGE_PASSWORD),
            HUB_NUAGE_URL=NUAGE_SERVER.read_text(encoding="utf-8").strip(),
            HUB_NUAGE_ROOT=(NUAGE_ROOT.read_text(encoding="utf-8").strip()
                            if NUAGE_ROOT.exists() else "Dossiers IPR EPS"),
        )

    if not has_animateur():
        print()
        print("=== Création du compte Animateur ===")
        email = input("Votre adresse mail (identifiant du Hub) : ").strip()
        print("Choisissez un mot de passe d'au moins 14 caractères (il ne s'affiche pas).")
        done = subprocess.run([sys.executable, "-m", "flask", "--app", "app", "init-db", "--email", email],
                              cwd=HERE)
        if done.returncode != 0:
            sys.exit("Compte non créé. Relancez le lanceur.")

    sys.path.insert(0, str(HERE))
    from app import create_app
    app = create_app()
    if NUAGE_LOGIN.exists():
        runner = app.test_cli_runner()
        result = runner.invoke(args=["nuage-verifier"])
        print(result.output.strip() or "Vérification Nuage terminée.")
        if result.exit_code == 0:
            print("Reprise des dossiers Nuage dans le Hub…")
            print(runner.invoke(args=["nuage-synchroniser"]).output.strip())

    from waitress import create_server
    server = create_server(app, host="127.0.0.1", port=8080, threads=4,
                           max_request_body_size=34603008)
    print()
    print("Hub lancé : http://127.0.0.1:8080  (fermez cette fenêtre pour l'arrêter)")
    threading.Timer(1.5, webbrowser.open, ["http://127.0.0.1:8080/connexion"]).start()
    server.run()


if __name__ == "__main__":
    main()
