"""Shared tools scoped to one group in the Hub directory."""
import io
import json
from datetime import datetime
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

MODULES = {
    "evenements": ("Événements", "▦", "Publier un événement et recueillir les participations."),
    "reunions": ("Réunions", "◉", "Fixer une réunion, partager son ordre du jour et son lien de visioconférence."),
    "creneaux": ("Créneaux", "◷", "Proposer des créneaux et réserver les places disponibles."),
    "questionnaires": ("Questionnaires", "☷", "Poser des questions au groupe et consulter les réponses reçues."),
    "marque-pages": ("Marque-pages", "◇", "Retrouver les liens utiles du groupe."),
    "publications": ("Publications", "▤", "Partager les annonces et les informations du groupe."),
}
SCHEDULED = {"evenements", "reunions", "creneaux"}
RSVP = {"evenements", "reunions"}
ATTACHMENT_LIMIT = 16 * 1024 * 1024
ATTACHMENT_COUNT = 5


def group_id():
    if "ipr_group_id" not in g:
        row = g.db.execute("SELECT group_id FROM ipr_settings WHERE id=1").fetchone()
        if row is None:
            row = g.db.execute("SELECT id FROM groups WHERE name='IPR'").fetchone()
        g.ipr_group_id = row[0] if row else None
    return g.ipr_group_id


def has_access():
    if not g.get("user"):
        return False
    if g.user["admin"]:
        return True
    return g.db.execute("SELECT 1 FROM memberships WHERE group_id=? AND user_id=?",
                        (group_id(), g.user["id"])).fetchone() is not None


def entry_fields(module):
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    if not title or len(title) > 180 or len(body) > 12000:
        raise ValueError("Renseignez un titre de 180 caractères maximum et un texte de 12 000 caractères maximum.")
    link = ""
    if module in {"evenements", "reunions", "marque-pages"}:
        link = request.form.get("link", "").strip()
        if link or module == "marque-pages":
            parsed = urlsplit(link)
            if (len(link) > 2048 or parsed.scheme not in {"https", "http"} or not parsed.hostname
                    or parsed.username is not None or any(char.isspace() or ord(char) < 32 for char in link)):
                raise ValueError("Renseignez un lien commençant par https:// ou http://.")
    starts, ends = "", ""
    if module in SCHEDULED:
        starts = request.form.get("starts", "")
        ends = request.form.get("ends", "")
        try:
            for value in (starts, ends) if ends else (starts,):
                if datetime.strptime(value, "%Y-%m-%dT%H:%M").isoformat(timespec="minutes") != value:
                    raise ValueError
        except ValueError:
            raise ValueError("Renseignez une date et une heure valides.") from None
        if (module == "creneaux" and not ends) or (ends and ends <= starts):
            raise ValueError("L’heure de fin doit être postérieure à l’heure de début.")
    capacity = None
    if module == "creneaux":
        capacity = request.form.get("capacity", type=int)
        if capacity is None or not 1 <= capacity <= 1000:
            raise ValueError("Indiquez un nombre de places entre 1 et 1 000.")
    questions = []
    if module == "questionnaires":
        questions = [line.strip() for line in request.form.get("questions", "").splitlines() if line.strip()]
        if not 1 <= len(questions) <= 30 or any(len(question) > 400 for question in questions):
            raise ValueError("Saisissez de 1 à 30 questions de 400 caractères maximum, une par ligne.")
    return title, body, starts, ends, link, capacity, json.dumps(questions, ensure_ascii=False)


def publication_uploads(attachments):
    current_ids = {item["id"] for item in attachments}
    removed = set(request.form.getlist("remove_attachment", type=int))
    if not removed <= current_ids:
        raise ValueError("Une pièce jointe sélectionnée n’est plus disponible.")
    kept = [item for item in attachments if item["id"] not in removed]
    files = [file for file in request.files.getlist("attachments") if file.filename]
    if len(kept) + len(files) > ATTACHMENT_COUNT:
        raise ValueError("Une publication peut contenir jusqu’à cinq pièces jointes.")
    remaining = ATTACHMENT_LIMIT - sum(item["size"] for item in kept)
    names = {item["name"].casefold() for item in kept}
    uploads = []
    for file in files:
        name = file.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if (not name or name in {".", ".."} or len(name) > 180
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise ValueError("Le nom d’une pièce jointe est invalide ou trop long.")
        if name.casefold() in names:
            raise ValueError("Deux pièces jointes portent le même nom.")
        content = file.stream.read(remaining + 1)
        if not content:
            raise ValueError("Une pièce jointe est vide.")
        if len(content) > remaining:
            raise ValueError("Les pièces jointes ne doivent pas dépasser 16 Mio au total.")
        names.add(name.casefold())
        remaining -= len(content)
        uploads.append((name, content))
    return kept, removed, uploads


def register_ipr_modules(app):
    bp = Blueprint("ipr", __name__, url_prefix="/applications")

    @bp.app_context_processor
    def sidebar_modules():
        return {"ipr_visible": has_access(), "ipr_modules": MODULES}

    @bp.post("/groupe")
    def configure():
        if not g.user["admin"]:
            abort(403)
        selection = request.form.get("group", type=int)
        if not g.db.execute("SELECT 1 FROM groups WHERE id=?", (selection,)).fetchone():
            abort(400, "Groupe introuvable.")
        g.db.execute("""INSERT INTO ipr_settings VALUES(1,?)
                        ON CONFLICT(id) DO UPDATE SET group_id=excluded.group_id""", (selection,))
        g.db.commit()
        flash("Groupe des applications enregistré.")
        return redirect(url_for("directory"), code=303)

    @bp.get("/annuaire")
    def directory():
        if not has_access():
            abort(403)
        members = g.db.execute(
            """SELECT users.email FROM users JOIN memberships ON memberships.user_id=users.id
               WHERE memberships.group_id=? AND users.active=1 ORDER BY users.email""", (group_id(),)
        ).fetchall()
        return render_template("ipr_directory.html", members=members)

    @bp.get("/publications/<int:publication_id>/pieces-jointes/<int:attachment_id>")
    def publication_attachment(publication_id, attachment_id):
        if not has_access() or group_id() is None:
            abort(403)
        attachment = g.db.execute(
            """SELECT a.name,a.content FROM publication_attachments a
               JOIN ipr_entries p ON p.id=a.publication_id
               WHERE a.id=? AND p.id=? AND p.group_id=? AND p.module='publications'""",
            (attachment_id, publication_id, group_id()),
        ).fetchone()
        if attachment is None:
            abort(404)
        return send_file(io.BytesIO(attachment["content"]), mimetype="application/octet-stream",
                         as_attachment=True, download_name=attachment["name"], conditional=False)

    @bp.route("/<module>", methods=["GET", "POST"])
    def module_page(module):
        if module not in MODULES:
            abort(404)
        if not has_access():
            abort(403)
        scope = group_id()
        if scope is None:
            if request.method == "POST":
                abort(400, "Choisissez d’abord le groupe dans l’annuaire.")
            return render_template("ipr_module.html", module=module, configured=False)

        entries = g.db.execute(
            """SELECT * FROM ipr_entries WHERE group_id=? AND module=?
               ORDER BY starts_at, id DESC""", (scope, module)
        ).fetchall()
        selected_id = (request.form if request.method == "POST" else request.args).get("entry", type=int)
        selected = next((entry for entry in entries if entry["id"] == selected_id), None)
        if selected_id is not None and selected is None:
            abort(404)
        user_id = g.user["id"]
        can_manage = selected is not None and (g.user["admin"] or selected["author_id"] == user_id)
        attachments = []
        if module == "publications" and selected is not None:
            attachments = g.db.execute(
                """SELECT id,name,length(content) AS size FROM publication_attachments
                   WHERE publication_id=? ORDER BY id""", (selected_id,),
            ).fetchall()
        responses = []
        if selected is not None:
            responses = g.db.execute(
                """SELECT ipr_responses.*,users.email FROM ipr_responses
                   JOIN users ON users.id=ipr_responses.user_id WHERE entry_id=? ORDER BY users.email""",
                (selected_id,),
            ).fetchall()
        own_response = next((response["value"] for response in responses if response["user_id"] == user_id), None)

        if request.method == "POST":
            action = request.form.get("action")
            if action in {"edit", "delete"} and not can_manage:
                abort(403)
            try:
                if action in {"create", "edit"}:
                    fields = entry_fields(module)
                    if module == "publications":
                        kept, removed, uploads = publication_uploads(attachments if action == "edit" else [])
                        if not fields[1] and not (kept or uploads):
                            raise ValueError("Ajoutez un texte ou une pièce jointe à la publication.")
                    if action == "create":
                        cursor = g.db.execute(
                            """INSERT INTO ipr_entries(group_id,module,author_id,title,body,starts_at,ends_at,link,capacity,questions)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""", (scope, module, user_id, *fields),
                        )
                        selected_id = cursor.lastrowid
                    else:
                        if module == "questionnaires" and responses and json.loads(fields[-1]) != json.loads(selected["questions"]):
                            raise ValueError("Les questions ne peuvent plus être modifiées après la première réponse.")
                        if module == "creneaux" and fields[-2] < len(responses):
                            raise ValueError("La capacité doit couvrir les réservations existantes.")
                        g.db.execute(
                            """UPDATE ipr_entries SET title=?,body=?,starts_at=?,ends_at=?,link=?,capacity=?,questions=?
                               WHERE id=?""", (*fields, selected_id),
                        )
                    if module == "publications":
                        g.db.executemany(
                            "DELETE FROM publication_attachments WHERE publication_id=? AND id=?",
                            [(selected_id, attachment_id) for attachment_id in removed],
                        )
                        g.db.executemany(
                            "INSERT INTO publication_attachments(publication_id,name,content) VALUES(?,?,?)",
                            [(selected_id, name, content) for name, content in uploads],
                        )
                    flash("Enregistré.")
                elif action == "delete":
                    g.db.execute("DELETE FROM ipr_entries WHERE id=?", (selected_id,))
                    selected_id = None
                    flash("Élément supprimé.")
                elif action in {"respond", "withdraw"} and selected is not None:
                    if module not in RSVP | {"creneaux", "questionnaires"}:
                        abort(400)
                    if action == "withdraw":
                        g.db.execute("DELETE FROM ipr_responses WHERE entry_id=? AND user_id=?", (selected_id, user_id))
                    else:
                        value = request.form.get("response")
                        if module in RSVP and value not in {"yes", "no"}:
                            abort(400)
                        if module == "creneaux":
                            if own_response is None and len(responses) >= selected["capacity"]:
                                raise ValueError("Ce créneau est complet.")
                            value = "reserved"
                        if module == "questionnaires":
                            answers = [request.form.get(f"answer_{index}", "").strip()
                                       for index, _ in enumerate(json.loads(selected["questions"]))]
                            if any(not answer or len(answer) > 2000 for answer in answers):
                                raise ValueError("Répondez à chaque question en 2 000 caractères maximum.")
                            value = json.dumps(answers, ensure_ascii=False)
                        g.db.execute(
                            """INSERT INTO ipr_responses VALUES(?,?,?)
                               ON CONFLICT(entry_id,user_id) DO UPDATE SET value=excluded.value""",
                            (selected_id, user_id, value),
                        )
                    flash("Réponse mise à jour.")
                else:
                    abort(400)
                g.db.commit()
            except ValueError as error:
                flash(str(error))
                mode = "edit" if action == "edit" else "create" if action == "create" else None
                return redirect(url_for("ipr.module_page", module=module, entry=selected_id, mode=mode), code=303)
            return redirect(url_for("ipr.module_page", module=module, entry=selected_id), code=303)

        mode = request.args.get("mode")
        if mode == "edit" and not can_manage:
            abort(403)
        questions = json.loads(selected["questions"]) if selected else []
        return render_template(
            "ipr_module.html", module=module, configured=True, entries=entries, selected=selected,
            mode=mode, can_manage=can_manage, questions=questions, attachments=attachments,
            answers=json.loads(own_response) if module == "questionnaires" and own_response else [],
            results=[(response["email"], json.loads(response["value"])) for response in responses]
                    if module == "questionnaires" and can_manage else [],
            own_response=own_response, response_count=len(responses),
            yes_count=sum(response["value"] == "yes" for response in responses),
            no_count=sum(response["value"] == "no" for response in responses),
            roster=[(response["email"], response["value"]) for response in responses]
                   if can_manage and module in RSVP | {"creneaux"} else [],
        )

    app.register_blueprint(bp)
