"""Stockage des fichiers du Hub dans Nuage avec un compte fonctionnel.

Le Hub reste seul juge des droits : il conserve l'arborescence, les noms et les
règles dans SQLite, et ne place dans Nuage que le contenu des fichiers. Chaque
fichier est rangé dans « <racine>/Stockage Hub » sous un nom unique (jeton +
nom d'origine), ce qui rend le stockage insensible aux renommages et
déplacements de dossiers dans le Hub.

Configuration (variables d'environnement du serveur, jamais dans le dépôt) :
  HUB_NUAGE_LOGIN              identifiant renvoyé par « flask nuage-autoriser »
  HUB_NUAGE_APP_PASSWORD_FILE  fichier contenant le mot de passe d'application
  (ou HUB_NUAGE_APP_PASSWORD)  le mot de passe lui-même, si pas de fichier
  HUB_NUAGE_ROOT               dossier racine dans Nuage (défaut « IA IPR EPS »)
"""
import base64
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlsplit

from nuage_pilote import NUAGE_LOGIN, NUAGE_STORAGE, check_flow_url, nuage_request

STORAGE_FOLDER = "Stockage Hub"
NETWORK_ERRORS = (OSError, URLError, ValueError)


class StorageError(RuntimeError):
    """Nuage n'a pas confirmé l'opération."""


class NuageStorage:
    def __init__(self, login, password, root, base_url=NUAGE_STORAGE):
        self.login, self.password = login, password
        self.path = (*(part.strip() for part in root.split("/") if part.strip()), STORAGE_FOLDER)
        self.base_url = base_url.rstrip("/")
        credential = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
        self.auth = {"Authorization": f"Basic {credential}"}
        self.ready = False

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
        root = os.environ.get("HUB_NUAGE_ROOT", "IA IPR EPS").strip()
        return cls(login, password, root, base_url)

    def _url(self, *parts):
        segments = (self.login, *self.path, *parts)
        return self.base_url + "/remote.php/dav/files/" + "/".join(quote(p, safe="") for p in segments)

    def _request(self, method, *parts, payload=None, headers=None, limit=64 * 1024):
        try:
            return nuage_request(self._url(*parts), method, payload=payload, limit=limit,
                                 headers={**self.auth, **(headers or {})})
        except NETWORK_ERRORS as error:
            raise StorageError("Nuage est injoignable pour le moment.") from error

    def _prepare(self):
        if self.ready:
            return
        for depth in range(1, len(self.path) + 1):
            folder = self.base_url + "/remote.php/dav/files/" + "/".join(
                quote(p, safe="") for p in (self.login, *self.path[:depth]))
            try:
                status, _ = nuage_request(folder, "MKCOL", headers=self.auth)
            except NETWORK_ERRORS as error:
                raise StorageError("Nuage est injoignable pour le moment.") from error
            if status not in {201, 405}:
                raise StorageError(f"Nuage refuse l’accès au dossier de stockage ({status}).")
        self.ready = True

    @staticmethod
    def new_reference(name):
        return f"{secrets.token_hex(8)}-{name}"

    def put(self, reference, data):
        self._prepare()
        status, _ = self._request("PUT", reference, payload=data,
                                  headers={"Content-Type": "application/octet-stream",
                                           "If-None-Match": "*"})
        if status not in {201, 204}:
            raise StorageError(f"Nuage n’a pas enregistré le fichier ({status}).")

    def get(self, reference, limit, first_bytes=None):
        headers = {"Range": f"bytes=0-{first_bytes - 1}"} if first_bytes else None
        status, data = self._request("GET", reference, headers=headers, limit=limit)
        if status not in {200, 206}:
            raise StorageError(f"Nuage n’a pas fourni le fichier ({status}).")
        return data[:first_bytes] if first_bytes else data

    def delete(self, reference):
        try:
            self._request("DELETE", reference)
        except StorageError:
            pass

    def check(self):
        self.ready = False
        self._prepare()


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
    echo("1. Ouvrez ce lien en étant connecté au compte Nuage qui stockera les fichiers :")
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
