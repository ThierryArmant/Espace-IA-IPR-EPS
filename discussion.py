"""Discussion commune de l'espace, affichée sous « En ligne » dans l'explorateur.

Pas d'autre connexion que celle du Hub : l'identité affichée est l'adresse mail
du compte. La discussion est éphémère : quand plus personne n'a le Hub ouvert
depuis IDLE_SECONDS, tous les messages sont effacés (et au plus tard après
RETENTION_DAYS jours).
"""
import sqlite3
import time

from flask import Blueprint, abort, g, jsonify, request

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat(
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_created ON chat(created);
CREATE TABLE IF NOT EXISTS chat_state(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""
RETENTION_DAYS = 30
MAX_LENGTH = 500
PAGE = 60
IDLE_SECONDS = 10 * 60


def register_discussion(app):
    bp = Blueprint("discussion", __name__)

    def serialize(row):
        mine = row["user_id"] == g.user["id"]
        return {
            "id": row["id"],
            "auteur": row["email"] or "compte supprimé",
            "nom": row["name"] or "",
            "texte": row["body"],
            "heure": time.strftime("%d/%m %H:%M", time.localtime(row["created"])),
            "moi": mine,
            "supprimable": mine or bool(g.user["admin"]),
        }

    def keep_alive():
        """Efface la discussion si plus personne ne l'a ouverte depuis IDLE_SECONDS, puis note
        qu'elle est ouverte (au plus une écriture par minute)."""
        now = int(time.time())
        row = g.db.execute("SELECT value FROM chat_state WHERE key='ouverte'").fetchone()
        last = row[0] if row else 0
        if now - last < 60:
            return
        try:
            if now - last > IDLE_SECONDS:
                g.db.execute("DELETE FROM chat")
            g.db.execute("INSERT INTO chat_state VALUES('ouverte', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now,))
            g.db.commit()
        except sqlite3.Error:
            g.db.rollback()

    @bp.get("/discussion/messages")
    def messages():
        keep_alive()
        after = request.args.get("apres", 0, type=int)
        rows = g.db.execute(
            """SELECT chat.*, users.email, users.name FROM chat LEFT JOIN users ON users.id = chat.user_id
               WHERE chat.id > ? AND chat.created >= ? ORDER BY chat.id DESC LIMIT ?""",
            (after, int(time.time()) - RETENTION_DAYS * 86400, PAGE)).fetchall()
        ids = [row[0] for row in g.db.execute("SELECT id FROM chat WHERE created >= ?",
                                              (int(time.time()) - RETENTION_DAYS * 86400,))]
        return jsonify(messages=[serialize(row) for row in reversed(rows)], existants=ids)

    @bp.post("/discussion")
    def send():
        body = " ".join(request.form.get("texte", "").split())
        if not body:
            abort(400, "Message vide.")
        if len(body) > MAX_LENGTH:
            abort(400, f"Message trop long ({MAX_LENGTH} caractères au plus).")
        keep_alive()
        now = int(time.time())
        g.db.execute("DELETE FROM chat WHERE created < ?", (now - RETENTION_DAYS * 86400,))
        g.db.execute("INSERT INTO chat(user_id, body, created) VALUES(?, ?, ?)", (g.user["id"], body, now))
        g.db.commit()
        return jsonify(ok=True)

    @bp.post("/discussion/<int:message_id>/supprimer")
    def delete(message_id):
        row = g.db.execute("SELECT user_id FROM chat WHERE id=?", (message_id,)).fetchone()
        if row is None:
            abort(404)
        if row["user_id"] != g.user["id"] and not g.user["admin"]:
            abort(403)
        g.db.execute("DELETE FROM chat WHERE id=?", (message_id,))
        g.db.commit()
        return jsonify(ok=True)

    app.register_blueprint(bp)
