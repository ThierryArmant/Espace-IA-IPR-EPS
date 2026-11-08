"""Send a Hub notification about a document to authorized IPR members."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

from ipr_modules import group_id, has_access


def register_document_notifications(app, allowed, get_node, rights, view, write, nuage_documents):
    bp = Blueprint("notifications", __name__)
    signer = URLSafeTimedSerializer(app.secret_key, salt="ipr-nuage-notification")

    def nuage_reference(node, name, link):
        return signer.dumps([g.user["id"], node["id"], name, link])

    def inbox_entries(*, unread_only=False):
        rows = g.db.execute(
            """SELECT n.id,n.node_id,n.created_at,s.email AS sender,r.is_read
               FROM document_notification_recipients r
               JOIN document_notifications n ON n.id=r.notification_id
               JOIN users s ON s.id=n.sender_id
               WHERE r.user_id=? AND n.group_id=? AND (?=0 OR r.is_read=0)
               ORDER BY n.id DESC""", (g.user["id"], group_id(), unread_only),
        )
        return [(row, node) for row in rows if (node := get_node(row["node_id"])) is not None and rights(node) & view]

    @bp.app_context_processor
    def notification_controls():
        visible = has_access() and group_id() is not None
        unread = len(inbox_entries(unread_only=True)) if visible and request.endpoint != "notifications.inbox" else None
        return {"can_notify_documents": visible, "notification_unread": unread,
                "nuage_notification_reference": nuage_reference}

    @bp.route("/dossier/<int:node_id>/notifier", methods=["GET", "POST"])
    def compose(node_id):
        if not has_access() or (scope := group_id()) is None:
            abort(403)
        reference = request.args.get("nuage")
        node = allowed(node_id, view, "folder" if reference else "file")
        allowed(node_id if reference else node["parent"], write, "folder")
        name = node["name"]
        nuage_file = ""
        if reference:
            if len(reference) > 4096:
                abort(400)
            try:
                sender_id, folder_id, name, nuage_file = signer.loads(reference, max_age=3600)
            except (BadData, ValueError, TypeError):
                abort(400, "Rouvrez le dossier pour sélectionner à nouveau le document.")
            if (sender_id, folder_id) != (g.user["id"], node_id):
                abort(404)

        people = g.db.execute(
            """SELECT u.id,u.email,u.admin FROM memberships m JOIN users u ON u.id=m.user_id
               WHERE m.group_id=? AND u.active=1 AND u.id<>? ORDER BY u.email""",
            (scope, g.user["id"]),
        )
        eligible = {person["id"]: person for person in people if rights(node, person) & view}
        if request.method == "POST":
            if request.form.get("audience") == "all":
                selected = set(eligible)
            elif request.form.get("audience") == "selected":
                values = request.form.getlist("recipients")
                if any(not value.isascii() or not value.isdecimal() or len(value) > 19 for value in values):
                    abort(400, "Sélection de destinataires invalide.")
                selected = {int(value) for value in values}
            else:
                abort(400, "Choisissez les destinataires.")
            if not selected or not selected <= eligible.keys():
                flash("Choisissez au moins un collègue qui a accès au contenu.")
                return redirect(url_for("notifications.compose", node_id=node_id, nuage=reference), code=303)

            notification_id = g.db.execute(
                "INSERT INTO document_notifications(group_id,sender_id,node_id,nuage_file) VALUES(?,?,?,?)",
                (scope, g.user["id"], node_id, nuage_file),
            ).lastrowid
            g.db.executemany(
                "INSERT INTO document_notification_recipients(notification_id,user_id) VALUES(?,?)",
                [(notification_id, user_id) for user_id in selected],
            )
            g.db.commit()
            flash(f"Notification envoyée dans le Hub à {len(selected)} collègue(s).")
            return redirect(url_for("folder" if reference else "document", node_id=node_id), code=303)
        return render_template("notification_compose.html", node=node, name=name,
                               people=eligible.values(), nuage=bool(reference))

    @bp.get("/notifications/<int:notification_id>/document")
    def locate(notification_id):
        if not has_access() or group_id() is None:
            abort(403)
        row = g.db.execute(
            """SELECT n.node_id,n.nuage_file FROM document_notifications n
               JOIN document_notification_recipients r ON r.notification_id=n.id
               WHERE n.id=? AND r.user_id=? AND n.group_id=?""",
            (notification_id, g.user["id"], group_id()),
        ).fetchone()
        if row is None or not row["nuage_file"]:
            abort(404)
        allowed(row["node_id"], view, "folder")
        connected, files, error = nuage_documents(row["node_id"])
        if not connected:
            flash("Connectez Nuage dans ce dossier, puis revenez à la notification.")
        elif error:
            flash(error)
        else:
            for name, link in files:
                if link == row["nuage_file"]:
                    return redirect(url_for("folder", node_id=row["node_id"], q=name), code=303)
            flash("Ce document n’est plus visible dans ce dossier avec votre compte Nuage.")
        return redirect(url_for("folder", node_id=row["node_id"]), code=303)

    @bp.route("/notifications", methods=["GET", "POST"])
    def inbox():
        if not has_access() or group_id() is None:
            abort(403)
        entries = inbox_entries()
        if request.method == "POST":
            entry_id = request.form.get("notification", type=int)
            if entry_id not in {row["id"] for row, _ in entries}:
                abort(404)
            g.db.execute(
                "UPDATE document_notification_recipients SET is_read=1 WHERE user_id=? AND notification_id=?",
                (g.user["id"], entry_id),
            )
            g.db.commit()
            return redirect(url_for("notifications.inbox"), code=303)
        return render_template("notifications.html", entries=entries,
                               notification_unread=sum(not row["is_read"] for row, _ in entries))

    app.register_blueprint(bp)
