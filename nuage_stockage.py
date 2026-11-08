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
