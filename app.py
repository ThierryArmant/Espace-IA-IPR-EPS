import hashlib
import io
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import time
import zlib
from collections import defaultdict
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import click
from flask import (
    Flask, abort, flash, g, redirect, render_template, request, send_file,
    session, url_for,
)
from werkzeug.exceptions import SecurityError
from werkzeug.security import check_password_hash, generate_password_hash

from ipr_modules import group_id as ipr_group_id, register_ipr_modules
from login_code import CodeMailer, login_with_code, start_session
from nuage_hub import register_nuage

VIEW, DOWNLOAD, WRITE = 1, 2, 4
ALL = VIEW | DOWNLOAD | WRITE
LIMIT = 32 * 1024 * 1024
COLORS = ("bleu", "menthe", "lavande", "rose", "sable")
EMAIL = re.compile(r"[^\s@,;?&#]+@[^\s@,;?&#]+\.[^\s@,;?&#]+")
DUMMY_PASSWORD = generate_password_hash(secrets.token_hex(16))


class ImportErrorZIP(ValueError):
    pass


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    secret = os.environ.get("HUB_SECRET_KEY", "")
    secret_file = os.environ.get("HUB_SECRET_KEY_FILE")
    if secret_file:
        if secret:
            raise RuntimeError("Définissez une seule source pour la clé de session.")
        secret = Path(secret_file).read_text(encoding="utf-8").strip()
    if len(secret) < 32:
        raise RuntimeError("Définissez HUB_SECRET_KEY (au moins 32 caractères).")
    Path(app.instance_path).mkdir(mode=0o700, parents=True, exist_ok=True)
    database = os.environ.get("HUB_DATABASE", str(Path(app.instance_path) / "hub.sqlite3"))
    local_http = os.environ.get("HUB_LOCAL_HTTP") == "1"
    public_url = os.environ.get("HUB_PUBLIC_URL", "http://127.0.0.1:8080" if local_http else "")
    origin = urlsplit(public_url)
    if (not origin.hostname or origin.username or origin.password or origin.path not in ("", "/")
            or origin.query or origin.fragment or (origin.scheme != "https" and not local_http)):
        raise RuntimeError("Définissez HUB_PUBLIC_URL avec l’origine HTTPS du Hub.")
    auth_mode = os.environ.get("HUB_AUTH_MODE", "password")
    if auth_mode not in {"password", "email_code"}:
        raise RuntimeError("HUB_AUTH_MODE doit être password ou email_code.")
    mailer = CodeMailer.from_environment() if auth_mode == "email_code" else None
    app.config.update(
        TRUSTED_HOSTS=[origin.hostname] if not local_http else ["localhost", "127.0.0.1"],
        SECRET_KEY=secret,
        SESSION_COOKIE_SECURE=not local_http,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=LIMIT + 1024 * 1024,
    )

    def connect():
        db = sqlite3.connect(database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    with closing(connect()) as db:
        db.executescript(Path(__file__).with_name("ipr_schema.sql").read_text(encoding="utf-8"))

    @app.template_test("readable")
    def readable(mask):
        return bool(mask & VIEW)

    @app.template_test("downloadable")
    def downloadable(mask):
        return bool(mask & DOWNLOAD)

    @app.template_test("writable")
    def writable(mask):
        return bool(mask & WRITE)

    @app.cli.command("init-db")
    @click.option("--email", required=True)
    @click.password_option()
    def init_db(email, password):
        email = email.strip().lower()
        if not EMAIL.fullmatch(email) or not 14 <= len(password) <= 256:
            raise click.ClickException("Adresse valide et mot de passe de 14 caractères minimum requis.")
        with closing(connect()) as db, db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users WHERE admin=1").fetchone():
                raise click.ClickException("Un compte Animateur existe déjà.")
            db.execute("INSERT INTO users(email,password,admin,active) VALUES(?,?,1,1)",
                       (email, generate_password_hash(password)))
        click.echo("Espace initialisé.")

    @app.cli.command("migrate-db")
    def migrate_db():
        with closing(connect()) as db, db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                raise click.ClickException("Initialisez d’abord la base du Hub.")
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        click.echo("Schéma du Hub mis à jour.")

    @app.cli.command("backup-db")
    @click.argument("destination", type=click.Path(path_type=Path))
    def backup_db(destination):
        # SQLite takes a consistent copy, including changes still in the WAL.
        with closing(connect()) as source:
            try:
                ready = source.execute("SELECT 1 FROM users WHERE admin=1 AND active=1").fetchone()
            except sqlite3.Error as error:
                raise click.ClickException("La base du Hub est absente ou illisible.") from error
            if not ready:
                raise click.ClickException("La base du Hub doit être initialisée.")
            try:
                descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except OSError as error:
                raise click.ClickException(str(error)) from error
            os.close(descriptor)
            try:
                with closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
                    if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError("Contrôle de la sauvegarde échoué.")
            except sqlite3.Error as error:
                destination.unlink(missing_ok=True)
                raise click.ClickException(str(error)) from error
        click.echo("Sauvegarde SQLite vérifiée.")

    @app.get("/sante")
    def health():
        try:
            with closing(connect()) as db:
                ready = db.execute("SELECT 1 FROM users WHERE admin=1 AND active=1").fetchone()
                if mailer:
                    db.execute("SELECT 1 FROM login_codes LIMIT 1")
        except sqlite3.Error:
            ready = False
        return ("OK", 200) if ready else ("Indisponible", 503)

    @app.before_request
    def prepare():
        if request.endpoint in {"static", "health"} or isinstance(request.routing_exception, SecurityError):
            return
        g.db = connect()
        g.db.execute("BEGIN IMMEDIATE" if request.method == "POST" else "BEGIN")
        g.user = None
        if session.get("user"):
            g.user = g.db.execute("SELECT * FROM users WHERE id=? AND active=1 AND session_version=?",
                                  (session["user"], session.get("version")),).fetchone()
        if request.method == "POST":
            expected = session.get("csrf", "")
            if not expected or not secrets.compare_digest(expected, request.form.get("csrf", "")):
                abort(400, "Le formulaire a expiré. Rechargez la page.")
        if request.endpoint not in {"login", "activate", None} and g.user is None:
            return redirect(url_for("login"))

    @app.teardown_request
    def close_db(_error):
        if "db" in g:
            g.db.close()

    @app.after_request
    def headers(response):
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response

    @app.context_processor
    def template_values():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return dict(csrf=session["csrf"], VIEW=VIEW, DOWNLOAD=DOWNLOAD, WRITE=WRITE, colors=COLORS)

    def require_admin():
        if not g.user["admin"]:
            abort(403, "Cette action est réservée à l’animateur.")

    def get_node(node_id):
        if "nodes" not in g:
            g.nodes = {r["id"]: r for r in g.db.execute(
                "SELECT id,parent,name,kind,color,updated FROM nodes"
            )}
        node = g.nodes.get(node_id)
        if node is None:
            abort(404)
        return node

    def lineage(node):
        path = [node]
        while path[-1]["parent"] is not None:
            path.append(get_node(path[-1]["parent"]))
        return path[::-1]

    def rights(node):
        if g.user["admin"]:
            return ALL
        if "rights_cache" not in g:
            g.rights_cache = {}
            g.rules = defaultdict(dict)
            rows = g.db.execute(
                """SELECT node, subject_kind, mask FROM rules
                   WHERE (subject_kind='user' AND subject=?)
                      OR (subject_kind='group' AND subject IN
                          (SELECT group_id FROM memberships WHERE user_id=?))""",
                (g.user["id"], g.user["id"]),
            )
            for row in rows:
                key = row["subject_kind"]
                g.rules[row["node"]][key] = g.rules[row["node"]].get(key, 0) | row["mask"]
        effective = VIEW
        for part in lineage(node):
            node_id = part["id"]
            if node_id not in g.rights_cache:
                rule = g.rules.get(node_id, {})
                # The root is a navigation shell. Each top-level branch is private by default.
                inherited = 0 if part["parent"] == 1 else effective
                if part["parent"] is not None and not effective & VIEW:
                    g.rights_cache[node_id] = 0
                else:
                    g.rights_cache[node_id] = rule.get("user", rule.get("group", inherited))
            effective = g.rights_cache[node_id]
        return effective

    def allowed(node_id, permission, kind=None):
        node = get_node(node_id)
        if (kind and node["kind"] != kind) or not rights(node) & permission:
            abort(404)
        return node

    def clean_name(value):
        value = value.strip()
        if (not value or value in {".", ".."} or len(value) > 180
                or any(c in value for c in '/\\:') or any(ord(c) < 32 for c in value)):
            raise ValueError("Nom invalide ou trop long.")
        return value

    def insert_node(parent, name, kind, color="bleu", content=None):
        cursor = g.db.execute(
            """INSERT INTO nodes(id,parent,name,kind,color,content)
               SELECT MAX((SELECT MAX(id) FROM nodes), last_deleted_id) + 1, ?, ?, ?, ?, ?
               FROM node_id_watermark WHERE singleton=1""",
            (parent, name, kind, color, content),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Appliquez la migration de la base du Hub.")
        return cursor.lastrowid

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def show_error(error):
        if isinstance(error, SecurityError):
            return "Requête invalide.", 400
        messages = {
            403: error.description,
            404: "Le contenu est introuvable ou son accès est restreint.",
            413: "Le fichier dépasse la limite de 32 Mio.",
            429: "Trop de tentatives. Réessayez dans quelques minutes.",
        }
        return render_template("error.html", message=messages.get(error.code, error.description)), error.code

    @app.route("/connexion", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("folder"))
        if mailer:
            return login_with_code(mailer)
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()[:254]
            password = request.form.get("password", "")
            now = int(time.time())
            # Shared limit per account, including unknown accounts, plus a per-IP limit.
            keys = ("email:" + email, "ip:" + (request.remote_addr or "inconnue"))
            g.db.execute("DELETE FROM attempts WHERE at < ?", (now - 900,))
            for key, limit in zip(keys, (8, 40)):
                if g.db.execute("SELECT COUNT(*) FROM attempts WHERE key=?", (key,)).fetchone()[0] >= limit:
                    abort(429)
            user = g.db.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
            stored_hash = user["password"] if user else DUMMY_PASSWORD
            if len(password) <= 256 and check_password_hash(stored_hash, password) and user:
                g.db.commit()
                return start_session(user["id"], user["session_version"])
            g.db.executemany("INSERT INTO attempts VALUES(?,?)", [(key, now) for key in keys])
            g.db.commit()
            flash("Identifiants incorrects.")
        return render_template("login.html")

    @app.post("/deconnexion")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/activation/<token>", methods=["GET", "POST"])
    def activate(token):
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invitation = g.db.execute(
            """SELECT users.id, users.email FROM invites JOIN users ON users.id=invites.user_id
               WHERE token_hash=? AND expires>? AND users.password IS NULL""",
            (token_hash, int(time.time())),
        ).fetchone()
        if invitation is None:
            abort(404)
        if request.method == "POST":
            password = request.form.get("password", "")
            if not mailer and not 14 <= len(password) <= 256:
                flash("Choisissez un mot de passe de 14 à 256 caractères.")
            else:
                password_hash = "email-code-only" if mailer else generate_password_hash(password)
                g.db.execute("UPDATE users SET password=?, active=1 WHERE id=?",
                             (password_hash, invitation["id"]))
                g.db.execute("DELETE FROM invites WHERE user_id=?", (invitation["id"],))
                g.db.commit()
                session.clear()
                return redirect(url_for("login"))
        return render_template("login.html", invitation=invitation, use_code=bool(mailer))

    @app.get("/")
    @app.get("/dossier/<int:node_id>")
    def folder(node_id=1):
        node = allowed(node_id, VIEW, "folder")
        children = defaultdict(list)
        visible_files = []
        search = request.args.get("q", "").strip().casefold()
        for entry in sorted(g.nodes.values(), key=lambda row: row["id"]):
            if entry["kind"] == "folder" and entry["parent"] and rights(entry) & VIEW:
                children[entry["parent"]].append(entry)
            elif (entry["kind"] == "file" and entry["parent"] == node_id
                  and rights(entry) & VIEW and search in entry["name"].casefold()):
                visible_files.append(entry)
        visible_files.sort(key=lambda row: row["name"].casefold())
        connected, nuage_files, nuage_error = nuage_documents(node_id)
        return render_template("folder.html", node=node, trail=lineage(node), children=children,
                               files=visible_files, rights=rights, search=search,
                               nuage_connected=connected, nuage_error=nuage_error,
                               nuage_files=[(name, link) for name, link in nuage_files if search in name.casefold()])

    @app.post("/dossier/<int:node_id>/ajouter")
    def add_folder(node_id):
        node = allowed(node_id, WRITE, "folder")
        color = request.form.get("color", "bleu")
        if color not in COLORS:
            abort(400, "Couleur inconnue.")
        try:
            if len(lineage(node)) >= 64:
                raise ValueError("Limite de 63 niveaux de sous-dossiers atteinte.")
            child = insert_node(node_id, clean_name(request.form.get("name", "")), "folder", color)
            g.db.commit()
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error) if isinstance(error, ValueError) else "Ce nom existe déjà dans ce dossier.")
            return redirect(url_for("folder", node_id=node_id))
        return redirect(url_for("folder", node_id=child))

    @app.post("/dossier/<int:node_id>/renommer")
    def rename_folder(node_id):
        node = allowed(node_id, WRITE, "folder")
        if node["parent"] is None:
            abort(403, "Le dossier racine ne peut pas être renommé.")
        try:
            name = clean_name(request.form.get("name", ""))
            g.db.execute("UPDATE nodes SET name=?, updated=strftime('%Y-%m-%d %H:%M','now') WHERE id=?",
                         (name, node_id))
            g.db.commit()
            flash("Dossier renommé.")
        except (ValueError, sqlite3.IntegrityError) as error:
            g.db.rollback()
            flash(str(error) if isinstance(error, ValueError) else "Ce nom existe déjà dans ce dossier.")
        return redirect(url_for("folder", node_id=node_id))

    @app.post("/dossier/<int:node_id>/supprimer")
    def delete_folder(node_id):
        node = allowed(node_id, WRITE, "folder")
        if node["parent"] is None:
            abort(403, "Le dossier racine ne peut pas être supprimé.")
        if request.form.get("confirm") != "yes":
            abort(400, "Confirmez la suppression du dossier.")
        if g.db.execute("SELECT 1 FROM nodes WHERE parent=? LIMIT 1", (node_id,)).fetchone():
            flash("Videz ce dossier avant de le supprimer.")
            return redirect(url_for("folder", node_id=node_id))
        g.db.execute("UPDATE node_id_watermark SET last_deleted_id=MAX(last_deleted_id, ?) WHERE singleton=1",
                     (node_id,))
        g.db.execute("DELETE FROM rules WHERE node=?", (node_id,))
        g.db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        g.db.commit()
        flash("Dossier supprimé.")
        return redirect(url_for("folder", node_id=node["parent"]))

    @app.post("/dossier/<int:node_id>/couleur")
    def folder_color(node_id):
        require_admin()
        allowed(node_id, VIEW, "folder")
        color = request.form.get("color")
        if color not in COLORS:
            abort(400, "Couleur inconnue.")
        g.db.execute("UPDATE nodes SET color=? WHERE id=?", (color, node_id))
        g.db.commit()
        return redirect(url_for("folder", node_id=node_id))

    @app.post("/dossier/<int:node_id>/fichiers")
    def upload(node_id):
        allowed(node_id, WRITE, "folder")
        try:
            files = request.files.getlist("files")
            if not files or len(files) > 200:
                raise ValueError("Sélectionnez entre 1 et 200 fichiers.")
            total = 0
            for file in files:
                name = clean_name(file.filename or "")
                data = file.read(LIMIT + 1)
                total += len(data)
                if total > LIMIT:
                    raise ValueError("La sélection dépasse 32 Mio.")
                insert_node(node_id, name, "file", content=data)
            g.db.commit()
            flash("Documents importés.")
        except (ValueError, sqlite3.IntegrityError) as error:
            g.db.rollback()
            flash(str(error) if isinstance(error, ValueError) else "Un nom existe déjà. Aucun fichier importé.")
        return redirect(url_for("folder", node_id=node_id))

    def unpack(archive, node):
        infos = archive.infolist()
        if len(infos) > 1000 or sum(info.file_size for info in infos) > LIMIT:
            raise ImportErrorZIP("Le ZIP dépasse 1 000 entrées ou 32 Mio décompressés.")
        imported_folders = {(): node["id"]}
        depth = len(lineage(node))
        for info in infos:
            if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                raise ImportErrorZIP("Les archives chiffrées et les liens symboliques sont refusés.")
            parts = tuple(info.filename.rstrip("/").split("/"))
            if depth + len(parts) > 64 or any(clean_name(part) != part for part in parts):
                raise ImportErrorZIP("L’archive contient un chemin invalide.")
            parent = node["id"]
            folders = parts if info.is_dir() else parts[:-1]
            for i, name in enumerate(folders, 1):
                path = folders[:i]
                if path not in imported_folders:
                    imported_folders[path] = insert_node(parent, name, "folder")
                parent = imported_folders[path]
            if not info.is_dir():
                insert_node(parent, parts[-1], "file", content=archive.read(info))

    @app.post("/dossier/<int:node_id>/importer-zip")
    def import_zip(node_id):
        node = allowed(node_id, WRITE, "folder")
        file = request.files.get("archive")
        try:
            if not file:
                raise ImportErrorZIP("Sélectionnez une archive ZIP.")
            with ZipFile(file.stream) as archive:
                unpack(archive, node)
            g.db.commit()
            flash("Arborescence importée.")
        except (BadZipFile, ValueError, RuntimeError, NotImplementedError, zlib.error, sqlite3.IntegrityError) as error:
            g.db.rollback()
            if isinstance(error, sqlite3.IntegrityError):
                flash("Un nom existe déjà. Aucun élément importé.")
            else:
                flash(str(error) if isinstance(error, ValueError) else "Archive ZIP invalide ou illisible.")
        return redirect(url_for("folder", node_id=node_id))

    @app.get("/dossier/<int:node_id>/exporter-zip")
    def export_zip(node_id):
        node = allowed(node_id, DOWNLOAD, "folder")
        children = defaultdict(list)
        for row in g.nodes.values():
            children[row["parent"]].append(row)
        pending = [(node, node["name"] + "/")]
        entries = []
        while pending:
            row, path = pending.pop()
            if not rights(row) & DOWNLOAD:
                abort(403, "L’archive complète contient des éléments dont le téléchargement est restreint.")
            if len(entries) >= 1000:
                abort(413)
            entries.append((row, path))
            if row["kind"] == "folder":
                for child in children[row["id"]]:
                    suffix = "/" if child["kind"] == "folder" else ""
                    pending.append((child, path + child["name"] + suffix))
        target = io.BytesIO()
        total = 0
        with ZipFile(target, "w", ZIP_DEFLATED) as archive:
            for row, path in entries:
                data = b""
                if row["kind"] == "file":
                    size = g.db.execute("SELECT length(content) FROM nodes WHERE id=?", (row["id"],)).fetchone()[0]
                    total += size
                    if total > LIMIT:
                        abort(413)
                    data = content(row["id"])
                archive.writestr(path, data)
        target.seek(0)
        return send_file(target, mimetype="application/zip", as_attachment=True,
                         download_name=node["name"] + ".zip", conditional=False)

    def content(node_id):
        return g.db.execute("SELECT content FROM nodes WHERE id=?", (node_id,)).fetchone()[0]

    @app.get("/document/<int:node_id>")
    def document(node_id):
        node = allowed(node_id, VIEW, "file")
        suffix = Path(node["name"]).suffix.lower()
        preview = suffix in {".pdf", ".txt", ".csv"}
        page = max(1, min(1000, request.args.get("page", 1, type=int)))
        return render_template("document.html", node=node, trail=lineage(node),
                               mask=rights(node), preview=preview, suffix=suffix, page=page)

    @app.get("/document/<int:node_id>/telecharger")
    def download(node_id):
        node = allowed(node_id, DOWNLOAD, "file")
        return send_file(io.BytesIO(content(node_id)), mimetype="application/octet-stream",
                         as_attachment=True, download_name=node["name"], conditional=False)

    @app.get("/document/<int:node_id>/apercu/<int:page>")
    def preview_pdf(node_id, page):
        node = allowed(node_id, VIEW, "file")
        if Path(node["name"]).suffix.lower() != ".pdf" or not 1 <= page <= 1000:
            abort(404)
        data = content(node_id)
        g.db.rollback()
        try:
            rendered = subprocess.run(
                ["pdftoppm", "-f", str(page), "-l", str(page), "-scale-to", "1400", "-png", "-"],
                input=data, capture_output=True, check=True, timeout=8,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            abort(404)
        if not rendered.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            abort(404)
        return send_file(io.BytesIO(rendered.stdout), mimetype="image/png", conditional=False)

    @app.get("/document/<int:node_id>/texte")
    def preview_text(node_id):
        node = allowed(node_id, VIEW, "file")
        if Path(node["name"]).suffix.lower() not in {".txt", ".csv"}:
            abort(404)
        data = g.db.execute("SELECT substr(content,1,100001) FROM nodes WHERE id=?", (node_id,)).fetchone()[0]
        return render_template("text.html", data=data[:100000].decode("utf-8", "replace"),
                               truncated=len(data) > 100000)

    def people():
        return g.db.execute("SELECT id,email,active,admin,password IS NOT NULL AS activated FROM users ORDER BY email").fetchall()

    def groups():
        return g.db.execute("SELECT * FROM groups ORDER BY name").fetchall()

    @app.route("/droits/<int:node_id>", methods=["GET", "POST"])
    def permissions(node_id):
        require_admin()
        node = get_node(node_id)
        if node_id == 1:
            abort(404)
        if request.method == "POST":
            kind = request.form.get("kind")
            subject = request.form.get("subject", type=int)
            available = people() if kind == "user" else groups() if kind == "group" else ()
            if subject not in {row["id"] for row in available if kind != "user" or not row["admin"]}:
                abort(400, "Destinataire introuvable.")
            action = request.form.get("action")
            if action == "inherit":
                g.db.execute("DELETE FROM rules WHERE node=? AND subject_kind=? AND subject=?",
                             (node_id, kind, subject))
            else:
                mask = sum(bit for field, bit in (("read", VIEW), ("download", DOWNLOAD), ("write", WRITE if node["kind"] == "folder" else 0))
                           if request.form.get(field) == "1")
                if mask:
                    mask |= VIEW
                g.db.execute(
                    """INSERT INTO rules VALUES(?,?,?,?)
                       ON CONFLICT(node,subject_kind,subject) DO UPDATE SET mask=excluded.mask""",
                    (node_id, kind, subject, mask),
                )
            g.db.commit()
            flash("Autorisations mises à jour.")
            return redirect(url_for("permissions", node_id=node_id))
        rules = g.db.execute(
            """SELECT rules.*, COALESCE(users.email, groups.name) AS label FROM rules
               LEFT JOIN users ON subject_kind='user' AND users.id=subject
               LEFT JOIN groups ON subject_kind='group' AND groups.id=subject
               WHERE node=? ORDER BY subject_kind,label""", (node_id,),
        ).fetchall()
        return render_template("permissions.html", node=node, rules=rules, people=people(), groups=groups())

    @app.get("/annuaire")
    def directory():
        require_admin()
        members = defaultdict(set)
        for row in g.db.execute("SELECT * FROM memberships"):
            members[row["user_id"]].add(row["group_id"])
        return render_template("directory.html", people=people(), groups=groups(), members=members,
                               ipr_group_id=ipr_group_id())

    @app.post("/annuaire/groupe")
    def add_group():
        require_admin()
        try:
            g.db.execute("INSERT INTO groups(name) VALUES(?)", (clean_name(request.form.get("name", "")),))
            g.db.commit()
        except (ValueError, sqlite3.IntegrityError):
            flash("Nom de groupe invalide ou déjà utilisé.")
        return redirect(url_for("directory"))

    @app.post("/annuaire/compte/<int:user_id>")
    def manage_user(user_id):
        require_admin()
        user = g.db.execute("SELECT * FROM users WHERE id=? AND admin=0", (user_id,)).fetchone()
        if not user:
            abort(404)
        if request.form.get("action") == "suspend":
            g.db.execute("UPDATE users SET active=0, session_version=session_version+1 WHERE id=?", (user_id,))
            g.db.execute("DELETE FROM invites WHERE user_id=?", (user_id,))
        elif request.form.get("action") == "resume":
            if not user["password"]:
                abort(400, "Ce compte doit d’abord activer son invitation.")
            g.db.execute("UPDATE users SET active=1 WHERE id=?", (user_id,))
        else:
            selection = {value for value in request.form.getlist("groups", type=int)}
            if not selection <= {row["id"] for row in groups()}:
                abort(400, "Groupe inconnu.")
            g.db.execute("DELETE FROM memberships WHERE user_id=?", (user_id,))
            g.db.executemany("INSERT INTO memberships VALUES(?,?)",
                             [(user_id, group_id) for group_id in selection])
        g.db.commit()
        flash("Compte mis à jour.")
        return redirect(url_for("directory"))

    def mailto(email, subject, body):
        return "mailto:" + quote(email, safe="@") + "?subject=" + quote(subject) + "&body=" + quote(body)

    def public_link(endpoint, **values):
        return public_url.rstrip("/") + url_for(endpoint, **values)

    @app.post("/annuaire/inviter")
    def invite():
        require_admin()
        email = request.form.get("email", "").strip().lower()
        if len(email) > 254 or not EMAIL.fullmatch(email):
            abort(400, "Adresse électronique invalide.")
        user = g.db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and user["password"]:
            flash("Ce compte a déjà été activé.")
            return redirect(url_for("directory"))
        user_id = user["id"] if user else g.db.execute("INSERT INTO users(email) VALUES(?)", (email,)).lastrowid
        token = secrets.token_urlsafe(32)
        g.db.execute("DELETE FROM invites WHERE user_id=?", (user_id,))
        g.db.execute("INSERT INTO invites VALUES(?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + 48 * 3600))
        g.db.commit()
        link = public_link("activate", token=token)
        body = "Bonjour,\n\nVoici votre invitation à l’espace IA-IPR EPS. Le lien est valable 48 heures.\n\n" + link
        return render_template("message.html", title="Invitation prête", link=link,
                               draft=mailto(email, "Invitation à l’espace IA-IPR EPS", body))

    @app.route("/demandes", methods=["GET", "POST"])
    def messages():
        require_admin()
        if request.method == "POST":
            recipients = {row["id"]: row["email"] for row in people() if row["active"]}
            email = recipients.get(request.form.get("recipient", type=int))
            subject = request.form.get("subject", "").strip()
            body = request.form.get("body", "").strip()
            if not email or not subject or not body or len(subject) > 120 or len(body) > 2000:
                abort(400, "Renseignez un destinataire, un objet et un message valides.")
            return render_template("message.html", title="Demande prête",
                                   draft=mailto(email, subject, body))
        return render_template("messages.html", people=[row for row in people() if row["active"]])

    register_ipr_modules(app)
    nuage_documents = register_nuage(app, allowed, lineage, rights, VIEW, WRITE)
    return app
