"""Essai local du dépôt IA-IPR EPS. Ne pas publier ce serveur sur Internet."""
import base64
import io
import json
import os
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree
from zipfile import ZIP_STORED, ZipFile

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

NUAGE_LOGIN = "https://nuage.apps.education.fr"
NUAGE_STORAGE = "https://nuage01.apps.education.fr"
TEST_PATH = "/IA%20IPR%20EPS/Pilote%20Hub/"
PDF_LIMIT = 10 * 1024 * 1024
TEST_NAME = re.compile(r"hub-test-[0-9a-f]{24}\.pdf")
DAV = "{DAV:}"
OC = "{http://owncloud.org/ns}"
OFFICE_TYPES = {
    "texte": ("odt", "text", "<text:p/>"),
    "tableur": ("ods", "spreadsheet", '<table:table table:name="Feuille1">'
                "<table:table-row><table:table-cell/></table:table-row></table:table>"),
}
OFFICE_NAME = re.compile(r"hub-test-[0-9a-f]{24}\.(?:odt|ods)")
FILE_ID_QUERY = (b'<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
                 b"<d:prop><oc:fileid/></d:prop></d:propfind>")
FILE_ID_HEADERS = {"Content-Type": "application/xml; charset=utf-8"}


def blank_office_document(kind):
    extension, body, content = OFFICE_TYPES[kind]
    mime = f"application/vnd.oasis.opendocument.{body}"
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", mime, compress_type=ZIP_STORED)
        archive.writestr("content.xml",
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
            ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
            ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" office:version="1.2">'
            f"<office:body><office:{body}>{content}</office:{body}></office:body>"
            "</office:document-content>")
        archive.writestr("META-INF/manifest.xml",
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"'
            ' manifest:version="1.2">'
            f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            "</manifest:manifest>")
    return extension, mime, output.getvalue()


def office_link(response):
    file_id = response.findtext(f"{DAV}propstat/{DAV}prop/{OC}fileid", "")
    if re.fullmatch(r"[1-9][0-9]{0,19}", file_id):
        return f"{NUAGE_STORAGE}/index.php/f/{file_id}"
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def nuage_request(url, method, *, payload=None, headers=None, limit=128 * 1024):
    outgoing = Request(url, data=payload, headers=headers or {}, method=method)
    try:
        with build_opener(NoRedirect()).open(outgoing, timeout=12) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("La réponse de Nuage dépasse la limite du pilote.")
            return response.status, data
    except HTTPError as error:
        return error.code, b""


def check_flow_url(value, operation):
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.netloc not in {
            "nuage.apps.education.fr", "nuage01.apps.education.fr"}
            or parts.query or parts.fragment):
        raise ValueError("L’adresse renvoyée par Nuage n’est pas reconnue.")
    path = parts.path.removeprefix("/index.php")
    if operation == "flow":
        valid = bool(re.fullmatch(r"/login/v2/flow/[A-Za-z0-9_-]+", path))
    else:
        valid = path == "/login/v2/poll"
    if not valid:
        raise ValueError("L’adresse renvoyée par Nuage n’est pas reconnue.")
    return value


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secrets.token_bytes(32),
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
        SESSION_COOKIE_NAME="ipr_nuage_pilote",
        SESSION_COOKIE_SAMESITE="Strict",
        MAX_CONTENT_LENGTH=PDF_LIMIT + 256 * 1024,
    )
    # Un seul pilote local. Les secrets disparaissent quand il est arrêté.
    accounts = {}
    pending = {}

    @app.before_request
    def local_session():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            abort(403)
        if request.method == "POST":
            csrf = session.get("csrf")
            submitted = request.form.get("csrf", "")
            if not csrf or not secrets.compare_digest(csrf, submitted):
                abort(400, "Formulaire expiré. Rechargez la page.")
        elif "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def key():
        return session["csrf"]

    def dav(method, suffix="", payload=None, headers=None, limit=128 * 1024):
        login, password = accounts[key()]
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode("ascii")
        url = f"{NUAGE_STORAGE}/remote.php/dav/files/{quote(login, safe='')}{TEST_PATH}{suffix}"
        return nuage_request(url, method, payload=payload, limit=limit, headers={
            "Authorization": f"Basic {credentials}", **(headers or {}),
        })

    @app.get("/")
    def home():
        connected = key() in accounts
        files = []
        office_files = {}
        if connected:
            try:
                status, data = dav("PROPFIND", payload=FILE_ID_QUERY,
                                   headers={**FILE_ID_HEADERS, "Depth": "1"}, limit=512 * 1024)
                if status == 207:
                    root = ElementTree.fromstring(data)
                    for node in root.findall(f"{DAV}response"):
                        name = unquote(node.findtext(f"{DAV}href", "").rsplit("/", 1)[-1])
                        if TEST_NAME.fullmatch(name):
                            files.append(name)
                        elif OFFICE_NAME.fullmatch(name):
                            office_files[name] = office_link(node)
                elif status == 404:
                    flash("Le sous-dossier « Pilote Hub » sera créé au premier essai.")
                else:
                    flash(f"La liste des documents de test n’est pas disponible (Nuage {status}).")
            except (ValueError, ElementTree.ParseError, URLError, OSError):
                flash("Impossible de lire la liste dans Nuage.")
        flow = pending.get(key())
        return render_template("nuage_pilote.html", connected=connected, files=sorted(set(files)),
                               office_files=sorted(office_files.items()),
                               authorization_url=flow[0] if flow else None, csrf=key())

    @app.post("/connecter")
    def connect():
        if key() in accounts:
            return redirect(url_for("home"))
        pending.pop(key(), None)
        try:
            status, body = nuage_request(f"{NUAGE_LOGIN}/index.php/login/v2", "POST", payload=b"")
            if status != 200:
                raise ValueError(f"Nuage n’a pas démarré la connexion ({status}).")
            data = json.loads(body)
            authorization_url = check_flow_url(data["login"], "flow")
            poll_url = check_flow_url(data["poll"]["endpoint"], "poll")
            token = data["poll"]["token"]
            if not isinstance(token, str) or not token:
                raise ValueError("Nuage n’a pas fourni de code de suivi.")
            pending[key()] = (authorization_url, poll_url, token, time.monotonic() + 1200)
        except (KeyError, TypeError, AttributeError, ValueError, URLError, OSError):
            flash("Impossible de démarrer l’autorisation Nuage.")
        return redirect(url_for("home"))

    @app.post("/verifier")
    def verify():
        flow = pending.get(key())
        if not flow or flow[3] <= time.monotonic():
            pending.pop(key(), None)
            flash("Autorisation expirée. Relancez la connexion à Nuage.")
            return redirect(url_for("home"))
        try:
            _, url, token, _ = flow
            status, body = nuage_request(url, "POST", payload=urlencode({"token": token}).encode(),
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            if status == 404:
                flash("Autorisez d’abord le pilote dans l’onglet Nuage, puis revenez ici.")
            elif status == 200:
                data = json.loads(body)
                login, password = data["loginName"], data["appPassword"]
                server = urlsplit(data["server"])
                if (not isinstance(login, str) or not login or ":" in login
                        or not isinstance(password, str) or not password
                        or server.scheme != "https" or server.netloc not in {
                            "nuage.apps.education.fr", "nuage01.apps.education.fr"}):
                    raise ValueError("Identifiants d’application non reconnus.")
                accounts[key()] = (login, password)
                pending.pop(key(), None)
                flash("Compte Nuage connecté. Vous pouvez créer un document de test.")
            else:
                flash(f"Autorisation non confirmée par Nuage ({status}).")
        except (KeyError, TypeError, AttributeError, ValueError, URLError, OSError):
            flash("Impossible de vérifier l’autorisation Nuage.")
        return redirect(url_for("home"))

    @app.post("/deposer")
    def upload():
        if key() not in accounts:
            abort(403)
        file = request.files.get("file")
        data = file.read(PDF_LIMIT + 1) if file else b""
        if len(data) > PDF_LIMIT or not data.startswith(b"%PDF-"):
            flash("Choisissez un PDF de test de 10 Mio maximum.")
            return redirect(url_for("home"))
        try:
            status, _ = dav("MKCOL")
            if status not in {201, 405}:
                flash(f"Le dossier de test n’a pas pu être créé (Nuage {status}).")
                return redirect(url_for("home"))
            name = f"hub-test-{secrets.token_hex(12)}.pdf"
            status, _ = dav("PUT", name, payload=data, headers={
                "Content-Type": "application/pdf", "If-None-Match": "*",
            })
            if status == 201:
                flash("PDF de test enregistré dans Nuage. Vous pouvez le télécharger ci-dessous.")
            else:
                flash(f"Nuage n’a pas confirmé le dépôt ({status}).")
        except (ValueError, URLError, OSError):
            flash("La réponse de Nuage est indisponible. Vérifiez la liste avant de réessayer.")
        return redirect(url_for("home"))

    @app.post("/creer/<kind>")
    def create_office(kind):
        if key() not in accounts:
            abort(403)
        if kind not in OFFICE_TYPES:
            abort(404)
        extension, mime, data = blank_office_document(kind)
        name = f"hub-test-{secrets.token_hex(12)}.{extension}"
        try:
            status, _ = dav("MKCOL")
            if status not in {201, 405}:
                flash(f"Le dossier de test n’a pas pu être créé (Nuage {status}).")
                return redirect(url_for("home"))
            status, _ = dav("PUT", name, payload=data, headers={
                "Content-Type": mime, "If-None-Match": "*",
            })
            if status != 201:
                flash(f"Nuage n’a pas confirmé la création ({status}).")
                return redirect(url_for("home"))
            status, xml = dav("PROPFIND", name, payload=FILE_ID_QUERY,
                              headers={**FILE_ID_HEADERS, "Depth": "0"})
            if status == 207:
                item = ElementTree.fromstring(xml).find(f"{DAV}response")
                link = office_link(item) if item is not None else None
                if link:
                    return redirect(link, code=303)
            flash("Document créé dans Nuage. Vous pouvez le retrouver dans « Pilote Hub ».")
        except (ValueError, ElementTree.ParseError, URLError, OSError):
            flash("La réponse de Nuage est indisponible. Vérifiez « Pilote Hub » avant de réessayer.")
        return redirect(url_for("home"))

    @app.get("/fichier/<name>")
    def download(name):
        if key() not in accounts or not TEST_NAME.fullmatch(name):
            abort(404)
        try:
            status, data = dav("GET", name, limit=PDF_LIMIT)
            if status != 200 or not data.startswith(b"%PDF-"):
                abort(404)
        except (ValueError, URLError, OSError):
            abort(404)
        return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                         download_name=name, conditional=False)

    @app.post("/fermer")
    def disconnect():
        accounts.pop(key(), None)
        pending.pop(key(), None)
        session.clear()
        flash("Session locale fermée.")
        return redirect(url_for("home"))

    return app


if __name__ == "__main__":
    import threading
    import webbrowser

    from waitress import create_server

    server = create_server(create_app(), host="127.0.0.1", port=8088, threads=1,
                           max_request_body_size=PDF_LIMIT + 256 * 1024)
    if os.environ.get("HUB_PILOTE_OUVRIR") == "1":
        threading.Timer(0.5, webbrowser.open, args=("http://127.0.0.1:8088/",)).start()
    print("Pilote IA-IPR EPS : http://127.0.0.1:8088/", flush=True)
    server.run()
