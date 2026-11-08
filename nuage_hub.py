"""Connect the private Hub to the signed-in user's Nuage folder."""
import base64
import hmac
import json
import os
import re
import secrets
from datetime import date
from urllib.error import URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from xml.etree import ElementTree

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, abort, flash, g, redirect, render_template, session, url_for

from nuage_pilote import (
    DAV, FILE_ID_HEADERS, FILE_ID_QUERY, NUAGE_LOGIN, NUAGE_STORAGE, OFFICE_TYPES,
    blank_office_document, check_flow_url, nuage_request, office_link,
)

CONNECTION_ERRORS = (ValueError, KeyError, TypeError, AttributeError, OSError, URLError, ElementTree.ParseError)
LABELS = {"texte": "Document texte", "tableur": "Tableur"}


def register_nuage(app, allowed, lineage, view, write):
    nuage = Blueprint("nuage", __name__)
    secret = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
    cipher = Fernet(base64.urlsafe_b64encode(hmac.digest(secret, b"ia-ipr-nuage-v1", "sha256")))
    root = os.environ.get("HUB_NUAGE_ROOT", "IA IPR EPS").strip()

    def seal(values):
        return cipher.encrypt(json.dumps(values).encode()).decode("ascii")

    def unseal(name, ttl):
        try:
            return json.loads(cipher.decrypt(session.get(name, ""), ttl=ttl))
        except (InvalidToken, ValueError, TypeError):
            return None

    def folder_path(node_id, permission=view):
        node = allowed(node_id, view, "folder")
        if permission == write:
            allowed(node_id, write, "folder")
        parts = (root, *(part["name"] for part in lineage(node)[1:]))
        # DAV writes and polling can be slow; release SQLite's request lock first.
        g.db.rollback()
        return node, parts

    def dav(account, path, method, *, payload=None, headers=None, limit=128 * 1024):
        login, password = account
        credential = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
        url = NUAGE_STORAGE + "/remote.php/dav/files/" + "/".join(quote(p, safe="") for p in (login, *path))
        return nuage_request(url, method, payload=payload, limit=limit,
                             headers={"Authorization": f"Basic {credential}", **(headers or {})})

    def listing(account, path):
        status, body = dav(account, path, "PROPFIND", payload=FILE_ID_QUERY,
                           headers={**FILE_ID_HEADERS, "Depth": "1"}, limit=512 * 1024)
        if status != 207:
            return status, {}
        files = {}
        for entry in ElementTree.fromstring(body).findall(f"{DAV}response"):
            name = unquote(entry.findtext(f"{DAV}href", "").rstrip("/").rsplit("/", 1)[-1])
            if name.lower().endswith((".odt", ".ods")):
                files[name] = office_link(entry)
        return status, files

    @nuage.get("/dossier/<int:node_id>/nuage")
    def documents(node_id):
        node, path = folder_path(node_id)
        account = unseal("nuage_account", 3600)
        files = {}
        if account:
            try:
                status, files = listing(account, path)
                if status == 404:
                    flash("Ce dossier Nuage sera créé lors du premier enregistrement si vous avez les droits.")
                elif status != 207:
                    flash(f"Impossible de lire ce dossier dans Nuage ({status}).")
            except CONNECTION_ERRORS:
                flash("La liste Nuage est temporairement indisponible.")
        return render_template("nuage_dossier.html", node=node, path=path, files=sorted(files.items()),
                               connected=bool(account), authorization=unseal("nuage_flow", 900))

    @nuage.post("/dossier/<int:node_id>/nuage/connecter")
    def connect(node_id):
        folder_path(node_id)
        session.pop("nuage_flow", None)
        try:
            status, body = nuage_request(f"{NUAGE_LOGIN}/index.php/login/v2", "POST", payload=b"")
            if status != 200:
                raise ValueError("Autorisation indisponible")
            data = json.loads(body)
            login_url = check_flow_url(data["login"], "flow")
            poll_url = check_flow_url(data["poll"]["endpoint"], "poll")
            token = data["poll"]["token"]
            if not isinstance(token, str) or not 1 <= len(token) <= 512:
                raise ValueError("Suivi invalide")
            session["nuage_flow"] = seal([login_url, poll_url, token])
        except CONNECTION_ERRORS:
            flash("Impossible de démarrer l’autorisation Nuage.")
        return redirect(url_for("nuage.documents", node_id=node_id), code=303)

    @nuage.post("/dossier/<int:node_id>/nuage/confirmer")
    def confirm(node_id):
        folder_path(node_id)
        flow = unseal("nuage_flow", 900)
        if flow:
            try:
                _, url, token = flow
                status, body = nuage_request(url, "POST", payload=urlencode({"token": token}).encode(),
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
                if status == 200:
                    data = json.loads(body)
                    login, password = data["loginName"], data["appPassword"]
                    server = urlsplit(data["server"])
                    if (not isinstance(login, str) or not 1 <= len(login) <= 256 or ":" in login
                            or not isinstance(password, str) or not 1 <= len(password) <= 512
                            or server.scheme != "https" or server.netloc not in {
                                "nuage.apps.education.fr", "nuage01.apps.education.fr"}):
                        raise ValueError("Compte Nuage non reconnu")
                    session["nuage_account"] = seal([login, password])
                    session.pop("nuage_flow", None)
                    flash("Nuage est connecté. Vous pouvez créer un document.")
                    return redirect(url_for("folder", node_id=node_id), code=303)
                flash("Autorisez d’abord l’accès sur la page officielle Nuage.")
            except CONNECTION_ERRORS:
                flash("Impossible de confirmer l’autorisation Nuage.")
        else:
            flash("L’autorisation a expiré. Cliquez sur « Connecter Nuage ».")
        return redirect(url_for("nuage.documents", node_id=node_id), code=303)

    @nuage.post("/dossier/<int:node_id>/nuage/fermer")
    def disconnect(node_id):
        folder_path(node_id)
        for key in ("nuage_account", "nuage_flow", "nuage_pending"):
            session.pop(key, None)
        return redirect(url_for("folder", node_id=node_id), code=303)

    @nuage.post("/dossier/<int:node_id>/nuage/creer/<kind>")
    def create(node_id, kind):
        _, path = folder_path(node_id, write)
        if kind not in OFFICE_TYPES:
            abort(404)
        account = unseal("nuage_account", 3600)
        if not account:
            flash("Connectez Nuage une première fois, puis revenez au bouton de création.")
            return redirect(url_for("nuage.documents", node_id=node_id), code=303)

        ext, mime, data = blank_office_document(kind)
        pending = session.get("nuage_pending")
        name = (pending[2] if pending and pending[:2] == [node_id, kind]
                else f"{LABELS[kind]} {date.today().isoformat()} - {secrets.token_hex(5)}.{ext}")
        session["nuage_pending"] = [node_id, kind, name]
        headers = {"Content-Type": mime, "If-None-Match": "*"}
        status = None
        try:
            status, _ = dav(account, (*path, name), "PUT", payload=data, headers=headers)
            if status in {404, 409} and len(path) > 1:
                # Create descendants only; the shared Nuage root must already exist.
                for depth in range(2, len(path) + 1):
                    status, _ = dav(account, path[:depth], "MKCOL")
                    if status not in {201, 405}:
                        break
                else:
                    status = None
                    status, _ = dav(account, (*path, name), "PUT", payload=data, headers=headers)
        except CONNECTION_ERRORS:
            status = None

        if status is not None and status not in {201, 412} and status < 500:
            session.pop("nuage_pending", None)
            if status in {401, 403}:
                flash("Nuage a refusé la création. Vérifiez le droit de modification du dossier.")
            else:
                flash(f"Nuage n’a pas créé le document ({status}). Vérifiez le dossier partagé « {root} ».")
            return redirect(url_for("nuage.documents", node_id=node_id), code=303)

        try:
            _, files = listing(account, path)
        except CONNECTION_ERRORS:
            files = {}
        if status == 201 or name in files:
            session.pop("nuage_pending", None)
            if files.get(name):
                return redirect(files[name], code=303)
            flash("Document créé. Retrouvez-le dans la liste Nuage.")
        else:
            flash("Création non confirmée. Un nouvel essai reprendra le même fichier.")
        return redirect(url_for("nuage.documents", node_id=node_id), code=303)

    app.register_blueprint(nuage)
