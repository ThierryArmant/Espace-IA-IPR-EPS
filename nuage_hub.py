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
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from nuage_pilote import (
    DAV, FILE_ID_HEADERS, FILE_ID_QUERY, NUAGE_LOGIN, NUAGE_STORAGE, OFFICE_TYPES,
    blank_office_document, check_flow_url, nuage_request, office_link,
)

CONNECTION_ERRORS = (ValueError, KeyError, TypeError, AttributeError, OSError, URLError, ElementTree.ParseError)
LABELS = {"texte": "Document texte", "tableur": "Tableur"}
AUTHORIZATION_LIFETIME = 900
ACCOUNT_LIFETIME = 8 * 3600
OFFICE_LIST_QUERY = FILE_ID_QUERY.replace(b"<oc:fileid/>", b"<oc:fileid/><d:resourcetype/>")


def register_nuage(app, allowed, lineage, rights, view, write):
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

    def dav_url(login, path):
        return NUAGE_STORAGE + "/remote.php/dav/files/" + "/".join(quote(p, safe="") for p in (login, *path))

    def dav(account, path, method, *, payload=None, headers=None, limit=128 * 1024):
        login, password = account
        credential = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
        return nuage_request(dav_url(login, path), method, payload=payload, limit=limit,
                             headers={"Authorization": f"Basic {credential}", **(headers or {})})

    def listing(account, path):
        status, body = dav(account, path, "PROPFIND", payload=OFFICE_LIST_QUERY,
                           headers={**FILE_ID_HEADERS, "Depth": "1"}, limit=512 * 1024)
        if status != 207:
            return status, {}
        files = {}
        for entry in ElementTree.fromstring(body).findall(f"{DAV}response"):
            href = entry.findtext(f"{DAV}href", "")
            name = unquote(href.rsplit("/", 1)[-1])
            collection = entry.find(f"{DAV}propstat/{DAV}prop/{DAV}resourcetype/{DAV}collection")
            if collection is None and name.lower().endswith((".odt", ".ods")) and "/" not in name:
                files[name] = office_link(entry)
        return status, files

    def read_folder(account, path):
        if account:
            try:
                status, files = listing(account, path)
                if status in {207, 404}:
                    return sorted(files.items(), key=lambda item: item[0].casefold()), None
                return [], f"Impossible de lire ce dossier dans Nuage ({status})."
            except CONNECTION_ERRORS:
                return [], "La liste Nuage est temporairement indisponible."
        return [], None

    def ensure_descendants(account, path):
        # The shared root must already exist.
        for depth in range(2, len(path) + 1):
            status, _ = dav(account, path[:depth], "MKCOL")
            if status not in {201, 405}:
                return status
        return None

    def folder_documents(node_id):
        account = unseal("nuage_account", ACCOUNT_LIFETIME)
        if not account:
            return False, [], None
        _, path = folder_path(node_id)
        files, error = read_folder(account, path)
        return True, files, error

    def requested_kind(node_id):
        intent = session.get("nuage_creation")
        if intent and intent[0] == node_id:
            return intent[1]
        return None

    @nuage.get("/dossier/<int:node_id>/nuage")
    def documents(node_id):
        node, path = folder_path(node_id)
        account = unseal("nuage_account", ACCOUNT_LIFETIME)
        files, error = read_folder(account, path)
        if error:
            flash(error)
        return render_template("nuage_dossier.html", node=node, path=path, files=files,
                               connected=bool(account), authorization=unseal("nuage_flow", AUTHORIZATION_LIFETIME),
                               creation_kind=requested_kind(node_id))

    @nuage.route("/dossier/<int:node_id>/nuage/deplacer", methods=["GET", "POST"])
    def move(node_id):
        node, path = folder_path(node_id, write)
        account = unseal("nuage_account", ACCOUNT_LIFETIME)
        if not account:
            return redirect(url_for("nuage.documents", node_id=node_id), code=303)
        name = (request.form if request.method == "POST" else request.args).get("name", "")
        if (not name.lower().endswith((".odt", ".ods")) or "/" in name or "\\" in name
                or any(ord(char) < 32 for char in name)):
            abort(400)
        if request.method != "POST":
            destinations = sorted(
                ((" › ".join(part["name"] for part in lineage(item)), item["id"])
                 for item in g.nodes.values()
                 if item["kind"] == "folder" and item["id"] != node_id
                 and rights(item) & view and rights(item) & write),
                key=lambda item: item[0].casefold(),
            )
            return render_template("nuage_deplacer.html", node=node, name=name, destinations=destinations)

        destination_id = request.form.get("destination", type=int)
        if destination_id is None or destination_id == node_id:
            abort(400)
        _, destination = folder_path(destination_id, write)
        headers = {"Destination": dav_url(account[0], (*destination, name)), "Overwrite": "F"}
        try:
            status, files = listing(account, path)
            if status == 207 and name in files:
                status, _ = dav(account, (*path, name), "MOVE", headers=headers)
                if status == 409:
                    status = ensure_descendants(account, destination)
                    if status is None:
                        status, _ = dav(account, (*path, name), "MOVE", headers=headers)
        except CONNECTION_ERRORS:
            status = None
        if status in {201, 204}:
            flash(f"« {name} » a été déplacé dans ce dossier.")
            return redirect(url_for("folder", node_id=destination_id), code=303)
        if status == 412:
            flash("Un document porte déjà ce nom dans le dossier de destination.")
        elif status in {401, 403}:
            flash("Nuage a refusé le déplacement. Vérifiez les droits des deux dossiers.")
        else:
            flash("Déplacement non confirmé. Vérifiez les deux dossiers avant de réessayer.")
        return redirect(url_for("folder", node_id=node_id), code=303)

    def begin_authorization():
        session.pop("nuage_flow", None)
        try:
            status, body = nuage_request(
                f"{NUAGE_LOGIN}/index.php/login/v2", "POST", payload=b"",
                headers={"User-Agent": "IA-IPR EPS"},
            )
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

    @nuage.post("/dossier/<int:node_id>/nuage/connecter")
    def connect(node_id):
        folder_path(node_id)
        begin_authorization()
        return redirect(url_for("nuage.documents", node_id=node_id), code=303)

    @nuage.post("/dossier/<int:node_id>/nuage/confirmer")
    def confirm(node_id):
        kind = requested_kind(node_id)
        _, path = folder_path(node_id, write if kind else view)
        flow = unseal("nuage_flow", AUTHORIZATION_LIFETIME)
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
                else:
                    flash("Autorisez d’abord l’accès sur la page officielle Nuage.")
            except CONNECTION_ERRORS:
                flash("Impossible de confirmer l’autorisation Nuage.")
            else:
                if status == 200:
                    if kind:
                        session.pop("nuage_creation", None)
                        return create_document(node_id, kind, path, [login, password])
                    flash("Nuage est connecté. Vous pouvez créer un document.")
                    return redirect(url_for("folder", node_id=node_id), code=303)
        else:
            flash("L’autorisation a expiré. Cliquez sur « Connecter Nuage ».")
        return redirect(url_for("nuage.documents", node_id=node_id), code=303)

    @nuage.post("/dossier/<int:node_id>/nuage/fermer")
    def disconnect(node_id):
        folder_path(node_id)
        for key in ("nuage_account", "nuage_flow", "nuage_pending", "nuage_creation"):
            session.pop(key, None)
        return redirect(url_for("folder", node_id=node_id), code=303)

    @nuage.post("/dossier/<int:node_id>/nuage/creer/<kind>")
    def create(node_id, kind):
        _, path = folder_path(node_id, write)
        if kind not in OFFICE_TYPES:
            abort(404)
        account = unseal("nuage_account", ACCOUNT_LIFETIME)
        if not account:
            session["nuage_creation"] = [node_id, kind]
            if not unseal("nuage_flow", AUTHORIZATION_LIFETIME):
                begin_authorization()
            return creation_response(node_id, endpoint="nuage.documents")
        if requested_kind(node_id):
            session.pop("nuage_creation", None)
        return create_document(node_id, kind, path, account)

    def creation_response(node_id, editor=None, *, endpoint="folder"):
        destination = url_for(endpoint, node_id=node_id)
        if request.accept_mimetypes.best == "application/json":
            return {"editor": editor, "folder": destination}
        return redirect(destination, code=303)

    def create_document(node_id, kind, path, account):
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
                status = ensure_descendants(account, path)
                if status is None:
                    status, _ = dav(account, (*path, name), "PUT", payload=data, headers=headers)
        except CONNECTION_ERRORS:
            status = None

        if status is not None and status not in {201, 412} and status < 500:
            session.pop("nuage_pending", None)
            if status in {401, 403}:
                flash("Nuage a refusé la création. Vérifiez le droit de modification du dossier.")
            else:
                flash(f"Nuage n’a pas créé le document ({status}). Vérifiez le dossier partagé « {root} ».")
            return creation_response(node_id)

        try:
            _, files = listing(account, path)
        except CONNECTION_ERRORS:
            files = {}
        if status == 201 or name in files:
            session.pop("nuage_pending", None)
            flash("Document créé dans ce dossier.")
            return creation_response(node_id, files.get(name))
        else:
            flash("Création non confirmée. Un nouvel essai reprendra le même fichier.")
        return creation_response(node_id)

    app.register_blueprint(nuage)
    return folder_documents
