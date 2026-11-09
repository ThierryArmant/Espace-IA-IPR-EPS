"""Le Hub reprend l'arborescence Nuage, en appliquant ses propres droits.

Chaque dossier du Hub correspond au dossier Nuage de même chemin sous la racine.
Les fichiers restent dans Nuage : le Hub les liste, les montre et les sert
seulement aux personnes autorisées, avec le compte de service.
"""
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from nuage_pilote import OFFICE_TYPES, blank_office_document
from activite import detect_changes, record as record_activity
from nuage_stockage import StorageError

PREVIEW_LIMIT = 32 * 1024 * 1024
MAX_SYNC_FOLDERS = 5000


def valid_name(name):
    return (bool(name) and name not in {".", ".."} and len(name) <= 180
            and not any(c in name for c in '/\\:') and not any(ord(c) < 32 for c in name))


def name_key(name):
    """Clé de comparaison tolérante : accents composés, apostrophes, espaces, casse."""
    name = unicodedata.normalize("NFC", name).replace("\u2019", "'").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", name).strip().casefold()


def folder_path(lineage_rows):
    return tuple(row["name"] for row in lineage_rows[1:])


def insert_folder(db, parent, name):
    db.execute(
        """INSERT INTO nodes(id,parent,name,kind,color)
           SELECT MAX((SELECT MAX(id) FROM nodes), last_deleted_id) + 1, ?, ?, 'folder', 'bleu'
           FROM node_id_watermark WHERE singleton=1""",
        (parent, name),
    )
    return db.execute("SELECT id FROM nodes WHERE parent=? AND name=?", (parent, name)).fetchone()[0]


def synchronize(db, storage, start_id=1, echo=print):
    """Crée dans le Hub les dossiers Nuage manquants, à partir de start_id.

    Lit d'abord toute l'arborescence Nuage sans toucher à la base, puis écrit les
    dossiers manquants en une seule transaction courte.
    """
    rows = {row[0]: row for row in db.execute("SELECT id,parent,name FROM nodes WHERE kind='folder'")}
    db.rollback()

    def path_of(node_id):
        names = []
        while rows[node_id][1] is not None:
            names.append(rows[node_id][2])
            node_id = rows[node_id][1]
        return tuple(reversed(names))

    base = path_of(start_id)
    found, skipped, pending, seen = [], [], [()], 0
    while pending:
        relative = pending.pop()
        seen += 1
        if seen > MAX_SYNC_FOLDERS:
            echo("Limite de dossiers atteinte : relancez la synchronisation plus bas dans l’arborescence.")
            break
        if seen % 25 == 0:
            echo(f"… {seen} dossiers lus dans Nuage")
        content = storage.listing((*base, *relative))
        if content is None:
            continue
        for name in content[0]:
            if not valid_name(name) or len(base) + len(relative) >= 63:
                skipped.append("/".join((*base, *relative, name)))
                continue
            found.append((*relative, name))
            pending.append((*relative, name))

    db.execute("BEGIN IMMEDIATE")
    rows = {row[0]: row for row in db.execute("SELECT id,parent,name FROM nodes WHERE kind='folder'")}
    children = {}
    for node_id, parent, name in rows.values():
        children.setdefault(parent, {})[name_key(name)] = node_id
    ids, created, renamed = {(): start_id}, 0, 0
    for relative in sorted(found, key=len):
        parent = ids.get(relative[:-1])
        if parent is None:
            continue
        child = children.get(parent, {}).get(name_key(relative[-1]))
        if child is None:
            child = insert_folder(db, parent, relative[-1])
            children.setdefault(parent, {})[name_key(relative[-1])] = child
            created += 1
        elif rows[child][2] != relative[-1]:
            # Même dossier, écriture différente : le Hub reprend le nom exact de Nuage.
            db.execute("UPDATE nodes SET name=? WHERE id=?", (relative[-1], child))
            renamed += 1
        ids[relative] = child
    db.commit()
    if renamed:
        echo(f"{renamed} dossier(s) renommé(s) dans le Hub pour reprendre l’écriture exacte de Nuage.")
    for name in skipped:
        echo(f"Dossier ignoré (nom non accepté par le Hub) : {name}")
    return created, skipped


def register_mirror(app, storage, *, allowed, lineage, rights, require_admin, view, download, write):
    mirror = Blueprint("miroir", __name__)

    def content_mask(node):
        # La page d’accueil est ouverte à tous : ses fichiers Nuage ne sont montrés à personne.
        if node["parent"] is None:
            return 0
        return rights(node, structure=False)

    def folder_and_path(node_id, permission):
        node = allowed(node_id, view, "folder")
        if not content_mask(node) & permission:
            abort(404)
        return node, folder_path(lineage(node))

    def requested_name():
        name = request.args.get("nom", "")
        if not valid_name(name):
            abort(404)
        return name

    def files(node):
        """Fichiers Nuage visibles pour le lecteur, sous-dossiers Nuage absents du Hub."""
        if not content_mask(node) & view:
            return [], None, []
        path = folder_path(lineage(node))
        try:
            content = storage.listing(path)
        except StorageError as error:
            return [], str(error), []
        if content is None:
            return [], None, []
        detect_changes(g.db, node["id"], content[1])
        known = {row["name"].casefold() for row in g.nodes.values() if row["parent"] == node["id"]}
        missing = [name for name in content[0] if name.casefold() not in known]
        return content[1], None, missing

    def upload(node, batch):
        path = folder_path(lineage(node))
        g.db.rollback()  # Les transferts peuvent être longs : libérer la base.
        content = storage.listing(path)
        existing = {item["name"].casefold() for item in content[1]} if content else set()
        clash = [name for name, _ in batch if name.casefold() in existing]
        if clash:
            raise ValueError(f"« {clash[0]} » existe déjà dans ce dossier. Aucun fichier importé.")
        sent = []
        try:
            for name, data in batch:
                storage.put((*path, name), data)
                sent.append((*path, name))
        except FileExistsError as error:
            for item in sent:
                storage.delete(item)
            raise ValueError(f"« {error} » existe déjà dans ce dossier. Aucun fichier importé.") from error
        except StorageError:
            for item in sent:
                storage.delete(item)
            raise

    def import_tree(node, folders, files_to_send):
        base = folder_path(lineage(node))
        sent = []
        try:
            for folder in folders:
                storage.make_folders((*base, *folder))
            for parts, data in files_to_send:
                storage.put((*base, *parts), data)
                sent.append((*base, *parts))
        except FileExistsError as error:
            for item in sent:
                storage.delete(item)
            raise ValueError(f"« {error} » existe déjà dans Nuage. Aucun élément importé.") from error
        except StorageError:
            for item in sent:
                storage.delete(item)
            raise

    def folder_created(node):
        storage.make_folders(folder_path(lineage(node)))

    def folder_renamed(node, new_name):
        path = folder_path(lineage(node))
        status = storage.move(path, (*path[:-1], new_name))
        if status in {201, 204, 404}:
            return
        if status == 412:
            raise ValueError("Un dossier porte déjà ce nom dans Nuage.")
        raise StorageError(f"Nuage n’a pas renommé le dossier ({status}).")

    def folder_moved(node, destination):
        source = folder_path(lineage(node))
        target = (*folder_path(lineage(destination)), node["name"])
        status = storage.move(source, target)
        if status in {201, 204, 404}:
            return
        if status == 412:
            raise ValueError("Un dossier porte déjà ce nom à cet endroit dans Nuage.")
        if status == 409:
            storage.make_folders(target[:-1])
            status = storage.move(source, target)
            if status in {201, 204}:
                return
        raise StorageError(f"Nuage n’a pas déplacé le dossier ({status}).")

    def folder_deleted(node):
        path = folder_path(lineage(node))
        content = storage.listing(path)
        if content is None:
            return
        if content[0] or content[1]:
            raise ValueError("Ce dossier contient encore des éléments dans Nuage.")
        storage.delete(path)

    def unavailable():
        abort(503, "Nuage ne répond pas. Réessayez dans quelques minutes.")

    @mirror.get("/dossier/<int:node_id>/fichier")
    def document(node_id):
        node, path = folder_and_path(node_id, view)
        name = requested_name()
        try:
            item = storage.file_info((*path, name))
        except StorageError:
            unavailable()
        if item is None:
            abort(404)
        suffix = Path(name).suffix.lower()
        mask = content_mask(node)
        page = max(1, min(1000, request.args.get("page", 1, type=int)))
        return render_template("nuage_fichier.html", node=node, trail=lineage(node), item=item,
                               suffix=suffix, page=page, mask=mask)

    @mirror.get("/dossier/<int:node_id>/fichier/telecharger")
    def download_file(node_id):
        _, path = folder_and_path(node_id, download)
        name = requested_name()
        g.db.rollback()
        try:
            response = storage.open((*path, name))
        except StorageError:
            unavailable()

        def chunks():
            with response:
                while block := response.read(64 * 1024):
                    yield block

        headers = {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)}
        length = response.headers.get("Content-Length")
        if length and length.isdigit():
            headers["Content-Length"] = length
        return Response(chunks(), mimetype="application/octet-stream", headers=headers)

    @mirror.get("/dossier/<int:node_id>/fichier/apercu/<int:page>")
    def preview_pdf(node_id, page):
        _, path = folder_and_path(node_id, view)
        name = requested_name()
        if Path(name).suffix.lower() != ".pdf" or not 1 <= page <= 1000:
            abort(404)
        g.db.rollback()
        try:
            data = storage.get((*path, name), PREVIEW_LIMIT)
        except (StorageError, ValueError):
            abort(404)
        try:
            rendered = subprocess.run(
                ["pdftoppm", "-f", str(page), "-l", str(page), "-scale-to", "1400", "-png", "-"],
                input=data, capture_output=True, check=True, timeout=8,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            abort(404)
        if not rendered.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            abort(404)
        return Response(rendered.stdout, mimetype="image/png")

    @mirror.get("/dossier/<int:node_id>/fichier/texte")
    def preview_text(node_id):
        _, path = folder_and_path(node_id, view)
        name = requested_name()
        if Path(name).suffix.lower() not in {".txt", ".csv"}:
            abort(404)
        g.db.rollback()
        try:
            data = storage.get((*path, name), PREVIEW_LIMIT, 100001)
        except (StorageError, ValueError):
            unavailable()
        return render_template("text.html", data=data[:100000].decode("utf-8", "replace"),
                               truncated=len(data) > 100000)

    @mirror.post("/dossier/<int:node_id>/creer/<kind>")
    def create_office(node_id, kind):
        if kind not in OFFICE_TYPES:
            abort(404)
        _, path = folder_and_path(node_id, write)
        extension, _, data = blank_office_document(kind)
        label = request.form.get("titre", "").strip() or ("Tableur" if kind == "tableur" else "Document")
        if not valid_name(f"{label}.{extension}"):
            flash("Titre invalide : évitez / \\ et :.")
            return redirect(url_for("folder", node_id=node_id))
        g.db.rollback()
        name, number = f"{label}.{extension}", 1
        try:
            while True:
                try:
                    storage.put((*path, name), data)
                    break
                except FileExistsError:
                    number += 1
                    name = f"{label} ({number}).{extension}"
                    if number > 50:
                        raise StorageError("Trop de fichiers portent ce nom.")
        except StorageError as error:
            flash(str(error))
            return redirect(url_for("folder", node_id=node_id))
        record_activity(g.db, node_id, "creation", name, g.user["id"], fresh=True)
        g.db.commit()
        flash(f"« {name} » a été créé. Cliquez sur « Modifier à plusieurs » pour l’ouvrir dans Collabora.")
        return redirect(url_for("folder", node_id=node_id))

    @mirror.post("/dossier/<int:node_id>/synchroniser")
    def sync(node_id):
        require_admin()
        allowed(node_id, view, "folder")
        messages = []
        try:
            created, skipped = synchronize(g.db, storage, node_id, messages.append)
        except StorageError as error:
            g.db.rollback()
            flash(str(error))
            return redirect(url_for("folder", node_id=node_id))
        flash(f"{created} dossier(s) Nuage ajouté(s) au Hub." + (
            f" {len(skipped)} ignoré(s) car leur nom contient / \\ ou :." if skipped else ""))
        return redirect(url_for("folder", node_id=node_id))

    app.register_blueprint(mirror)
    return type("Mirror", (), dict(
        files=staticmethod(files), upload=staticmethod(upload), import_tree=staticmethod(import_tree),
        folder_created=staticmethod(folder_created), folder_renamed=staticmethod(folder_renamed),
        folder_deleted=staticmethod(folder_deleted), folder_moved=staticmethod(folder_moved),
    ))
