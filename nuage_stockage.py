"""Accès du Hub à l'arborescence Nuage avec un compte de service.

Le Hub reprend Nuage tel qu'il est classé : chaque dossier du Hub correspond au
dossier Nuage de même chemin sous la racine (HUB_NUAGE_ROOT). Les fichiers
restent dans Nuage. Le Hub décide seul qui voit, télécharge ou dépose, puis
lit ou écrit dans Nuage avec le compte de service.

Configuration (variables d'environnement du serveur, jamais dans le dépôt) :
  HUB_NUAGE_LOGIN              identifiant renvoyé par « flask nuage-autoriser »
  HUB_NUAGE_APP_PASSWORD_FILE  fichier contenant le mot de passe d'application
  (ou HUB_NUAGE_APP_PASSWORD)  le mot de passe lui-même, si pas de fichier
  HUB_NUAGE_URL                serveur Nuage du compte (par défaut nuage01)
  HUB_NUAGE_ROOT               dossier de départ, sous-dossiers compris,
                               par exemple « Dossiers IPR EPS/IA IPR EPS »
"""
import base64
import json
import os
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, build_opener
from xml.etree import ElementTree

from nuage_pilote import DAV, NUAGE_LOGIN, NUAGE_STORAGE, OC, NoRedirect, check_flow_url, nuage_request

NETWORK_ERRORS = (OSError, URLError, ValueError, ElementTree.ParseError)
LIST_QUERY = (b'<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop>'
              b"<d:resourcetype/><d:getcontentlength/><d:getlastmodified/><oc:fileid/>"
              b"</d:prop></d:propfind>")


class StorageError(RuntimeError):
    """Nuage n'a pas confirmé l'opération."""


def split_root(root):
    return tuple(part.strip() for part in root.split("/") if part.strip())


class NuageStorage:
    def __init__(self, login, password, root, base_url=NUAGE_STORAGE):
        self.login = login
        self.root = split_root(root)
        self.base_url = base_url.rstrip("/")
        credential = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
        self.auth = {"Authorization": f"Basic {credential}"}

    @classmethod
    def from_environment(cls, local_http=False):
        login = os.environ.get("HUB_NUAGE_LOGIN", "").strip()
        password = os.environ.get("HUB_NUAGE_APP_PASSWORD", "")
        password_file = os.environ.get("HUB_NUAGE_APP_PASSWORD_FILE")
        if password_file:
            if password:
                raise RuntimeError("Définissez une seule source pour le mot de passe Nuage.")
            password = Path(password_file).read_text(encoding="utf-8").strip()
        if not login and not password:
            return None
        if not login or not password or ":" in login:
            raise RuntimeError("Renseignez HUB_NUAGE_LOGIN et le mot de passe d’application Nuage.")
        base_url = os.environ.get("HUB_NUAGE_URL", NUAGE_STORAGE)
        if urlsplit(base_url).scheme != "https" and not local_http:
            raise RuntimeError("HUB_NUAGE_URL doit être en HTTPS.")
        return cls(login, password, os.environ.get("HUB_NUAGE_ROOT", "IA IPR EPS"), base_url)

    # Chemins : tuples de noms relatifs à la racine.
    def url(self, path):
        segments = (self.login, *self.root, *path)
        return self.base_url + "/remote.php/dav/files/" + "/".join(quote(p, safe="") for p in segments)

    def _request(self, method, path, *, payload=None, headers=None, limit=64 * 1024):
        try:
            return nuage_request(self.url(path), method, payload=payload, limit=limit,
                                 headers={**self.auth, **(headers or {})})
        except NETWORK_ERRORS as error:
            raise StorageError("Nuage est injoignable pour le moment.") from error

    def listing(self, path):
        """Retourne (sous-dossiers, fichiers) ou None si le dossier n'existe pas dans Nuage."""
        status, body = self._request("PROPFIND", path, payload=LIST_QUERY, limit=8 * 1024 * 1024,
                                     headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
        if status == 404:
            return None
        if status != 207:
            raise StorageError(f"Nuage n’a pas listé ce dossier ({status}).")
        own = urlsplit(self.url(path)).path.rstrip("/")
        folders, files = [], []
        try:
            entries = ElementTree.fromstring(body).findall(f"{DAV}response")
        except ElementTree.ParseError as error:
            raise StorageError("Réponse de Nuage illisible.") from error
        for entry in entries:
            href = urlsplit(entry.findtext(f"{DAV}href", "")).path.rstrip("/")
            if unquote(href) == unquote(own):
                continue
            name = unquote(href.rsplit("/", 1)[-1])
            if not name or name in {".", ".."}:
                continue
            prop = entry.find(f"{DAV}propstat/{DAV}prop")
            if prop is None:
                continue
            if prop.find(f"{DAV}resourcetype/{DAV}collection") is not None:
                folders.append(name)
                continue
            size = prop.findtext(f"{DAV}getcontentlength", "0").strip()
            modified = prop.findtext(f"{DAV}getlastmodified", "").strip()
            try:
                modified = parsedate_to_datetime(modified).strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                modified = ""
            file_id = prop.findtext(f"{OC}fileid", "").strip()
            files.append({
                "name": name,
                "size": int(size) if size.isdigit() else 0,
                "modified": modified,
                "editor": (f"{self.base_url}/index.php/f/{file_id}"
                           if re.fullmatch(r"[1-9][0-9]{0,19}", file_id) else None),
            })
        folders.sort(key=str.casefold)
        files.sort(key=lambda item: item["name"].casefold())
        return folders, files

    def file_info(self, path):
        content = self.listing(path[:-1])
        if content:
            for item in content[1]:
                if item["name"] == path[-1]:
                    return item
        return None

    def make_folders(self, path):
        """Crée les dossiers manquants jusqu'à path (la racine comprise)."""
        full = (*self.root, *path)
        for depth in range(1, len(full) + 1):
            url = self.base_url + "/remote.php/dav/files/" + "/".join(
                quote(p, safe="") for p in (self.login, *full[:depth]))
            try:
                status, _ = nuage_request(url, "MKCOL", headers=self.auth)
            except NETWORK_ERRORS as error:
                raise StorageError("Nuage est injoignable pour le moment.") from error
            if status not in {201, 405}:
                raise StorageError(f"Nuage refuse la création du dossier ({status}).")

    def put(self, path, data):
        headers = {"Content-Type": "application/octet-stream", "If-None-Match": "*"}
        status, _ = self._request("PUT", path, payload=data, headers=headers)
        if status in {404, 409}:
            self.make_folders(path[:-1])
            status, _ = self._request("PUT", path, payload=data, headers=headers)
        if status == 412:
            raise FileExistsError(path[-1])
        if status not in {201, 204}:
            raise StorageError(f"Nuage n’a pas enregistré « {path[-1]} » ({status}).")

    def get(self, path, limit, first_bytes=None):
        headers = {"Range": f"bytes=0-{first_bytes - 1}"} if first_bytes else None
        status, data = self._request("GET", path, headers=headers, limit=limit)
        if status not in {200, 206}:
            raise StorageError(f"Nuage n’a pas fourni le fichier ({status}).")
        return data[:first_bytes] if first_bytes else data

    def open(self, path):
        """Ouvre un téléchargement en flux (pour les gros fichiers)."""
        request = Request(self.url(path), headers=self.auth, method="GET")
        try:
            response = build_opener(NoRedirect()).open(request, timeout=30)
        except HTTPError as error:
            raise StorageError(f"Nuage n’a pas fourni le fichier ({error.code}).") from error
        except NETWORK_ERRORS as error:
            raise StorageError("Nuage est injoignable pour le moment.") from error
        return response

    def move(self, source, destination):
        status, _ = self._request("MOVE", source, headers={"Destination": self.url(destination),
                                                           "Overwrite": "F"})
        return status

    def delete(self, path):
        try:
            return self._request("DELETE", path)[0]
        except StorageError:
            return None


def authorize_service_account(echo, wait=600):
    """Obtient un mot de passe d'application Nuage (flux de connexion v2)."""
    status, body = nuage_request(f"{NUAGE_LOGIN}/index.php/login/v2", "POST", payload=b"",
                                 headers={"User-Agent": "Espace IA-IPR EPS (serveur)"})
    if status != 200:
        raise StorageError("Nuage n’a pas ouvert l’autorisation.")
    data = json.loads(body)
    login_url = check_flow_url(data["login"], "flow")
    poll_url = check_flow_url(data["poll"]["endpoint"], "poll")
    token = data["poll"]["token"]
    echo("1. Ouvrez ce lien en étant connecté au compte Nuage qui contient les dossiers :")
    echo("   " + login_url)
    echo("2. Autorisez l’accès. Cette fenêtre attend la confirmation…")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(5)
        status, body = nuage_request(poll_url, "POST", payload=urlencode({"token": token}).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        if status == 200:
            result = json.loads(body)
            server = urlsplit(result["server"])
            if server.scheme != "https" or not re.fullmatch(r"nuage[0-9]*\.apps\.education\.fr", server.netloc):
                raise StorageError("Serveur Nuage non reconnu.")
            return result["loginName"], result["appPassword"], f"https://{server.netloc}"
    raise StorageError("Autorisation non reçue dans le délai.")


def _settings_file():
    return Path(os.environ.get("HUB_ENV_FILE", Path.home() / ".ia-ipr-eps" / "hub.env"))


def _write_settings(values):
    path = _settings_file()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in lines if line.partition("=")[0].strip() not in values]
    kept += [f"{key}={value}" for key, value in values.items()]
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write("\n".join(kept) + "\n")
    return path


def _load_settings():
    path = _settings_file()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip().startswith("HUB_"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def report(database=None):
    """Compare le Hub et Nuage sans rien modifier."""
    import sqlite3
    _load_settings()
    storage = NuageStorage.from_environment(os.environ.get("HUB_LOCAL_HTTP") == "1")
    if not storage:
        print("Nuage n’est pas branché : lancez « autoriser ».")
        return 1
    database = database or os.environ.get("HUB_DATABASE") or str(Path.home() / ".ia-ipr-eps" / "hub.sqlite3")
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    rows = {r[0]: r for r in db.execute("SELECT id,parent,name,kind FROM nodes")}
    hub_files = {}
    for node_id, parent, name, kind in rows.values():
        if kind == "file":
            hub_files.setdefault(parent, []).append(name)

    def path_of(node_id):
        names = []
        while rows[node_id][1] is not None:
            names.append(rows[node_id][2])
            node_id = rows[node_id][1]
        return tuple(reversed(names))

    listings = {}

    def folders_in(path):
        if path not in listings:
            content = storage.listing(path)
            listings[path] = set(content[0]) if content else None
        return listings[path]

    missing = []
    for node_id, parent, name, kind in sorted(rows.values()):
        if kind != "folder" or parent is None:
            continue
        path = path_of(node_id)
        existing = folders_in(path[:-1])
        if existing is None or name not in existing:
            missing.append(path)
    print(f"Dossiers du Hub absents de Nuage : {len(missing)}")
    for path in missing[:60]:
        print("  •", " / ".join(path))
    total = sum(len(v) for v in hub_files.values())
    print(f"Fichiers enregistrés dans la base du Hub (pas dans Nuage) : {total}")
    for parent, names in sorted(hub_files.items()):
        where = " / ".join(path_of(parent)) or "(accueil)"
        print(f"  • {where} : {', '.join(sorted(names)[:8])}{' …' if len(names) > 8 else ''}")
    return 0


def clean(database=None, ask=input):
    """Aligne le Hub sur Nuage : ajoute les dossiers Nuage manquants, puis retire
    (après confirmation) les dossiers du Hub absents de Nuage et sans fichier du Hub."""
    import sqlite3
    from nuage_miroir import name_key, synchronize
    _load_settings()
    storage = NuageStorage.from_environment(os.environ.get("HUB_LOCAL_HTTP") == "1")
    if not storage:
        print("Nuage n’est pas branché : lancez « autoriser ».")
        return 1
    database = database or os.environ.get("HUB_DATABASE") or str(Path.home() / ".ia-ipr-eps" / "hub.sqlite3")
    db = sqlite3.connect(database, timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    print("1. Ajout des dossiers présents dans Nuage…")
    created, skipped = synchronize(db, storage, 1, print)
    print(f"   {created} dossier(s) ajouté(s).")

    rows = {r[0]: r for r in db.execute("SELECT id,parent,name,kind FROM nodes")}
    children = {}
    for node_id, parent, _, _ in rows.values():
        children.setdefault(parent, []).append(node_id)

    def path_of(node_id):
        names = []
        while rows[node_id][1] is not None:
            names.append(rows[node_id][2])
            node_id = rows[node_id][1]
        return tuple(reversed(names))

    def subtree(node_id):
        found, pending = [], [node_id]
        while pending:
            current = pending.pop()
            found.append(current)
            pending.extend(children.get(current, []))
        return found

    print("2. Recherche des dossiers du Hub absents de Nuage…")
    listings, orphans = {}, []
    for node_id, parent, name, kind in sorted(rows.values()):
        if kind != "folder" or parent is None:
            continue
        path = path_of(node_id)
        if any(orphan == path[:len(orphan)] for orphan in map(path_of, orphans)):
            continue
        if path[:-1] not in listings:
            content = storage.listing(path[:-1])
            listings[path[:-1]] = {name_key(item) for item in content[0]} if content else set()
        if name_key(name) not in listings[path[:-1]]:
            orphans.append(node_id)
    removable, kept = [], []
    for node_id in orphans:
        nodes = subtree(node_id)
        (kept if any(rows[n][3] == "file" for n in nodes) else removable).append((node_id, nodes))
    for node_id, nodes in kept:
        print(f"   Conservé (contient des fichiers du Hub) : {' / '.join(path_of(node_id))}")
    if not removable:
        print("   Aucun dossier à traiter. Le Hub est aligné sur Nuage.")
        return 0
    print(f"   {len(removable)} dossier(s) du Hub absents de Nuage (souvent des dossiers vides,")
    print("   que Nuage ignore lors d’un envoi par le navigateur) :")
    for number, (node_id, nodes) in enumerate(removable, 1):
        extra = f" (+ {len(nodes) - 1} sous-dossier(s))" if len(nodes) > 1 else ""
        print(f"   {number:>3}. {' / '.join(path_of(node_id))}{extra}")
    print()
    print("Que faire de ces dossiers ?")
    print("   creer   : les créer dans Nuage (ils restent dans le Hub)")
    print("   retirer : les retirer du Hub (rien n’est supprimé dans Nuage)")
    print("   Entrée  : ne rien faire")
    action = ask("Action pour tous : ").strip().lower()
    if action not in {"creer", "créer", "retirer"}:
        print("Rien n’a été modifié.")
        return 0
    action = "retirer" if action == "retirer" else "creer"
    other = "retirer" if action == "creer" else "creer"
    answer = ask(f"Numéros à {other} plutôt (séparés par des espaces, Entrée si aucun) : ")
    exceptions = {int(item) for item in re.findall(r"\d+", answer) if 1 <= int(item) <= len(removable)}
    to_create, to_remove = [], []
    for number, entry in enumerate(removable, 1):
        ((to_remove if action == "creer" else to_create) if number in exceptions
         else (to_create if action == "creer" else to_remove)).append(entry)
    print(f"Résumé : {len(to_create)} à créer dans Nuage, {len(to_remove)} à retirer du Hub.")
    if ask("Confirmer ? Tapez oui : ").strip().lower() != "oui":
        print("Rien n’a été modifié.")
        return 0
    created_folders = 0
    for _, nodes in to_create:
        for node_id in sorted(nodes, key=lambda n: len(path_of(n))):
            if rows[node_id][3] == "folder":
                storage.make_folders(path_of(node_id))
                created_folders += 1
    with db:
        for _, nodes in to_remove:
            for node_id in sorted(nodes, key=lambda n: -len(path_of(n))):
                db.execute("UPDATE node_id_watermark SET last_deleted_id=MAX(last_deleted_id, ?) WHERE singleton=1",
                           (node_id,))
                db.execute("DELETE FROM rules WHERE node=?", (node_id,))
                db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
    print(f"Terminé : {created_folders} dossier(s) créé(s) dans Nuage, {len(to_remove)} retiré(s) du Hub.")
    return 0


def main(argv):
    """python nuage_stockage.py autoriser | verifier  (sur le serveur, en SSH)."""
    action = argv[1] if len(argv) > 1 else ""
    if action == "autoriser":
        login, password, server = authorize_service_account(print)
        folder = _settings_file().parent
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        secret = folder / "nuage_password"
        descriptor = os.open(secret, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(password + "\n")
        print()
        print("Quel dossier Nuage contient vos dossiers principaux (CMI, Formateurs…) ?")
        root = input("Chemin depuis la racine de Nuage [Dossiers IPR EPS] : ").strip() or "Dossiers IPR EPS"
        path = _write_settings({"HUB_NUAGE_LOGIN": login, "HUB_NUAGE_URL": server,
                                "HUB_NUAGE_APP_PASSWORD_FILE": str(secret), "HUB_NUAGE_ROOT": root})
        print(f"Réglages enregistrés dans {path}")
        action = "verifier"
    if action == "verifier":
        _load_settings()
        storage = NuageStorage.from_environment(os.environ.get("HUB_LOCAL_HTTP") == "1")
        if not storage:
            print("Nuage n’est pas branché : lancez « autoriser ».")
            return 1
        content = storage.listing(())
        if content is None:
            print(f"Dossier de départ introuvable : « {'/'.join(storage.root)} ».")
            print(f"Corrigez HUB_NUAGE_ROOT dans {_settings_file()} puis relancez « verifier ».")
            return 1
        print(f"Nuage lu dans « {'/'.join(storage.root)} » : {len(content[0])} dossier(s), "
              f"{len(content[1])} fichier(s).")
        for name in content[0][:20]:
            print("  •", name)
        return 0
    if action == "etat":
        return report(argv[2] if len(argv) > 2 else None)
    if action == "nettoyer":
        return clean(argv[2] if len(argv) > 2 else None)
    print("Usage : python nuage_stockage.py autoriser | verifier | etat | nettoyer")
    return 1


if __name__ == "__main__":
    import sys
    try:
        sys.exit(main(sys.argv))
    except (StorageError, RuntimeError, OSError, ValueError, KeyError) as error:
        sys.exit(f"Erreur : {error}")
